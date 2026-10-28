
import os
import logging

import yfinance as yf

from fx_research.db import get_connection


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

SYMBOLS = {
    "AUD/JPY": "AUDJPY=X",
    "EUR/JPY": "EURJPY=X",
}


def collect_symbol(symbol: str, ticker: str) -> int:
    """5分足を取得し、Neonへ保存する。"""
    data = yf.download(
        ticker,
        period="5d",
        interval="5m",
        auto_adjust=False,
        progress=False,
        threads=False,
    )

    if data.empty:
        logging.warning("%s: 価格データがありません", symbol)
        return 0

    # yfinanceの列がMultiIndexの場合にも対応する
    if getattr(data.columns, "nlevels", 1) > 1:
        data.columns = data.columns.get_level_values(0)

    required = {"Open", "High", "Low", "Close"}
    if not required.issubset(data.columns):
        raise ValueError(
            f"{symbol}: 必要な価格列がありません: {list(data.columns)}"
        )

    rows = []
    for timestamp, bar in data.iterrows():
        if bar[["Open", "High", "Low", "Close"]].isna().any():
            continue

        rows.append(
            (
                symbol,
                timestamp.to_pydatetime(),
                float(bar["Open"]),
                float(bar["High"]),
                float(bar["Low"]),
                float(bar["Close"]),
                "yfinance",
            )
        )

    if not rows:
        logging.warning("%s: 保存可能な価格データがありません", symbol)
        return 0

    sql = """
        INSERT INTO price_bars
            (symbol, timestamp, open, high, low, close, source)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (symbol, timestamp) DO NOTHING
    """

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(sql, rows)
            inserted = cur.rowcount

    logging.info(
        "%s: 取得=%d本、今回の新規登録=%d本",
        symbol,
        len(rows),
        inserted,
    )
    return inserted


def main():
    total = 0

    for symbol, ticker in SYMBOLS.items():
        try:
            total += collect_symbol(symbol, ticker)
        except Exception:
            logging.exception("%s: 価格データ取得・保存に失敗", symbol)

    logging.info("ORION価格収集終了：新規登録合計=%d本", total)


if __name__ == "__main__":
    main()
