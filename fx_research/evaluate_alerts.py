import os
import math
from datetime import timedelta, time
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


def check_interval_continuity(alert_time, target_time, actual_timestamps):
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
    missing_alert_bar_count = 0

    # 未評価アラートと必要な価格データをまとめて取得する。
    # アラート発生時の価格足が欠けていても、アラート自体を除外しない。
    # 中間足の時刻も同時に取得する。
    # 過去のdata_gaps履歴だけでは評価をスキップしない。

    sql = """
        SELECT
            a.id,
