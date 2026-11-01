
import os
from collections import defaultdict
from statistics import mean, median

import psycopg


def analyze_alert_results():
    database_url = os.environ["DATABASE_URL"]

    results = defaultdict(list)
    total_alerts = 0

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*)
                FROM market_alerts
                """
            )
            total_alerts = cur.fetchone()[0]

            cur.execute(
                """
                SELECT
                    a.symbol,
                    a.change_pct,
                    e.horizon_minutes,
                    e.price_change_pct
                FROM market_alerts AS a
                JOIN alert_evaluations AS e
                  ON e.alert_id = a.id
                ORDER BY
                    a.symbol,
                    e.horizon_minutes,
                    a.alert_timestamp
                """
            )

            rows = cur.fetchall()

    print("=" * 60)
    print("PROJECT ORION: ALERT RESULT ANALYSIS")
    print("=" * 60)

    print(f"Total alerts       : {total_alerts}")
    print(f"Evaluation records : {len(rows)}")

    for symbol, alert_change, horizon, future_change in rows:
        if alert_change is None or future_change is None:
            continue

        alert_change = float(alert_change)
        future_change = float(future_change)

        if alert_change > 0:
            direction = "UP"
        elif alert_change < 0:
            direction = "DOWN"
        else:
            direction = "NEUTRAL"

        results[(symbol, horizon, direction)].append(
            (alert_change, future_change)
        )

    print("\n--- RESULTS BY SYMBOL / HORIZON / DIRECTION ---")

    for key in sorted(results):
        symbol, horizon, direction = key
        values = results[key]

        alert_changes = [v[0] for v in values]
        future_changes = [v[1] for v in values]

        continuation = 0
        reversal = 0
        unchanged = 0

        for alert_change, future_change in values:
            if alert_change * future_change > 0:
                continuation += 1
            elif alert_change * future_change < 0:
                reversal += 1
            else:
                unchanged += 1

        count = len(values)

        continuation_rate = continuation / count * 100
        reversal_rate = reversal / count * 100

        print("\n" + "-" * 45)
        print(f"Symbol             : {symbol}")
        print(f"Alert direction    : {direction}")
        print(f"Horizon            : {horizon} minutes")
        print(f"Sample count       : {count}")
        print(f"Average alert move : {mean(alert_changes):.5f}%")
        print(f"Average price move : {mean(future_changes):.5f}%")
        print(f"Median price move  : {median(future_changes):.5f}%")
        print(f"Continuation       : {continuation} ({continuation_rate:.1f}%)")
        print(f"Reversal           : {reversal} ({reversal_rate:.1f}%)")
        print(f"Unchanged          : {unchanged}")

    print("\n" + "=" * 60)
    print("Project ORION: analysis finished.")
    print("=" * 60)


if __name__ == "__main__":
    analyze_alert_results()
