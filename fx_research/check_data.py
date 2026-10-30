
import logging
from datetime import time, timedelta
from zoneinfo import ZoneInfo

from fx_research.db import get_connection


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

BAR_INTERVAL_MINUTES = 5
NEW_YORK = ZoneInfo("America/New_York")



def is_market_open(timestamp) -> bool:
    """ニューヨーク時間を基準にFX市場の週末休場を判定する。"""

    local_time = timestamp.astimezone(NEW_YORK)

    weekday = local_time.weekday()
    clock = local_time.time()

    # 土曜日は休場
    if weekday == 5:
        return False

    # 日曜日は17時から再開
    if weekday == 6:
        return clock >= time(17, 0)

    # 金曜日は17時に終了
    if weekday == 4:
        return clock < time(17, 0)

    # 月曜日から木曜日は営業
    return True




def count_open_slots(previous, current) -> int:
    """2つのデータ時刻の間にある、欠損した営業時間内の5分区間を数える。"""

    count = 0
    timestamp = previous + timedelta(minutes=BAR_INTERVAL_MINUTES)

    # currentは次に存在するデータなので、欠損区間には含めない
    while timestamp < current:
        if is_market_open(timestamp):
            count += 1

        timestamp += timedelta(minutes=BAR_INTERVAL_MINUTES)

    return count



def check_symbol(symbol: str) -> None:
    """価格データの品質と市場営業時間内の空白を確認する。"""

    sql = """
        WITH ordered AS (
            SELECT
                timestamp,
                open,
                high,
                low,
                close,
                LAG(timestamp) OVER (ORDER BY timestamp) AS prev_timestamp
            FROM price_bars
            WHERE symbol = %s
        )
        SELECT
            COUNT(*) AS total_rows,
            COUNT(DISTINCT timestamp) AS unique_timestamps,
            MIN(timestamp) AS first_timestamp,
            MAX(timestamp) AS last_timestamp,
            COUNT(*) FILTER (
                WHERE high < low
                   OR high < open
                   OR high < close
                   OR low > open
                   OR low > close
            ) AS invalid_ohlc,
            COUNT(*) FILTER (
                WHERE prev_timestamp IS NOT NULL
                  AND timestamp - prev_timestamp < INTERVAL '5 minutes'
            ) AS short_intervals,
            COUNT(*) FILTER (
                WHERE prev_timestamp IS NOT NULL
                  AND timestamp - prev_timestamp > INTERVAL '5 minutes'
            ) AS long_intervals
        FROM ordered
    """

    gaps_sql = """
        WITH ordered AS (
            SELECT
                timestamp,
                LAG(timestamp) OVER (ORDER BY timestamp) AS prev_timestamp
            FROM price_bars
            WHERE symbol = %s
        )
        SELECT
            prev_timestamp,
            timestamp,
            timestamp - prev_timestamp AS interval_length
        FROM ordered
        WHERE prev_timestamp IS NOT NULL
          AND timestamp - prev_timestamp > INTERVAL '5 minutes'
        ORDER BY timestamp
    """

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (symbol,))
            result = cur.fetchone()

            cur.execute(gaps_sql, (symbol,))
            gaps = cur.fetchall()

    total, unique, first, last, invalid, short_gaps, long_gaps = result

    print(f"\n--- {symbol} ---")
    print(f"データ本数             : {total}")
    print(f"異なる時刻の数         : {unique}")
    print(f"最初の時刻             : {first}")
    print(f"最後の時刻             : {last}")
    print(f"価格の整合性エラー     : {invalid}")
    print(f"5分未満の間隔          : {short_gaps}")
    print(f"5分を超える間隔        : {long_gaps}")

    closed_only = 0
    suspicious = 0

    for previous, current, duration in gaps:
        open_slots = count_open_slots(previous, current)
        open_minutes = open_slots * BAR_INTERVAL_MINUTES

        print("\n時間間隔の詳細:")
        print(f"  前のデータ           : {previous}")
        print(f"  次のデータ           : {current}")
        print(f"  経過時間             : {duration}")
        print(f"  営業時間内の5分区間  : {open_slots}区間")
        print(f"  営業時間内の時間     : 約{open_minutes}分")

        if open_slots == 0:
            closed_only += 1
            print("  判定                 : 市場休場時間内の空白")
        else:
            suspicious += 1
            print("  判定                 : 市場営業時間を含む空白・要確認")

    print("\n空白の集計:")
    print(f"  市場休場時間内のみ   : {closed_only}件")
    print(f"  営業時間を含む空白   : {suspicious}件")

    if total == 0:
        print("判定: データがありません")
    elif total != unique or invalid > 0 or short_gaps > 0:
        print("判定: データの確認が必要です")
    elif suspicious > 0:
        print("判定: 営業時間内のデータ欠損の疑いがあります")
    else:
        print("判定: 基本チェック合格。検出された空白は市場休場時間内です")


def main():
    for symbol in ("AUD/JPY", "EUR/JPY"):
        try:
            check_symbol(symbol)
        except Exception:
            logging.exception("%s: 品質チェックに失敗", symbol)
            raise


if __name__ == "__main__":
    main()
