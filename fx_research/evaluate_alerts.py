
import os
import math
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

import psycopg



HORIZONS_MINUTES = (5, 15, 30, 60)
BAR_INTERVAL_MINUTES = 5

NEW_YORK = ZoneInfo("America/New_York")


def is_market_open(timestamp):
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


def is_valid_price(price):
    """価格が正の有限数値であることを確認する。"""

    if price is None:
        return False

    try:
        value = float(price)
    except (TypeError, ValueError, OverflowError):
        return False

    return math.isfinite(value) and value > 0


def check_interval_continuity(
    alert_time,
    target_time,
    actual_timestamps,
):
    """
    アラートから評価時刻までの5分足を確認する。

    市場休場時間は欠損として扱わない。
    市場営業時間内の足が不足していれば不合格とする。
    """

    actual_set = set(actual_timestamps)
    missing_timestamps = []

    expected_time = alert_time + timedelta(
        minutes=BAR_INTERVAL_MINUTES
    )

    while expected_time <= target_time:

        if is_market_open(expected_time):
            if expected_time not in actual_set:
                missing_timestamps.append(expected_time)

        expected_time += timedelta(
            minutes=BAR_INTERVAL_MINUTES
        )

    return missing_timestamps


def evaluate_alerts():

    database_url = os.environ.get("DATABASE_URL")

    if not database_url:
        raise RuntimeError(
            "環境変数 DATABASE_URL が設定されていません"
        )

    evaluated_count = 0
    pending_count = 0
    incomplete_count = 0
    invalid_count = 0

    # 未評価アラートと必要な価格データをまとめて取得する。
    # 中間足の時刻も同時に取得する。
    # 過去のdata_gaps履歴だけでは評価をスキップしない。

    sql = """
        SELECT
            a.id,
            a.symbol,
            a.alert_timestamp,
            p.close AS alert_close,
            h.horizon_minutes,
            target.target_time,
            fp.timestamp AS future_timestamp,
            fp.close AS future_close,
            COALESCE(
                interval_bars.timestamps,
                ARRAY[]::timestamptz[]
            ) AS interval_timestamps

        FROM market_alerts AS a

        JOIN price_bars AS p
          ON p.symbol = a.symbol
         AND p.timestamp = a.alert_timestamp

        CROSS JOIN unnest(%s::int[])
            AS h(horizon_minutes)

        CROSS JOIN LATERAL (
            SELECT
                a.alert_timestamp
                + h.horizon_minutes * INTERVAL '1 minute'
                AS target_time
        ) AS target

        LEFT JOIN alert_evaluations AS e
          ON e.alert_id = a.id
         AND e.horizon_minutes = h.horizon_minutes

        LEFT JOIN price_bars AS fp
          ON fp.symbol = a.symbol
         AND fp.timestamp = target.target_time

        LEFT JOIN LATERAL (
            SELECT
                ARRAY_AGG(
                    m.timestamp
                    ORDER BY m.timestamp
                ) AS timestamps

            FROM price_bars AS m

            WHERE m.symbol = a.symbol
              AND m.timestamp > a.alert_timestamp
              AND m.timestamp <= target.target_time

        ) AS interval_bars ON TRUE

        WHERE e.id IS NULL

        ORDER BY
            a.alert_timestamp,
            a.id,
            h.horizon_minutes
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

        ON CONFLICT (
            alert_id,
            horizon_minutes
        )
        DO NOTHING
    """

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:

            cur.execute(
                sql,
                (list(HORIZONS_MINUTES),),
            )

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
                interval_timestamps,
            ) in rows:

                # アラート発生時の価格を確認する。
                if not is_valid_price(alert_close):

                    if alert_id not in invalid_alert_ids:
                        print(
                            f"Invalid alert price: "
                            f"id={alert_id}, "
                            f"symbol={symbol}"
                        )

                        invalid_alert_ids.add(alert_id)

                    invalid_count += 1
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
                if not is_valid_price(future_close):

                    print(
                        f"Invalid future price: "
                        f"alert_id={alert_id}, "
                        f"symbol={symbol}, "
                        f"horizon={horizon}m"
                    )

                    invalid_count += 1
                    continue

                # 中間5分足の連続性を確認する。
                missing_timestamps = check_interval_continuity(
                    alert_time,
                    target_time,
                    interval_timestamps,
                )

                if missing_timestamps:

                    print(
                        f"Incomplete: alert_id={alert_id}, "
                        f"symbol={symbol}, "
                        f"horizon={horizon}m, "
                        f"missing_bars={len(missing_timestamps)}, "
                        f"first_missing={missing_timestamps[0]}"
                    )

                    incomplete_count += 1
                    continue

                # 従来と同じ価格変化率を計算する。
                alert_price = float(alert_close)
                future_price = float(future_close)

                price_change_pct = (
                    (future_price - alert_price)
                    / alert_price
                ) * 100

                if not math.isfinite(price_change_pct):

                    print(
                        f"Invalid price change: "
                        f"alert_id={alert_id}, "
                        f"symbol={symbol}, "
                        f"horizon={horizon}m"
                    )

                    invalid_count += 1
                    continue

                insert_records.append(
                    (
                        alert_id,
                        horizon,
                        future_time,
                        future_price,
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
    print(f"Incomplete intervals: {incomplete_count}")
    print(f"Invalid prices: {invalid_count}")


if __name__ == "__main__":
    evaluate_alerts()
