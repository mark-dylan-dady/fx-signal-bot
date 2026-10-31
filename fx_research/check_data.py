
import logging
from datetime import time, timedelta
from zoneinfo import ZoneInfo

from fx_research.db import get_connection


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

BAR_INTERVAL_MINUTES = 5
BAR_INTERVAL_SECONDS = BAR_INTERVAL_MINUTES * 60

NEW_YORK = ZoneInfo("America/New_York")


def is_market_open(timestamp) -> bool:
    """ニューヨーク時間を基準にFX市場の週末休場を判定する。"""

    local_time = timestamp.astimezone(NEW_YORK)

    weekday = local_time.weekday()
    clock = local_time.time()

    if weekday == 5:
        return False

    if weekday == 6:
        return clock >= time(17, 0)

    if weekday == 4:
        return clock < time(17, 0)

    return True


def count_open_slots(previous, current) -> int:
    """欠損した市場営業時間内の5分区間を数える。"""

    count = 0
    timestamp = previous + timedelta(minutes=BAR_INTERVAL_MINUTES)

    while timestamp < current:
        if is_market_open(timestamp):
            count += 1

        timestamp += timedelta(minutes=BAR_INTERVAL_MINUTES)

    return count


def classify_gap(previous, current, duration):
    """データ間隔を3種類に分類する。"""

    duration_seconds = duration.total_seconds()

    if duration_seconds % BAR_INTERVAL_SECONDS != 0:
        return "UNKNOWN", 0

    open_slots = count_open_slots(previous, current)

    if open_slots == 0:
        return "MARKET_CLOSED", open_slots

    return "SOURCE_GAP", open_slots


def save_gap_history(symbol: str, gaps: list) -> int:
    """
    欠損履歴をNeonに保存する。

    同じ通貨ペア・前後の時刻の欠損が既に存在する場合は、
    新規登録せず検出回数と最終検出日時を更新する。
    """

    if not gaps:
        return 0

    sql = """
        INSERT INTO data_gaps (
            symbol,
            previous_timestamp,
            next_timestamp,
            duration_minutes,
            missing_bars,
            classification
        )
        VALUES (%s, %s, %s, %s, %s, %s)

        ON CONFLICT (
            symbol,
            previous_timestamp,
            next_timestamp
        )
        DO UPDATE SET
            duration_minutes = EXCLUDED.duration_minutes,
            missing_bars = EXCLUDED.missing_bars,
            classification = EXCLUDED.classification,
            last_detected_at = NOW(),
            detection_count = data_gaps.detection_count + 1
    """

    records = []

    for previous, current, duration, classification, open_slots in gaps:

        if classification == "MARKET_CLOSED":
            continue

        # UNKNOWNの場合は実際の経過時間を記録する。
        if classification == "UNKNOWN":
            duration_minutes = duration.total_seconds() / 60
            missing_bars = 0
        else:
            duration_minutes = open_slots * BAR_INTERVAL_MINUTES
            missing_bars = open_slots

        records.append(
            (
                symbol,
                previous,
                current,
                duration_minutes,
                missing_bars,
                classification,
            )
        )

    if not records:
        return 0

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(sql, records)

    logging.info(
        "%s: 欠損履歴を%d件保存・更新しました",
        symbol,
        len(records),
    )

    return len(records)


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

    (
        total,
        unique,
        first,
        last,
        invalid,
        short_gaps,
        long_gaps,
    ) = result

    print(f"\n--- {symbol} ---")
    print(f"データ本数             : {total}")
    print(f"異なる時刻の数         : {unique}")
    print(f"最初の時刻             : {first}")
    print(f"最後の時刻             : {last}")
    print(f"価格の整合性エラー     : {invalid}")
    print(f"5分未満の間隔          : {short_gaps}")
    print(f"5分を超える間隔        : {long_gaps}")

    market_closed = 0
    source_gap = 0
    unknown = 0

    classified_gaps = []

    for previous, current, duration in gaps:

        classification, open_slots = classify_gap(
            previous,
            current,
            duration,
        )

        classified_gaps.append(
            (
                previous,
                current,
                duration,
                classification,
                open_slots,
            )
        )

        open_minutes = open_slots * BAR_INTERVAL_MINUTES

        print("\n時間間隔の詳細:")
        print(f"  前のデータ           : {previous}")
        print(f"  次のデータ           : {current}")
        print(f"  経過時間             : {duration}")
        print(f"  営業時間内の5分区間  : {open_slots}区間")
        print(f"  営業時間内の時間     : 約{open_minutes}分")

        if classification == "MARKET_CLOSED":
            market_closed += 1
            print("  分類                 : MARKET_CLOSED")
            print("  判定                 : 市場休場時間内の空白")

        elif classification == "SOURCE_GAP":
            source_gap += 1
            print("  分類                 : SOURCE_GAP")
            print("  判定                 : データ配信元の欠損の疑い")

        else:
            unknown += 1
            print("  分類                 : UNKNOWN")
            print("  判定                 : 原因不明・時間間隔を要確認")

    print("\n空白の集計:")
    print(f"  MARKET_CLOSED       : {market_closed}件")
    print(f"  SOURCE_GAP          : {source_gap}件")
    print(f"  UNKNOWN             : {unknown}件")

    # 市場休場以外の欠損履歴をNeonに保存する。
    saved = save_gap_history(symbol, classified_gaps)

    print(f"  Neon保存・更新       : {saved}件")

    if total == 0:
        print("判定: データがありません")

    elif (
        total != unique
        or invalid > 0
        or short_gaps > 0
    ):
        print("判定: データの整合性に問題があります")

    elif source_gap > 0 or unknown > 0:
        print("判定: データ欠損または原因不明の空白があります")

    else:
        print("判定: 基本チェック合格。検出された空白は市場休場時間内です")


def main():
    for symbol in ("AUD/JPY", "EUR/JPY"):
        try:
            check_symbol(symbol)

        except Exception:
            logging.exception(
                "%s: 品質チェックに失敗",
                symbol,
            )
            raise


if __name__ == "__main__":
    main()
