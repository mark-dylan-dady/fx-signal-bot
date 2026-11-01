
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fx_research.db import get_connection


JST = ZoneInfo("Asia/Tokyo")
SYMBOLS = ["AUD/JPY", "EUR/JPY"]
HORIZONS = [5, 15, 60]


def to_jst(timestamp):
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(JST)


def report_orion_status():
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=24)

    print("=" * 78)
    print("PROJECT ORION: SYSTEM STATUS REPORT")
    print(f"Report time: {now.astimezone(JST):%Y-%m-%d %H:%M:%S JST}")
    print("=" * 78)

    with get_connection() as conn:
        with conn.cursor() as cur:

            # Price data status
            cur.execute("""
                SELECT
                    symbol,
                    COUNT(*) AS total_bars,
                    MAX(timestamp) AS latest_timestamp,
                    COUNT(*) FILTER (
                        WHERE timestamp >= %s
                    ) AS recent_bars
                FROM price_bars
                GROUP BY symbol
                ORDER BY symbol
            """, (since,))

            price_rows = cur.fetchall()

            print("\n" + "-" * 78)
            print("1. PRICE DATA STATUS")
            print("-" * 78)

            price_status = {}

            for symbol, total, latest, recent in price_rows:
                price_status[symbol] = latest

                latest_text = (
                    to_jst(latest).strftime("%Y-%m-%d %H:%M:%S JST")
                    if latest else "NO DATA"
                )

                print(f"\n{symbol}")
                print(f"  Total bars       : {total:,}")
                print(f"  Latest bar       : {latest_text}")
                print(f"  Bars in last 24h : {recent:,}")

            for symbol in SYMBOLS:
                if symbol not in price_status:
                    print(f"\n{symbol}: NO DATA")

            # Alert status
            cur.execute("""
                SELECT
                    symbol,
                    COUNT(*) AS total_alerts,
                    COUNT(*) FILTER (
                        WHERE alert_timestamp >= %s
                    ) AS recent_alerts
                FROM market_alerts
                GROUP BY symbol
                ORDER BY symbol
            """, (since,))

            alert_rows = cur.fetchall()

            print("\n" + "-" * 78)
            print("2. MARKET ALERT STATUS")
            print("-" * 78)

            for symbol, total, recent in alert_rows:
                print(
                    f"{symbol:10s} | "
                    f"Total: {total:5d} | "
                    f"Last 24h: {recent:4d}"
                )

            for symbol in SYMBOLS:
                if symbol not in {row[0] for row in alert_rows}:
                    print(f"{symbol:10s} | No alerts recorded")

            # Evaluation status
            cur.execute("""
                SELECT
                    e.horizon_minutes,
                    COUNT(*) AS total_evaluations,
                    COUNT(*) FILTER (
                        WHERE e.evaluated_at >= %s
                    ) AS recent_evaluations,
                    COUNT(*) FILTER (
                        WHERE e.future_close IS NULL
                    ) AS pending
                FROM alert_evaluations e
                GROUP BY e.horizon_minutes
                ORDER BY e.horizon_minutes
            """, (since,))

            evaluation_rows = cur.fetchall()

            print("\n" + "-" * 78)
            print("3. ALERT EVALUATION STATUS")
            print("-" * 78)

            evaluation_map = {}

            for horizon, total, recent, pending in evaluation_rows:
                evaluation_map[horizon] = True
                print(
                    f"{horizon:2d} minutes | "
                    f"Total: {total:5d} | "
                    f"Last 24h: {recent:4d} | "
                    f"Pending: {pending:4d}"
                )

            for horizon in HORIZONS:
                if horizon not in evaluation_map:
                    print(
                        f"{horizon:2d} minutes | "
                        "No evaluation records"
                    )

    # Basic freshness check
    print("\n" + "-" * 78)
    print("4. BASIC DATA FRESHNESS CHECK")
    print("-" * 78)

    for symbol in SYMBOLS:
        latest = price_status.get(symbol)

        if latest is None:
            print(f"{symbol:10s} | WARNING: No price data")
            continue

        age_hours = (now - latest).total_seconds() / 3600

        if age_hours <= 1:
            status = "RECENT"
        elif age_hours <= 24:
            status = "CHECK"
        else:
            status = "STALE"

        print(
            f"{symbol:10s} | "
            f"Age: {age_hours:6.1f} hours | "
            f"{status}"
        )

    print("\n" + "=" * 78)
    print("ORION STATUS REPORT COMPLETED")
    print("=" * 78)


if __name__ == "__main__":
    report_orion_status()
