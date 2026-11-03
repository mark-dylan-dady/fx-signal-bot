
import os
from collections import defaultdict
from statistics import mean, median

import psycopg


HISTORY_BARS = 302

TREND_FLAT_THRESHOLD_PCT = 0.02

VOLATILITY_LOW_MAX = 0.8
VOLATILITY_HIGH_MIN = 1.5

HORIZONS_MINUTES = (5, 15, 30, 60)


def classify_trend(bars, minutes):
    """アラート直前のトレンドを判定する。"""

    required_bars = minutes // 5 + 1

    if len(bars) < required_bars:
        return "UNKNOWN"

    selected = bars[-required_bars:]

    for previous, current in zip(selected, selected[1:]):
        if (current[0] - previous[0]).total_seconds() != 300:
            return "UNKNOWN"

    first_close = selected[0][1]
    last_close = selected[-1][1]

    if first_close <= 0:
        return "UNKNOWN"

    change_pct = (
        (last_close - first_close) / first_close
    ) * 100

    if change_pct > TREND_FLAT_THRESHOLD_PCT:
        return "UP"

    if change_pct < -TREND_FLAT_THRESHOLD_PCT:
        return "DOWN"

    return "FLAT"


def calculate_returns(bars):
    """連続する5分足の変動率を計算する。"""

    returns = []

    for previous, current in zip(bars, bars[1:]):
        previous_time, previous_close = previous
        current_time, current_close = current

        if (current_time - previous_time).total_seconds() != 300:
            continue

        if previous_close <= 0 or current_close <= 0:
            continue

        change_pct = (
            (current_close - previous_close) / previous_close
        ) * 100

        returns.append(change_pct)

    return returns


def classify_volatility(bars):
    """直前1時間の変動率を過去の中央値と比較する。"""

    if len(bars) < HISTORY_BARS:
        return "UNKNOWN", None

    recent_bars = bars[-13:]
    recent_returns = calculate_returns(recent_bars)

    if len(recent_returns) != 12:
        return "UNKNOWN", None

    baseline_bars = bars[:-13]
    baseline_returns = calculate_returns(baseline_bars)

    if len(baseline_returns) < 30:
        return "UNKNOWN", None

    baseline_magnitude = median(
        abs(value) for value in baseline_returns
    )

    if baseline_magnitude <= 0:
        return "UNKNOWN", None

    recent_magnitude = mean(
        abs(value) for value in recent_returns
    )

    ratio = recent_magnitude / baseline_magnitude

    if ratio < VOLATILITY_LOW_MAX:
        state = "LOW"
    elif ratio >= VOLATILITY_HIGH_MIN:
        state = "HIGH"
    else:
        state = "NORMAL"

    return state, ratio


def analyze_market_state(bars, alert_time):
    """アラート発生前の市場状態を分析する。"""

    if not bars:
        return "UNKNOWN", "UNKNOWN", "UNKNOWN", None

    expected_time = alert_time.timestamp() - 300

    if bars[-1][0].timestamp() != expected_time:
        return "UNKNOWN", "UNKNOWN", "UNKNOWN", None

    trend_1h = classify_trend(bars, 60)
    trend_3h = classify_trend(bars, 180)

    volatility, volatility_ratio = classify_volatility(bars)

    return (
        trend_1h,
        trend_3h,
        volatility,
        volatility_ratio,
    )

def load_alerts(cur):
    """アラートと評価結果を読み込む。"""

    cur.execute(
        """
        SELECT
            a.id,
            a.symbol,
            a.alert_timestamp,
            a.direction,
            e.horizon_minutes,
            e.price_change_pct
        FROM market_alerts AS a
        LEFT JOIN alert_evaluations AS e
          ON e.alert_id = a.id
        ORDER BY a.alert_timestamp, a.id
        """
    )

    rows = cur.fetchall()
    alerts = {}

    for (
        alert_id,
        symbol,
        alert_time,
        direction,
        horizon,
        price_change,
    ) in rows:

        if alert_id not in alerts:
            alerts[alert_id] = {
                "symbol": symbol,
                "alert_time": alert_time,
                "direction": direction or "UNKNOWN",
                "evaluations": [],
            }

        if horizon is not None and price_change is not None:
            alerts[alert_id]["evaluations"].append(
                (int(horizon), float(price_change))
            )

    return alerts


