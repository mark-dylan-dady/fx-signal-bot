import logging
from datetime import time, timedelta
from zoneinfo import ZoneInfo

from fx_research.db import get_connection


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

BAR_INTERVAL_MINUTES = 5
BAR_INTERVAL_SECONDS = BAR_INTERVAL_MINUTES * 60

NEW_YORK = ZoneInfo("America/New_York")

SYMBOLS = (
    "AUD/JPY",
    "EUR/JPY",
    "EUR/USD",
    "USD/JPY",
    "AUD/USD",
)


def is_market_open(timestamp) -> bool:
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


def count_open_slots(previous, current) -> int:
    """欠損した市場営業時間内の5分区間を数える。"""

    count = 0
    timestamp = previous + timedelta(minutes=BAR_INTERVAL_MINUTES)

    while timestamp < current:
        if is_market_open(timestamp):
            count += 1

        timestamp += timedelta(minutes=BAR_INTERVAL_MINUTES)

    return count


def classify_gap(previous, current, duration):
    """データ間隔を3種類に分類する。"""

    duration_seconds = duration.total_seconds()

    if duration_seconds % BAR_INTERVAL_SECONDS != 0:
        return "UNKNOWN", 0

    open_slots = count_open_slots(previous, current)

    if open_slots == 0:
        return "MARKET_CLOSED", open_slots

    return "SOURCE_GAP", open_slots


def save_gap_history(conn, gaps: list) -> int:
    """5通貨ペア分の欠損履歴を1回の接続でまとめて保存する。"""

    if not gaps:
        return 0

    sql = """
        INSERT INTO data_gaps (
            symbol,
            previous_timestamp,
            next_timestamp,
            duration_minutes,
            missing_bars,
            classification
        )
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (
            symbol,
            previous_timestamp,
            next_timestamp
