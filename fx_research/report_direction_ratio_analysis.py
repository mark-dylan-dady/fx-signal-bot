
import os
from collections import defaultdict

import psycopg


RATIO_BANDS = [
    ("3.0-4.0", 3.0, 4.0),
    ("4.0-5.0", 4.0, 5.0),
    ("5.0-8.0", 5.0, 8.0),
    ("8.0+", 8.0, None),
]

HORIZONS = (5, 15, 30, 60)


def get_ratio_band(ratio):
    """ratioを分析用の区分に分類する。"""
    for label, lower, upper in RATIO_BANDS:
        if ratio >= lower and (
            upper is None or ratio < upper
        ):
            return label

    return None


def load_evaluations():
    """アラート方向・ratio・評価結果を取得する。"""
    database_url = os.environ["DATABASE_URL"]

    query = """
        SELECT
            a.symbol,
            a.direction,
            a.ratio,
            e.horizon_minutes,
            e.price_change_pct
        FROM market_alerts AS a
        INNER JOIN alert_evaluations AS e
            ON e.alert_id = a.id
        WHERE
            a.direction IN ('UP', 'DOWN', 'UNKNOWN')
            AND a.ratio >= 3.0
            AND e.price_change_pct IS NOT NULL
        ORDER BY
            a.symbol,
            a.direction,
            a.ratio,
            e.horizon_minutes
    """

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(query)
            return cur.fetchall()


def analyze():
    rows = load_evaluations()

    print("=" * 78)
    print("PROJECT ORION: DIRECTION × RATIO ANALYSIS")
    print("=" * 78)

    print(f"\nTotal evaluations: {len(rows)}")

    if not rows:
        print("No evaluation data found.")
        return

    grouped = defaultdict(list)

    for (
        symbol,
        direction,
        ratio,
        horizon,
        price_change,
    ) in rows:

        ratio = float(ratio)
        price_change = float(price_change)

        band = get_ratio_band(ratio)

        if band is None or horizon not in HORIZONS:
            continue

        # 方向に合わせて価格変化の符号をそろえる。
        # UP   : 上昇すればプラス
        # DOWN : 下降すればプラス
        # UNKNOWN : 方向一致率の分析対象外
        if direction == "UP":
            aligned_change = price_change
        elif direction == "DOWN":
            aligned_change = -price_change
        else:
            aligned_change = None

        grouped[
            (symbol, direction, band, horizon)
        ].append(
            (price_change, aligned_change)
        )

    symbols = sorted({row[0] for row in rows})

    for symbol in symbols:
        print("\n" + "=" * 78)
        print(f"SYMBOL: {symbol}")
        print("=" * 78)

        for direction in ("UP", "DOWN", "UNKNOWN"):

            print(f"\n--- ALERT DIRECTION: {direction} ---")

            for band, _, _ in RATIO_BANDS:

                print(f"\n[RATIO {band}]")

                for horizon in HORIZONS:

                    key = (
                        symbol,
                        direction,
                        band,
                        horizon,
                    )

                    values = grouped.get(key, [])

                    if not values:
                        print(
                            f"  {horizon:2}m | "
                            "No data"
                        )
                        continue

                    count = len(values)

                    raw_changes = [
                        item[0] for item in values
                    ]

                    avg_change = (
                        sum(raw_changes) / count
                    )

                    up_count = sum(
                        1 for value in raw_changes
                        if value > 0
                    )

                    down_count = sum(
                        1 for value in raw_changes
                        if value < 0
                    )

                    flat_count = (
                        count - up_count - down_count
                    )

                    print(
                        f"  {horizon:2}m | "
                        f"N={count:3} | "
                        f"Avg={avg_change:+.5f}% | "
                        f"UP={up_count / count * 100:5.1f}% | "
                        f"DOWN={down_count / count * 100:5.1f}% | "
                        f"FLAT={flat_count / count * 100:5.1f}%"
                    )

                    # UNKNOWNには方向一致の概念がない。
                    if direction == "UNKNOWN":
                        continue

                    aligned_values = [
                        item[1] for item in values
                        if item[1] is not None
                    ]

                    aligned_count = len(aligned_values)

                    if aligned_count == 0:
                        continue

                    continuation = sum(
                        1 for value in aligned_values
                        if value > 0
                    )

                    reversal = sum(
                        1 for value in aligned_values
                        if value < 0
                    )

                    flat = (
                        aligned_count
                        - continuation
                        - reversal
                    )

                    continuation_rate = (
                        continuation / aligned_count * 100
                    )

                    average_aligned = (
                        sum(aligned_values)
                        / aligned_count
                    )

                    print(
                        f"       Direction match: "
                        f"{continuation_rate:.1f}% | "
                        f"Continue={continuation} | "
                        f"Reverse={reversal} | "
                        f"Flat={flat} | "
                        f"Avg aligned={average_aligned:+.5f}%"
                    )

    print("\n" + "=" * 78)
    print("ANALYSIS COMPLETE")
    print("=" * 78)


if __name__ == "__main__":
    analyze()