def load_pre_alert_bars(cur, symbol, alert_time):
    """アラート発生時刻より前の価格データを取得する。"""

    cur.execute(
        """
        SELECT timestamp, close
        FROM price_bars
        WHERE symbol = %s
          AND timestamp < %s
        ORDER BY timestamp DESC
        LIMIT %s
        """,
        (symbol, alert_time, HISTORY_BARS),
    )

    rows = cur.fetchall()

    return [
        (timestamp, float(close))
        for timestamp, close in reversed(rows)
        if close is not None and float(close) > 0
    ]


def create_report():
    database_url = os.environ["DATABASE_URL"]

    grouped = defaultdict(list)

    total_alerts = 0
    analyzed_alerts = 0
    unknown_state_alerts = 0
    total_evaluations = 0

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:

            alerts = load_alerts(cur)
            total_alerts = len(alerts)

            print("=" * 78)
            print("PROJECT ORION: PRE-ALERT MARKET STATE ANALYSIS")
            print("=" * 78)
            print(f"Total alerts: {total_alerts}")

            for alert_id, alert in alerts.items():

                symbol = alert["symbol"]
                alert_time = alert["alert_time"]
                direction = alert["direction"].upper()

                bars = load_pre_alert_bars(
                    cur,
                    symbol,
                    alert_time,
                )

                (
                    trend_1h,
                    trend_3h,
                    volatility,
                    volatility_ratio,
                ) = analyze_market_state(
                    bars,
                    alert_time,
                )

                analyzed_alerts += 1

                if (
                    trend_1h == "UNKNOWN"
                    or trend_3h == "UNKNOWN"
                    or volatility == "UNKNOWN"
                ):
                    unknown_state_alerts += 1

                state_key = (
                    symbol,
                    direction,
                    trend_1h,
                    trend_3h,
                    volatility,
                )

                for horizon, price_change in alert["evaluations"]:
                    grouped[state_key + (horizon,)].append(
                        price_change
                    )
                    total_evaluations += 1

    print("\n" + "=" * 78)
    print("ANALYSIS SETTINGS")
    print("=" * 78)
    print("1-hour trend : Previous 60 minutes")
    print("3-hour trend : Previous 180 minutes")
    print("Volatility   : Recent 1-hour average / prior median")
    print(
        f"Trend FLAT threshold : "
        f"+/- {TREND_FLAT_THRESHOLD_PCT:.3f}%"
    )
    print(f"Volatility LOW       : Ratio < {VOLATILITY_LOW_MAX}")
    print(f"Volatility HIGH      : Ratio >= {VOLATILITY_HIGH_MIN}")

    print("\n" + "=" * 78)
    print("DATA SUMMARY")
    print("=" * 78)
    print(f"Total alerts              : {total_alerts}")
    print(f"Alerts analyzed           : {analyzed_alerts}")
    print(f"Alerts with unknown state : {unknown_state_alerts}")
    print(f"Total evaluations         : {total_evaluations}")

    print("\n" + "=" * 78)
    print("RESULTS BY PRE-ALERT MARKET STATE")
    print("=" * 78)

    if not grouped:
        print("No evaluation data found.")

    for key in sorted(grouped.keys()):

        (
            symbol,
            direction,
            trend_1h,
            trend_3h,
            volatility,
            horizon,
        ) = key

        changes = grouped[key]
        average_change = mean(changes)

        continuation = 0
        reversal = 0
        flat = 0

        if direction == "UP":
            aligned_changes = changes
        elif direction == "DOWN":
            aligned_changes = [-value for value in changes]
        else:
            aligned_changes = []

        for value in aligned_changes:
            if value > 0:
                continuation += 1
            elif value < 0:
                reversal += 1
            else:
                flat += 1

        print("\n" + "-" * 78)
        print(
            f"{symbol} | ALERT={direction} | "
            f"1H={trend_1h} | 3H={trend_3h} | "
            f"VOL={volatility}"
        )
        print(
            f"After {horizon:2d} minutes | "
            f"N={len(changes):3d} | "
            f"Average change={average_change:+.5f}%"
        )

        if direction in ("UP", "DOWN"):
            match_rate = continuation / len(changes) * 100

            print(
                f"Continuation={match_rate:.1f}% | "
                f"Continue={continuation} | "
                f"Reverse={reversal} | Flat={flat}"
            )
        else:
            print(
                "Direction match: N/A "
                "(UNKNOWN alert direction)"
            )

    print("\n" + "=" * 78)
    print("PROJECT ORION: PRE-ALERT ANALYSIS FINISHED")
    print("=" * 78)


if __name__ == "__main__":
    create_report()
