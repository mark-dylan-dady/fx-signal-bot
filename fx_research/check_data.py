
import logging

from fx_research.db import get_connection


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)


def check_symbol(symbol: str) -> None:
    """価格データの品質と5分足の時間間隔を確認する。"""

    sql = """
        WITH ordered AS (
            SELECT
                timestamp,
                open,
                high,
                low,
                close,
                LAG(timestamp) OVER (ORDER BY timestamp) AS prev_timestamp
            FROM price_bars
            WHERE symbol = %s
        )
        SELECT
            COUNT(*) AS total_rows,
            COUNT(DISTINCT timestamp) AS unique_timestamps,
            MIN(timestamp) AS first_timestamp,
            MAX(timestamp) AS last_timestamp,
            COUNT(*) FILTER (
                WHERE high < low
                   OR high < open
                   OR high < close
                   OR low > open
                   OR low > close
            ) AS invalid_ohlc,
            COUNT(*) FILTER (
                WHERE prev_timestamp IS NOT NULL
                  AND timestamp - prev_timestamp < INTERVAL '5 minutes'
            ) AS short_intervals,
            COUNT(*) FILTER (
                WHERE prev_timestamp IS NOT NULL
                  AND timestamp - prev_timestamp > INTERVAL '5 minutes'
            ) AS long_intervals
        FROM ordered
    """

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (symbol,))
            result = cur.fetchone()

    total, unique, first, last, invalid, short_gaps, long_gaps = result

    print(f"\n--- {symbol} ---")
    print(f"データ本数             : {total}")
    print(f"異なる時刻の数         : {unique}")
    print(f"最初の時刻             : {first}")
    print(f"最後の時刻             : {last}")
    print(f"価格の整合性エラー     : {invalid}")
    print(f"5分未満の間隔           : {short_gaps}")
    print(f"5分を超える間隔         : {long_gaps}")

    if total == 0:
        print("判定: データがありません")
    elif total != unique or invalid > 0 or short_gaps > 0:
        print("判定: データの確認が必要です")
    else:
        print("判定: 基本チェック合格。時間間隔の詳細を確認してください")


def main():
    for symbol in ("AUD/JPY", "EUR/JPY"):
        try:
            check_symbol(symbol)
        except Exception:
            logging.exception("%s: 品質チェックに失敗", symbol)
            raise


if __name__ == "__main__":
    main()
