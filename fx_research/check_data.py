

import logging

from fx_research.db import get_connection


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)


def check_symbol(symbol: str) -> None:
    """通貨ペアごとの価格データ品質を確認する。"""

    sql = """
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
            ) AS invalid_ohlc
        FROM price_bars
        WHERE symbol = %s
    """

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (symbol,))
            result = cur.fetchone()

    total, unique, first, last, invalid = result

    print(f"\n--- {symbol} ---")
    print(f"データ本数       : {total}")
    print(f"異なる時刻の数   : {unique}")
    print(f"最初の時刻       : {first}")
    print(f"最後の時刻       : {last}")
    print(f"価格の整合性エラー: {invalid}")

    if total == 0:
        print("判定: データがありません")
    elif total != unique:
        print("判定: 同一時刻の重複があります")
    elif invalid > 0:
        print("判定: 価格データの確認が必要です")
    else:
        print("判定: 基本チェック合格")


def main():
    for symbol in ("AUD/JPY", "EUR/JPY"):
        try:
            check_symbol(symbol)
        except Exception:
            logging.exception("%s: 品質チェックに失敗", symbol)
            raise


if __name__ == "__main__":
    main()
