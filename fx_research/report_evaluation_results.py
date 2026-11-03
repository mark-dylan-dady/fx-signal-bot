
import os

import psycopg


HORIZONS_MINUTES = (5, 15, 30, 60)

# 変化なしと判定する範囲（％）
FLAT_THRESHOLD = 0.001


def report_evaluation_results():
    database_url = os.environ["DATABASE_URL"]

    sql = """
        SELECT
            a.symbol,
            a.direction,
            a.ratio,
            e.horizon_minutes,
            e.price_change_pct
        FROM market_alerts AS a
        JOIN alert_evaluations AS e
          ON e.alert_id = a.id
        WHERE e.price_change_pct IS NOT NULL
        ORDER BY a.symbol, e.horizon_minutes
    """

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()

    print("=" * 78)
    print("PROJECT ORION: EVALUATION ANALYSIS REPORT")
    print("=" * 78)

    if not rows:
        print("No evaluation data available.")
        return

    print(f"\nTotal evaluations: {len(rows)}")

    symbols = sorted(set(row[0] for row in rows))

    for symbol in symbols:
        print("\n" + "-" * 78)
        print(f"SYMBOL: {symbol}")
        print("-" * 78)

        for horizon in HORIZONS_MINUTES:
            selected = [
                row for row in rows
                if row[0] == symbol and row[3] == horizon
            ]

            if not selected:
                print(f"\n{horizon} minutes: No data")
                continue

            changes = [float(row[4]) for row in selected]
            ratios = [float(row[2]) for row in selected]

            count = len(changes)
            average = sum(changes) / count

            up = sum(
                1 for value in changes
                if value > FLAT_THRESHOLD
            )

            down = sum(
                1 for value in changes
                if value < -FLAT_THRESHOLD
            )

            flat = count - up - down

            max_up = max(changes)
            max_down = min(changes)

            avg_ratio = sum(ratios) / len(ratios)

            print(f"\n[{horizon} MINUTES]")
            print(f"  Evaluations       : {count}")
            print(f"  Average change    : {average:+.5f}%")
            print(f"  Up                : {up} ({up/count*100:.1f}%)")
            print(f"  Down              : {down} ({down/count*100:.1f}%)")
            print(f"  Flat              : {flat} ({flat/count*100:.1f}%)")
            print(f"  Maximum up        : {max_up:+.5f}%")
            print(f"  Maximum down      : {max_down:+.5f}%")
            print(f"  Average alert ratio: {avg_ratio:.2f}x")

    print("\n" + "=" * 78)
    print("PROJECT ORION: ANALYSIS COMPLETE")
    print("=" * 78)


if __name__ == "__main__":
    report_evaluation_results()
