
import logging
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fx_research.db import get_connection


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

SYMBOLS = (
    "AUD/JPY",
    "EUR/JPY",
    "EUR/USD",
    "USD/JPY",
    "AUD/USD",
)

BAR_INTERVAL_MINUTES = 5
BAR_INTERVAL_SECONDS = BAR_INTERVAL_MINUTES * 60
CHECK_HOURS = 2

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
    timestamp = previous + timedelta(
        minutes=BAR_INTERVAL_MINUTES
    )

    while timestamp < current:
        if is_market_open(timestamp):
            count += 1

        timestamp += timedelta(
            minutes=BAR_INTERVAL_MINUTES
        )

    return count


def classify_gap(previous, current, duration):
    """データ間隔を分類する。"""

    duration_seconds = duration.total_seconds()

    if duration_seconds % BAR_INTERVAL_SECONDS != 0:
        return "UNKNOWN", 0

    open_slots = count_open_slots(previous, current)

    if open_slots == 0:
        return "MARKET_CLOSED", 0

    return "SOURCE_GAP", open_slots


def check_recent_data():
    """直近2時間の価格データをまとめて検査する。"""

    checked_at = datetime.now(timezone.utc)
    cutoff = checked_at - timedelta(hours=CHECK_HOURS)

    sql = """
        WITH bounds AS (
            SELECT
                %s::timestamptz AS checked_at,
                %s::timestamptz AS cutoff
        ),

        boundary AS (
            SELECT DISTINCT ON (p.symbol)
                p.symbol,
                p.timestamp,
                p.open,
                p.high,
                p.low,
                p.close,
                FALSE AS is_recent
            FROM price_bars AS p
            CROSS JOIN bounds AS b
            WHERE p.symbol = ANY(%s)
              AND p.timestamp < b.cutoff
            ORDER BY p.symbol, p.timestamp DESC
        ),

        recent AS (
            SELECT
                p.symbol,
                p.timestamp,
                p.open,
                p.high,
                p.low,
                p.close,
                TRUE AS is_recent
            FROM price_bars AS p
            CROSS JOIN bounds AS b
            WHERE p.symbol = ANY(%s)
              AND p.timestamp >= b.cutoff
              AND p.timestamp <= b.checked_at
        ),

        combined AS (
            SELECT * FROM boundary
            UNION ALL
            SELECT * FROM recent
        ),

        ordered AS (
            SELECT
                symbol,
                timestamp,
                open,
                high,
                low,
                close,
                is_recent,
                LAG(timestamp) OVER (
                    PARTITION BY symbol
                    ORDER BY timestamp
                ) AS prev_timestamp
            FROM combined
        )

        SELECT
            o.symbol,
            o.timestamp,
            o.open,
            o.high,
            o.low,
            o.close,
            o.is_recent,
            o.prev_timestamp
        FROM ordered AS o
        ORDER BY o.symbol, o.timestamp
    """

    insert_sql = """
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
        DO NOTHING
    """

    results = {
        symbol: {
            "total": 0,
            "invalid": 0,
            "short": 0,
            "long": 0,
            "market_closed": 0,
            "source_gap": 0,
            "unknown": 0,
            "boundary_gap": 0,
            "last_timestamp": None,
        }
        for symbol in SYMBOLS
    }

    gap_records = []

    # 5通貨ペアを1回のDB接続で検査・履歴登録する。
    with get_connection() as conn:
        with conn.cursor() as cur:

            cur.execute(
                sql,
                (
                    checked_at,
                    cutoff,
                    list(SYMBOLS),
                    list(SYMBOLS),
                ),
            )

            rows = cur.fetchall()

            for (
                symbol,
                timestamp,
                open_price,
                high,
                low,
                close,
                is_recent,
                previous,
            ) in rows:

                result = results[symbol]

                if is_recent:
                    result["total"] += 1
                    result["last_timestamp"] = timestamp

                    # OHLCの整合性を確認する。
                    if (
                        high < low
                        or high < open_price
                        or high < close
                        or low > open_price
                        or low > close
                    ):
                        result["invalid"] += 1

                if previous is None:
                    continue

                duration = timestamp - previous

                if duration < timedelta(
                    minutes=BAR_INTERVAL_MINUTES
                ):
                    if is_recent:
                        result["short"] += 1
                    continue

                if duration == timedelta(
                    minutes=BAR_INTERVAL_MINUTES
                ):
                    continue

                # 境界より前から続く空白は、
                # 直近2時間だけの欠損とは断定できない。
                # 別集計にして履歴登録しない。
                if is_recent and previous < cutoff:
                    result["boundary_gap"] += 1
                    continue

                # 直近2時間内で確認された空白だけを検査する。
                if not is_recent:
                    continue

                result["long"] += 1

                classification, open_slots = classify_gap(
                    previous,
                    timestamp,
                    duration,
                )

                if classification == "MARKET_CLOSED":
                    result["market_closed"] += 1

                elif classification == "SOURCE_GAP":
                    result["source_gap"] += 1

                else:
                    result["unknown"] += 1

                if classification == "UNKNOWN":
                    duration_minutes = (
                        duration.total_seconds() / 60
                    )
                    missing_bars = 0
                else:
                    duration_minutes = (
                        open_slots * BAR_INTERVAL_MINUTES
                    )
                    missing_bars = open_slots

                gap_records.append(
                    (
                        symbol,
                        previous,
                        timestamp,
                        duration_minutes,
                        missing_bars,
                        classification,
                    )
                )

            # 欠損履歴を同じDB接続内で登録する。
            if gap_records:
                cur.executemany(
                    insert_sql,
                    gap_records,
                )

    print("\n========== PROJECT ORION ==========")
    print("       RECENT DATA QUALITY CHECK")
    print("===================================")
    print(f"検査対象期間: 直近{CHECK_HOURS}時間")
    print(f"検査時刻: {checked_at}")

    for symbol in SYMBOLS:
        result = results[symbol]

        print(f"\n--- {symbol} ---")
        print(f"直近データ本数       : {result['total']}")
        print(f"最新データ時刻       : {result['last_timestamp']}")
        print(f"価格整合性エラー     : {result['invalid']}")
        print(f"5分未満の間隔        : {result['short']}")
        print(f"5分超の間隔          : {result['long']}")
        print(f"境界をまたぐ空白     : {result['boundary_gap']}")
        print(f"MARKET_CLOSED       : {result['market_closed']}")
        print(f"SOURCE_GAP          : {result['source_gap']}")
        print(f"UNKNOWN             : {result['unknown']}")

        if result["total"] == 0:
            print("判定: 直近データがありません")

        elif (
            result["invalid"] > 0
            or result["short"] > 0
        ):
            print("判定: データ整合性に問題があります")

        elif (
            result["source_gap"] > 0
            or result["unknown"] > 0
        ):
            print("判定: 欠損または原因不明の空白があります")

        elif result["boundary_gap"] > 0:
            print("判定: 境界をまたぐ空白があります。全履歴検査で確認してください")

        else:
            print("判定: 直近データの基本チェック合格")

    print("\n-----------------------------------")
    print(f"欠損履歴の登録処理対象: {len(gap_records)}件")
    print("RECENT DATA CHECK FINISHED")
    print("-----------------------------------")


if __name__ == "__main__":
    check_recent_data()
