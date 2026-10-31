
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
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

# 直近7日間を評価対象にする
ANALYSIS_DAYS = 7

# 最新データの遅延を許容する時間
LATEST_DATA_GRACE_MINUTES = 15


def is_market_open(timestamp):
    """ニューヨーク時間を基準にFX市場の営業時間を判定する。"""
    local_time = timestamp.astimezone(NEW_YORK)
    weekday = local_time.weekday()
    hour = local_time.hour

    if weekday == 4 and hour >= 17:
        return False

    if weekday == 5:
        return False

    if weekday == 6 and hour < 17:
        return False

    return True


def generate_expected_slots(start_time, end_time):
    """市場営業時間内に存在するはずの5分足時刻を生成する。"""
    slots = []
    current = start_time.replace(second=0, microsecond=0)

    remainder = current.minute % BAR_INTERVAL_MINUTES
    if remainder:
        current += timedelta(minutes=BAR_INTERVAL_MINUTES - remainder)

    while current <= end_time:
        if is_market_open(current):
            slots.append(current)

        current += timedelta(minutes=BAR_INTERVAL_MINUTES)

    return slots


def fetch_price_data(start_time):
    """Neonから対象期間の価格データを取得する。"""
    sql = """
        SELECT symbol, timestamp, close
        FROM price_bars
        WHERE timestamp >= %s
          AND symbol IN (%s, %s)
        ORDER BY symbol, timestamp
    """

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql,
                (start_time, SYMBOLS[0], SYMBOLS[1]),
            )
            return cur.fetchall()


def evaluate_symbol(rows, symbol, expected_slots, now):
    """通貨ペアごとの取得品質を評価する。"""
    symbol_rows = [
        row for row in rows
        if row[0] == symbol
    ]

    actual_times = {
        row[1].replace(second=0, microsecond=0)
        for row in symbol_rows
    }
    
    expected_set = set(expected_slots)

    evaluation_end = now - timedelta(
        minutes=LATEST_DATA_GRACE_MINUTES
    )

    evaluated_set = {
        slot for slot in expected_set
        if slot <= evaluation_end
    }

    matched_times = actual_times & evaluated_set
    outside_times = actual_times - evaluated_set

    print(f"評価対象と一致したデータ : {len(matched_times)}")
    print(f"評価対象外のデータ       : {len(outside_times)}")

    if outside_times:
        print("【評価対象外データの詳細】")

        for timestamp in sorted(outside_times):
            if timestamp > evaluation_end:
                reason = "最新15分の猶予期間"
            elif not is_market_open(timestamp):
                reason = "市場休場時間"
            elif timestamp.minute % 5 != 0:
                reason = "5分足の時刻境界外"
            else:
                reason = "その他（要確認）"

            print(f"  {timestamp} : {reason}")

    valid_prices = sum(
        1 for row in symbol_rows
        if row[2] is not None and float(row[2]) > 0
    )

    # 最新15分間は配信遅延の可能性があるため評価から除外
    evaluation_end = now - timedelta(
        minutes=LATEST_DATA_GRACE_MINUTES
    )

    evaluated_slots = [
        slot for slot in expected_slots
        if slot <= evaluation_end
    ]

    missing_slots = [
        slot for slot in evaluated_slots
        if slot not in actual_times
    ]

    expected_count = len(evaluated_slots)
    actual_count = expected_count - len(missing_slots)

    success_rate = (
        actual_count / expected_count * 100
        if expected_count > 0
        else 0
    )

    print()
    print(f"【{symbol}】")
    print(f"保存データ行数       : {len(symbol_rows)}")
    print(f"有効な終値データ     : {valid_prices}")
    print(f"評価対象5分足本数    : {expected_count}")
    print(f"取得できた本数       : {actual_count}")
    print(f"欠損本数             : {len(missing_slots)}")
    print(f"取得成功率           : {success_rate:.2f}%")

    if symbol_rows:
        latest = max(row[1] for row in symbol_rows)
        print(f"最新データ（UTC）    : {latest}")
        print(
            "最新データ（日本）   : "
            f"{latest.astimezone(JAPAN)}"
        )

        delay = now - latest
        print(f"最新データの経過時間 : {delay.total_seconds() / 60:.1f} 分")

    if missing_slots:
        print("欠損時間帯（最大10件）:")
        for slot in missing_slots[:10]:
            print(f"  {slot.astimezone(JAPAN)}")

    return {
        "symbol": symbol,
        "expected": expected_count,
        "actual": actual_count,
        "missing": len(missing_slots),
        "success_rate": success_rate,
        "actual_times": actual_times,
        "missing_slots": missing_slots,
    }


def main():
    print()
    print("===================================")
    print("       PROJECT ORION")
    print("   DATA COLLECTION QUALITY")
    print("===================================")

    now = datetime.now(timezone.utc)
    start_time = now - timedelta(days=ANALYSIS_DAYS)

    print(f"評価期間（UTC）: {start_time} ～ {now}")
    print(f"評価期間       : 直近{ANALYSIS_DAYS}日間")

    try:
        rows = fetch_price_data(start_time)

        print(f"\n取得したDBデータ行数: {len(rows)}")

        expected_slots = generate_expected_slots(
            start_time,
            now,
        )

        results = []

        for symbol in SYMBOLS:
            result = evaluate_symbol(
                rows,
                symbol,
                expected_slots,
                now,
            )
            results.append(result)

        print()
        print("【2通貨ペアの比較】")

        if all(result["expected"] > 0 for result in results):
            total_expected = sum(
                result["expected"] for result in results
            )
            total_actual = sum(
                result["actual"] for result in results
            )

            overall_rate = total_actual / total_expected * 100

            print(f"全体取得成功率: {overall_rate:.2f}%")

        common_missing = (
            set(results[0]["missing_slots"])
            & set(results[1]["missing_slots"])
        )

        print(f"同時欠損5分足本数: {len(common_missing)}")

        for slot in sorted(common_missing)[:10]:
            print(f"  {slot.astimezone(JAPAN)}")

        print()
        print("===================================")
        print("       QUALITY CHECK COMPLETED")
        print("===================================")
        print()
        print("注意:")
        print("- 市場休場時間は評価対象から除外しています。")
        print("- 最新15分間は配信遅延を考慮して除外しています。")
        print("- 取得成功率は保存済みデータに基づく推定値です。")

    except Exception:
        logging.exception("データ収集品質の評価に失敗しました。")
        raise


if __name__ == "__main__":
    main()
