
import os
from collections import defaultdict
from statistics import mean, median

import psycopg


MIN_SAMPLE_NOTICE = 10
HORIZONS = (5, 15, 30, 60)


def load_alerts(cur):
    """アラートと評価結果を読み込む。"""

    cur.execute(
        """
        SELECT
            a.id,
            a.symbol,
            a.alert_timestamp,
            a.direction,
            e.horizon_minutes,
            e.price_change_pct
        FROM market_alerts AS a
        LEFT JOIN alert_evaluations AS e
          ON e.alert_id = a.id
        ORDER BY a.alert_timestamp, a.id
        """
    )

    rows = cur.fetchall()
    alerts = {}

    for (
        alert_id,
        symbol,
        alert_time,
        direction,
        horizon,
        price_change,
    ) in rows:

        if alert_id not in alerts:
            alerts[alert_id] = {
                "symbol": symbol,
                "alert_time": alert_time,
                "direction": direction or "UNKNOWN",
                "evaluations": [],
            }

        if horizon is not None and price_change is not None:
            alerts[alert_id]["evaluations"].append(
                (int(horizon), float(price_change))
            )

    return alerts


def calculate_statistics(changes, direction):
    """平均・中央値・継続率・反転率を計算する。"""

    count = len(changes)

    if count == 0:
        return None

    continuation = 0
    reversal = 0
    flat = 0

    if direction == "UP":
        aligned_changes = changes
    elif direction == "DOWN":
        aligned_changes = [-value for value in changes]
    else:
        aligned_changes = []

    for value in aligned_changes:
        if value > 0:
            continuation += 1
        elif value < 0:
            reversal += 1
        else:
            flat += 1

    if direction in ("UP", "DOWN"):
        continuation_rate = continuation / count * 100
        reversal_rate = reversal / count * 100
        flat_rate = flat / count * 100
    else:
        continuation_rate = None
        reversal_rate = None
        flat_rate = None

    return {
        "count": count,
        "average": mean(changes),
        "median": median(changes),
        "continuation": continuation,
        "reversal": reversal,
        "flat": flat,
        "continuation_rate": continuation_rate,
        "reversal_rate": reversal_rate,
        "flat_rate": flat_rate,
    }


def create_report():
    """通貨ペア別の基本統計レポートを作成する。"""

    database_url = os.environ["DATABASE_URL"]

    grouped = defaultdict(list)

    total_alerts = 0
    total_evaluations = 0

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:

            alerts = load_alerts(cur)
            total_alerts = len(alerts)

            for alert in alerts.values():

                symbol = alert["symbol"]
                direction = alert["direction"].upper()

                for horizon, price_change in alert["evaluations"]:

                    key = (symbol, direction, horizon)
                    grouped[key].append(price_change)

                    total_evaluations += 1

    print("=" * 78)
    print("PROJECT ORION: CURRENCY PAIR STATISTICS")
    print("=" * 78)

    print("\n" + "-" * 78)
    print("DATA SUMMARY")
    print("-" * 78)

    print(f"Total alerts       : {total_alerts}")
    print(f"Total evaluations  : {total_evaluations}")
    print(f"Minimum sample     : {MIN_SAMPLE_NOTICE}")

    print("\n" + "=" * 78)
    print("PAIR STATISTICS")
    print("=" * 78)

    symbols = sorted(set(key[0] for key in grouped))

    for symbol in symbols:

        print("\n" + "#" * 78)
        print(f"SYMBOL: {symbol}")
        print("#" * 78)

        for direction in ("UP", "DOWN"):

            print(f"\nDIRECTION: {direction}")

            for horizon in HORIZONS:

                key = (symbol, direction, horizon)
                changes = grouped.get(key, [])

                if not changes:
                    print(f"\n  {horizon:2d} MIN: No data")
                    continue

                stats = calculate_statistics(
                    changes,
                    direction,
                )

                print(f"\n  AFTER {horizon} MINUTES")
                print(f"    Sample count       : {stats['count']}")
                print(
                    f"    Average change     : "
                    f"{stats['average']:+.5f}%"
                )
                print(
                    f"    Median change      : "
                    f"{stats['median']:+.5f}%"
                )
                print(
                    f"    Continuation rate  : "
                    f"{stats['continuation_rate']:.1f}%"
                )
                print(
                    f"    Reversal rate      : "
                    f"{stats['reversal_rate']:.1f}%"
                )
                print(
                    f"    Flat rate          : "
                    f"{stats['flat_rate']:.1f}%"
                )

                if stats["count"] < MIN_SAMPLE_NOTICE:
                    print(
                        "    NOTE               : "
                        "Small sample; interpret with caution."
                    )

    print("\n" + "=" * 78)
    print("PROJECT ORION: PAIR STATISTICS FINISHED")
    print("=" * 78)


if __name__ == "__main__":
    create_report()
