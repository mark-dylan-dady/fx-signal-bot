import math
import os
from collections import defaultdict
from statistics import median

import psycopg


HORIZONS_MINUTES = (5, 15, 30, 60)

# 変化なしと判定する範囲（％）
FLAT_THRESHOLD = 0.001


def is_finite_number(value):
    """値を有限数として安全に扱えるか確認する。"""
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


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

    # 価格変化率が有限数でない行は集計から除外する。
    valid_rows = [
        row for row in rows
        if is_finite_number(row[4])
    ]
    invalid_change_count = len(rows) - len(valid_rows)

    print(f"Evaluation rows retrieved : {len(rows)}")
    print(f"Valid evaluations         : {len(valid_rows)}")
    print(f"Invalid price changes     : {invalid_change_count}")

    if not valid_rows:
        print("No valid evaluation data available.")
        return

    symbols = sorted(set(row[0] for row in valid_rows))

    for symbol in symbols:
        print("\\n" + "-" * 78)
        print(f"SYMBOL: {symbol}")
        print("-" * 78)

        for horizon in HORIZONS_MINUTES:
            selected = [
                row for row in valid_rows
                if row[0] == symbol and row[3] == horizon
            ]

            if not selected:
                print(f"\\n{horizon} minutes: No data")
                continue

            changes = [float(row[4]) for row in selected]
            count = len(changes)

            average = sum(changes) / count
            median_change = median(changes)

            up = sum(1 for value in changes if value > FLAT_THRESHOLD)
            down = sum(1 for value in changes if value < -FLAT_THRESHOLD)
            flat = count - up - down

            max_up = max(changes)
            max_down = min(changes)
