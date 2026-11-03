
import os

import psycopg


HORIZONS_MINUTES = (5, 15, 30, 60)

FLAT_THRESHOLD = 0.001

RATIO_GROUPS = (
    ("3.0 - 4.0", 3.0, 4.0),
    ("4.0 - 5.0", 4.0, 5.0),
    ("5.0 - 8.0", 5.0, 8.0),
    ("8.0+", 8.0, float("inf")),
)


def get_ratio_group(ratio):
    for label, lower, upper in RATIO_GROUPS:
        if lower <= ratio < upper:
            return label

    return "UNDER 3.0"


def report_ratio_analysis():

    database_url = os.environ["DATABASE_URL"]

    sql = """
        SELECT
            a.symbol,
            a.ratio,
            e.horizon_minutes,
            e.price_change_pct
        FROM market_alerts AS a
        JOIN alert_evaluations AS e
          ON e.alert_id = a.id
        WHERE e.price_change_pct IS NOT NULL
        ORDER BY a.symbol, a.ratio
    """

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()

    print("=" * 80)
    print("PROJECT ORION: ALERT RATIO ANALYSIS")
    print("=" * 80)

    print(f"\nTotal evaluations: {len(rows)}")

    if not rows:
        print("No evaluation data available.")
        return

    symbols = sorted(set(row[0] for row in rows))

    for symbol in symbols:

        print("\n" + "=" * 80)
        print(f"SYMBOL: {symbol}")
        print("=" * 80)

        for group_label, lower, upper in RATIO_GROUPS:

            group_rows = [
                row for row in rows
                if row[0] == symbol
                and lower <= float(row[1]) < upper
            ]

            print(f"\n--- RATIO GROUP: {group_label} ---")

            if not group_rows:
                print("No data")
                continue

            for horizon in HORIZONS_MINUTES:

                selected = [
                    row for row in group_rows
                    if row[2] == horizon
                ]

                if not selected:
                    print(f"{horizon}m: No data")
                    continue

                changes = [
                    float(row[3]) for row in selected
                ]

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

                print(f"\n  [{horizon} MINUTES]")
                print(f"    Count          : {count}")
                print(f"    Average change : {average:+.5f}%")
                print(
                    f"    Up             : {up} "
                    f"({up / count * 100:.1f}%)"
                )
                print(
                    f"    Down           : {down} "
                    f"({down / count * 100:.1f}%)"
                )
                print(
                    f"    Flat           : {flat} "
                    f"({flat / count * 100:.1f}%)"
                )
                print(
                    f"    Maximum up     : {max(changes):+.5f}%"
                )
                print(
                    f"    Maximum down   : {min(changes):+.5f}%"
                )

    print("\n" + "=" * 80)
    print("PROJECT ORION: RATIO ANALYSIS COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    report_ratio_analysis()
