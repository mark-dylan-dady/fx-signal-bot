
import os
from datetime import timedelta

import psycopg


HORIZONS_MINUTES = (5, 15, 60)


def evaluate_alerts():
    """未評価のアラートについて、検出後の価格変化を記録する。"""
    database_url = os.environ["DATABASE_URL"]

    evaluated_count = 0
    pending_count = 0

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    a.id,
                    a.symbol,
                    a.alert_timestamp,
                    p.close AS alert_close
                FROM market_alerts AS a
                JOIN price_bars AS p
                  ON p.symbol = a.symbol
                 AND p.timestamp = a.alert_timestamp
                ORDER BY a.alert_timestamp, a.id
                """
            )
            alerts = cur.fetchall()

            for alert_id, symbol, alert_time, alert_close in alerts:
                if alert_close is None or float(alert_close) <= 0:
                    print(
                        f"Skip alert {alert_id}: invalid alert price."
                    )
                    continue

                for horizon in HORIZONS_MINUTES:
                    cur.execute(
                        """
                        SELECT 1
                        FROM alert_evaluations
                        WHERE alert_id = %s
                          AND horizon_minutes = %s
                        """,
                        (alert_id, horizon),
                    )
                    if cur.fetchone():
                        continue

                    target_time = alert_time + timedelta(
                        minutes=horizon
                    )

                    # 目標時刻と完全一致する価格データだけを使う。
                    cur.execute(
                        """
                        SELECT timestamp, close
                        FROM price_bars
                        WHERE symbol = %s
                          AND timestamp = %s
                        LIMIT 1
                        """,
                        (symbol, target_time),
                    )
                    future = cur.fetchone()

                    if future is None:
                        pending_count += 1
                        continue

                    future_time, future_close = future

                    if future_close is None or float(future_close) <= 0:
                        pending_count += 1
                        continue

                    price_change_pct = (
                        (float(future_close) - float(alert_close))
                        / float(alert_close)
                    ) * 100

                    cur.execute(
                        """
                        INSERT INTO alert_evaluations (
                            alert_id,
                            horizon_minutes,
                            future_timestamp,
                            future_close,
                            price_change_pct
                        )
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (alert_id, horizon_minutes)
                        DO NOTHING
                        """,
                        (
                            alert_id,
                            horizon,
                            future_time,
                            float(future_close),
                            price_change_pct,
                        ),
                    )

                    if cur.rowcount:
                        evaluated_count += 1

    print("Project ORION: alert evaluation finished.")
    print(f"New evaluations saved: {evaluated_count}")
    print(f"Pending evaluations: {pending_count}")


if __name__ == "__main__":
    evaluate_alerts()
