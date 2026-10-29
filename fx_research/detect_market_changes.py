
import os
import psycopg


def detect_market_changes():
    database_url = os.environ["DATABASE_URL"]

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    symbol,
                    COUNT(*) AS bar_count,
                    MAX(timestamp) AS latest_timestamp
                FROM price_bars
                GROUP BY symbol
                ORDER BY symbol
            """)

            rows = cur.fetchall()

    if not rows:
        print("No price data found.")
        return

    for symbol, bar_count, latest_timestamp in rows:
        print(f"Symbol: {symbol}")
        print(f"Bars available: {bar_count}")
        print(f"Latest timestamp: {latest_timestamp}")


if __name__ == "__main__":
    detect_market_changes()
