
import os
from datetime import timedelta

import psycopg


HORIZONS_MINUTES = (5, 15, 30, 60)


def evaluate_alerts():
    database_url = os.environ["DATABASE_URL"]

    evaluated_count = 0
    pending_count = 0
    invalid_count = 0

    # 未評価のアラートと、必要な将来価格をまとめて取得する。
    # 過去のdata_gaps履歴だけでは評価をスキップしない。
    sql = """
        SELECT
            a.id,
            a.symbol,
            a.alert_timestamp,
            p.close AS alert_close,
            h.horizon_minutes,
            a.alert_timestamp
                + h.horizon_minutes * INTERVAL '1 minute'
                AS target_time,
            fp.timestamp AS future_timestamp,
            fp.close AS future_close
        FROM market_alerts AS a
        JOIN price_bars AS p
          ON p.symbol = a.symbol
         AND p.timestamp = a.alert_timestamp
        CROSS JOIN unnest(ARRAY[5, 15, 30, 60])
            AS h(horizon_minutes)
        LEFT JOIN alert_evaluations AS e
          ON e.alert_id = a.id
         AND e.horizon_minutes = h.horizon_minutes
        LEFT JOIN price_bars AS fp
          ON fp.symbol = a.symbol
         AND fp.timestamp =
             a.alert_timestamp
             + h.horizon_minutes * INTERVAL '1 minute'
        WHERE e.id IS NULL
        ORDER BY a.alert_timestamp, a.id, h.horizon_minutes
    """

    insert_sql = """
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
    """

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:

            cur.execute(sql)
            rows = cur.fetchall()

            print(
                f"未評価の組み合わせ: {len(rows)}"
            )

            insert_records = []
            invalid_alert_ids = set()

            for (
                alert_id,
                symbol,
                alert_time,
                alert_close,
                horizon,
                target_time,
                future_time,
                future_close,
            ) in rows:

                # アラート発生時の価格を確認する。
                if (
                    alert_close is None
                    or float(alert_close) <= 0
                ):
                    if alert_id not in invalid_alert_ids:
                        print(
                            f"Invalid alert price: "
                            f"id={alert_id}, "
                            f"symbol={symbol}"
                        )
                        invalid_alert_ids.add(alert_id)

                    continue

                # 評価時刻の価格がまだない場合は保留する。
                if future_time is None:
                    print(
                        f"Pending: alert_id={alert_id}, "
                        f"symbol={symbol}, "
                        f"horizon={horizon}m, "
                        f"target_time={target_time}"
                    )

                    pending_count += 1
                    continue

                # 将来価格の異常を確認する。
                if (
                    future_close is None
                    or float(future_close) <= 0
                ):
                    print(
                        f"Invalid future price: "
                        f"alert_id={alert_id}, "
                        f"symbol={symbol}, "
                        f"horizon={horizon}m, "
                        f"target_time={target_time}"
                    )

                    invalid_count += 1
                    continue

                # 従来と同じ価格変化率を計算する。
                price_change_pct = (
                    (
                        float(future_close)
                        - float(alert_close)
                    )
                    / float(alert_close)
                ) * 100

                insert_records.append(
                    (
                        alert_id,
                        horizon,
                        future_time,
                        float(future_close),
                        price_change_pct,
                    )
                )

            # 評価結果をまとめて登録する。
            if insert_records:
                cur.executemany(
                    insert_sql,
                    insert_records,
                )

                evaluated_count = cur.rowcount

    print("\nProject ORION: alert evaluation finished.")
    print(f"New evaluations saved: {evaluated_count}")
    print(f"Pending evaluations: {pending_count}")
    print(f"Invalid prices: {invalid_count}")


if __name__ == "__main__":
    evaluate_alerts()
