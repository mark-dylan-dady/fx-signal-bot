
import os
from collections import defaultdict
from statistics import mean, median

import psycopg

from fx_research.report_pre_alert_market_state import (
    load_alerts,
    load_pre_alert_bars,
    analyze_market_state,
)


MIN_SAMPLE_NOTICE = 10


def calculate_statistics(changes, direction):
    """値動きの統計とアラート方向に対する継続・反転を計算する。"""

    count = len(changes)

    average_change = mean(changes)
    median_change = median(changes)

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
        "average": average_change,
        "median": median_change,
        "continuation": continuation,
        "reversal": reversal,
        "flat": flat,
        "continuation_rate": continuation_rate,
        "reversal_rate": reversal_rate,
        "flat_rate": flat_rate,
    }


def create_report():
    """市場状態ごとの値動きを比較する。"""

    database_url = os.environ["DATABASE_URL"]

    grouped = defaultdict(list)

    total_alerts = 0
    analyzed_alerts = 0
    unknown_state_alerts = 0
    total_evaluations = 0

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:

            alerts = load_alerts(cur)
            total_alerts = len(alerts)

            for alert_id, alert in alerts.items():

                symbol = alert["symbol"]
                alert_time = alert["alert_time"]
                direction = alert["direction"].upper()

                bars = load_pre_alert_bars(
                    cur,
                    symbol,
                    alert_time,
                )

                (
                    trend_1h,
                    trend_3h,
                    volatility,
                    volatility_ratio,
                ) = analyze_market_state(
                    bars,
                    alert_time,
                )

                analyzed_alerts += 1

                if (
                    trend_1h == "UNKNOWN"
                    or trend_3h == "UNKNOWN"
                    or volatility == "UNKNOWN"
                ):
                    unknown_state_alerts += 1

                state_key = (
                    symbol,
                    direction,
                    trend_1h,
                    trend_3h,
                    volatility,
                )

                for horizon, price_change in alert["evaluations"]:

                    grouped[state_key + (horizon,)].append(
                        price_change
                    )

                    total_evaluations += 1

    print("=" * 78)
    print("PROJECT ORION: MARKET STATE COMPARISON REPORT")
    print("=" * 78)

    print("\n" + "-" * 78)
    print("DATA SUMMARY")
    print("-" * 78)

    print(f"Total alerts              : {total_alerts}")
    print(f"Alerts analyzed           : {analyzed_alerts}")
    print(f"Alerts with unknown state : {unknown_state_alerts}")
    print(f"Total evaluations         : {total_evaluations}")

    print("\n" + "-" * 78)
    print("ANALYSIS SETTINGS")
    print("-" * 78)

    print("Market state              : Existing pre-alert classification")
    print("Evaluation horizons       : 5, 15, 30, 60 minutes")
    print("Average                   : Mean price change")
    print("Median                    : Median price change")
    print("Continuation              : Movement in alert direction")
    print("Reversal                  : Movement against alert direction")
    print("Small sample warning      : N < 10")

    print("\n" + "=" * 78)
    print("COMPARISON RESULTS")
    print("=" * 78)

    if not grouped:
        print("No evaluation data found.")

    for key in sorted(grouped.keys()):

        (
            symbol,
            direction,
            trend_1h,
            trend_3h,
            volatility,
            horizon,
        ) = key

        changes = grouped[key]

        stats = calculate_statistics(
            changes,
            direction,
        )

        print("\n" + "-" * 78)

        print(
            f"{symbol} | ALERT={direction} | "
            f"1H={trend_1h} | 3H={trend_3h} | "
            f"VOL={volatility}"
        )

        print(f"After {horizon:2d} minutes")

        print(
            f"  Sample count       : {stats['count']}"
        )

        print(
            f"  Average change     : "
            f"{stats['average']:+.5f}%"
        )

        print(
            f"  Median change      : "
            f"{stats['median']:+.5f}%"
        )

        if direction in ("UP", "DOWN"):

            print(
                f"  Continuation rate  : "
                f"{stats['continuation_rate']:.1f}%"
            )

            print(
                f"  Reversal rate      : "
                f"{stats['reversal_rate']:.1f}%"
            )

            print(
                f"  Flat rate          : "
                f"{stats['flat_rate']:.1f}%"
            )

            print(
                f"  Counts             : "
                f"Continue={stats['continuation']} | "
                f"Reverse={stats['reversal']} | "
                f"Flat={stats['flat']}"
            )

        else:
            print(
                "  Continuation rate  : N/A "
                "(UNKNOWN alert direction)"
            )

        if stats["count"] < MIN_SAMPLE_NOTICE:
            print(
                "  NOTE               : "
                "Small sample; interpret with caution."
            )

    print("\n" + "=" * 78)
    print("PROJECT ORION: MARKET STATE COMPARISON FINISHED")
    print("=" * 78)


if __name__ == "__main__":
    create_report()
