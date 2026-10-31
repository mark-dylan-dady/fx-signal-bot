
import logging
from collections import Counter, defaultdict
from datetime import timedelta
from zoneinfo import ZoneInfo

from fx_research.db import get_connection


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

NEW_YORK = ZoneInfo("America/New_York")
JAPAN = ZoneInfo("Asia/Tokyo")

SYMBOLS = ("AUD/JPY", "EUR/JPY")
BAR_INTERVAL_MINUTES = 5

WEEKDAYS_JP = (
    "月曜日", "火曜日", "水曜日", "木曜日",
    "金曜日", "土曜日", "日曜日",
)


def is_market_open(timestamp):
    """ニューヨーク時間を基準にFX市場の営業時間を判定する。"""
    local_time = timestamp.astimezone(NEW_YORK)
    weekday = local_time.weekday()
    hour = local_time.hour

    # 金曜日17時以降は休場
    if weekday == 4 and hour >= 17:
        return False

    # 土曜日は休場
    if weekday == 5:
        return False

    # 日曜日17時より前は休場
    if weekday == 6 and hour < 17:
        return False

    return True


def inspect_missing_slots(previous, next_timestamp):
    """欠損区間内の最初・最後の市場営業中の5分足時刻を調べる。"""
    current = previous + timedelta(minutes=BAR_INTERVAL_MINUTES)

    first_missing = None
    last_missing = None
    count = 0

    while current < next_timestamp:
        if is_market_open(current):
            if first_missing is None:
                first_missing = current
            last_missing = current
            count += 1

        current += timedelta(minutes=BAR_INTERVAL_MINUTES)

    return first_missing, last_missing, count


def fetch_gap_history():
    """Neonから欠損履歴を取得する。"""
    sql = """
        SELECT
            symbol,
            previous_timestamp,
            next_timestamp,
            duration_minutes,
            missing_bars,
            classification,
            first_detected_at,
            last_detected_at,
            detection_count
        FROM data_gaps
        ORDER BY previous_timestamp, symbol
    """

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            return cur.fetchall()


def analyze_symbol(rows, symbol):
    """通貨ペアごとの欠損統計を表示する。"""
    selected = [row for row in rows if row[0] == symbol]

    print()
    print(f"【{symbol}】")
    print(f"欠損記録数       : {len(selected)} 件")

    if not selected:
        print("欠損記録はありません。")
        return

    durations = [float(row[3]) for row in selected]
    missing_bars = [int(row[4]) for row in selected]

    total_duration = sum(durations)
    average_duration = total_duration / len(durations)

    print(f"欠損時間合計     : {total_duration:.1f} 分")
    print(f"欠損時間平均     : {average_duration:.1f} 分")
    print(f"最大欠損時間     : {max(durations):.1f} 分")
    print(f"欠損5分足合計    : {sum(missing_bars)} 本")

    classifications = Counter(row[5] for row in selected)

    print("分類別記録数:")
    for classification, count in classifications.items():
        print(f"  {classification}: {count} 件")


def analyze_start_times(rows):
    """実際に欠損した最初の市場営業中の時刻を分析する。"""
    weekday_counts = Counter()
    hour_counts = Counter()

    print()
    print("【欠損開始時刻の分析】")

    for row in rows:
        symbol = row[0]
        previous = row[1]
        next_timestamp = row[2]
        classification = row[5]

        if classification != "SOURCE_GAP":
            continue

        first_missing, last_missing, count = inspect_missing_slots(
            previous,
            next_timestamp,
        )

        if first_missing is None:
            continue

        ny_time = first_missing.astimezone(NEW_YORK)
        jp_time = first_missing.astimezone(JAPAN)

        weekday = WEEKDAYS_JP[ny_time.weekday()]
        weekday_counts[weekday] += 1
        hour_counts[ny_time.hour] += 1

        print(f"{symbol}")
        print(f"  最初の欠損時刻（NY） : {ny_time:%Y-%m-%d %H:%M}")
        print(f"  最初の欠損時刻（日本）: {jp_time:%Y-%m-%d %H:%M}")
        print(f"  最後の欠損時刻（NY） : {last_missing.astimezone(NEW_YORK):%Y-%m-%d %H:%M}")
        print(f"  営業時間内の欠損本数 : {count} 本")

    print()
    print("曜日別の欠損記録数（NY時間）:")
    for weekday, count in weekday_counts.items():
        print(f"  {weekday}: {count} 件")

    print()
    print("時間帯別の欠損記録数（NY時間）:")
    for hour, count in sorted(hour_counts.items()):
        print(f"  {hour:02d}時台: {count} 件")


def analyze_shared_gaps(rows):
    """2通貨ペアで同じ境界時刻の欠損があるか調べる。"""
    groups = defaultdict(set)

    for row in rows:
        symbol = row[0]
        previous = row[1]
        next_timestamp = row[2]

        groups[(previous, next_timestamp)].add(symbol)

    shared = [
        (previous, next_timestamp, symbols)
        for (previous, next_timestamp), symbols in groups.items()
        if set(SYMBOLS).issubset(symbols)
    ]

    print()
    print("【AUD/JPY・EUR/JPY 共通欠損の分析】")

    if not shared:
        print("両通貨ペアで同じ欠損区間は見つかりませんでした。")
        return

    print(f"共通欠損区間数: {len(shared)} 件")

    for previous, next_timestamp, symbols in shared:
        print("-----------------------------------")
        print(f"欠損前の最終データ : {previous}")
        print(f"欠損後の最初のデータ: {next_timestamp}")
        print(f"対象通貨ペア       : {', '.join(sorted(symbols))}")


def main():
    print()
    print("===================================")
    print("       PROJECT ORION")
    print("       DATA GAP ANALYSIS")
    print("===================================")

    try:
        rows = fetch_gap_history()

        print(f"\n登録された欠損履歴: {len(rows)} 件")

        if not rows:
            print("分析対象の欠損履歴はありません。")
            return

        for symbol in SYMBOLS:
            analyze_symbol(rows, symbol)

        analyze_start_times(rows)
        analyze_shared_gaps(rows)

        print()
        print("===================================")
        print("       ANALYSIS COMPLETED")
        print("===================================")
        print()
        print("注意:")
        print("欠損記録が少ない場合、統計的な傾向とは断定できません。")
        print("今回の分析は、記録された欠損履歴に基づくものです。")

    except Exception:
        logging.exception("データ欠損分析に失敗しました。")
        raise


if __name__ == "__main__":
    main()
