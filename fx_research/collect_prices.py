import logging
import sys

import yfinance as yf

from fx_research.db import get_connection


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

SYMBOLS = {
    "AUD/JPY": "AUDJPY=X",
    "EUR/JPY": "EURJPY=X",
    "EUR/USD": "EURUSD=X",
    "USD/JPY": "USDJPY=X",
    "AUD/USD": "AUDUSD=X",
}

BAR_INTERVAL_MINUTES = 5

# AUD/USDの追加診断対象（UTC）
AUDUSD_DIAGNOSTIC_WINDOWS = [
    (
        "2026-10-30 21:00",
        "2026-10-30 21:30",
    ),
    (
        "2026-10-30 23:10",
        "2026-10-30 23:40",
    ),
]


def inspect_data(symbol, data):
    """取得した価格データの時間間隔と品質を調べる。"""

    timestamps = list(data.index)

    logging.info(
        "%s: Yahoo Finance取得件数=%d本",
        symbol,
        len(timestamps),
    )

    if len(timestamps) == 0:
        raise RuntimeError(f"{symbol}: 取得データがありません")

    timestamps.sort()

    duplicate_count = len(timestamps) - len(set(timestamps))

    logging.info(
        "%s: 重複時刻=%d件",
        symbol,
        duplicate_count,
    )

    gap_count = 0

    for previous, current in zip(timestamps, timestamps[1:]):
        duration = current - previous

        if duration.total_seconds() > BAR_INTERVAL_MINUTES * 60:
            gap_count += 1

            logging.warning(
                "%s: データ間隔の空白を検出",
                symbol,
            )
            logging.warning("  前のデータ: %s", previous)
            logging.warning("  次のデータ: %s", current)
            logging.warning("  経過時間: %s", duration)

    logging.info(
        "%s: 5分を超える時間間隔=%d件",
        symbol,
        gap_count,
    )

    logging.info(
        "%s: 最初の取得時刻=%s",
        symbol,
        timestamps[0],
    )

    logging.info(
        "%s: 最後の取得時刻=%s",
        symbol,
        timestamps[-1],
    )

    return duplicate_count, gap_count


def diagnose_audusd_windows(data, flat_mask):
    """AUD/USDの指定区間について、取得直後の価格を詳しく記録する。"""

    logging.info(
        "AUD/USD: 診断対象データ件数=%d本",
        len(data),
    )

    # yfinanceの時刻をUTCにそろえる
    utc_timestamps = []

    for timestamp in data.index:
        if timestamp.tzinfo is not None:
            utc_timestamp = timestamp.tz_convert("UTC")
        else:
            utc_timestamp = timestamp

        utc_timestamps.append(utc_timestamp)

    for window_start, window_end in AUDUSD_DIAGNOSTIC_WINDOWS:

        logging.info(
            "AUD/USD: 診断対象区間 %s ～ %s UTC",
            window_start,
            window_end,
        )

        target_positions = []

        for position, timestamp in enumerate(utc_timestamps):
            timestamp_text = timestamp.strftime("%Y-%m-%d %H:%M")

            if window_start <= timestamp_text <= window_end:
                target_positions.append(position)

        if not target_positions:
            logging.warning(
                "AUD/USD: 指定区間に取得データがありません"
            )
            continue

        # 区間の前後1本も診断対象に含める
        first_position = max(0, target_positions[0] - 1)
        last_position = min(
            len(data) - 1,
            target_positions[-1] + 1,
        )

        logging.info(
            "AUD/USD: 診断対象データ=%d本（前後1本を含む）",
            last_position - first_position + 1,
        )

        for position in range(first_position, last_position + 1):

            timestamp = utc_timestamps[position]
            bar = data.iloc[position]

            if position > 0:
                previous_timestamp = utc_timestamps[position - 1]
                previous_close = data.iloc[position - 1]["Close"]

                gap_minutes = (
                    timestamp - previous_timestamp
                ).total_seconds() / 60
            else:
                previous_timestamp = None
                previous_close = None
                gap_minutes = None

            is_flat = bool(flat_mask.iloc[position])

            logging.info(
                (
                    "AUD/USD DIAG: timestamp=%s "
                    "previous_timestamp=%s "
                    "previous_close=%s "
                    "Open=%s High=%s Low=%s Close=%s "
                    "flat=%s gap_minutes=%s"
                ),
                timestamp,
                previous_timestamp,
                previous_close,
                bar["Open"],
                bar["High"],
                bar["Low"],
                bar["Close"],
                is_flat,
                gap_minutes,
            )


def collect_audusd_diagnostic():
    """
    AUD/USDの診断専用データを10日間取得する。
    この関数ではDBへの保存を行わない。
    """

    logging.info(
        "AUD/USD: 診断専用データ取得開始（period=10d）"
    )

    data = yf.download(
        "AUDUSD=X",
        period="10d",
        interval="5m",
        auto_adjust=False,
        progress=False,
        threads=False,
    )

    if data.empty:
        raise RuntimeError(
            "AUD/USD: 診断専用データを取得できません"
        )

    # yfinanceの列がMultiIndexの場合にも対応
    if getattr(data.columns, "nlevels", 1) > 1:
        data.columns = data.columns.get_level_values(0)

    required = {"Open", "High", "Low", "Close"}

    if not required.issubset(data.columns):
        raise ValueError(
            "AUD/USD: 診断データに必要な価格列がありません"
        )

    logging.info(
        "AUD/USD: 診断専用データ取得件数=%d本",
        len(data),
    )

    logging.info(
        "AUD/USD: 診断専用データ最初の時刻=%s",
        data.index.min(),
    )

    logging.info(
        "AUD/USD: 診断専用データ最後の時刻=%s",
        data.index.max(),
    )

    flat_mask = (
        (data["Open"] == data["High"])
        & (data["High"] == data["Low"])
        & (data["Low"] == data["Close"])
    )

    flat_count = int(flat_mask.sum())

    logging.info(
        "AUD/USD: 診断専用データOHLC全値一致=%d本 / 全体=%d本",
        flat_count,
        len(data),
    )

    # 指定した2区間の詳細を記録
    diagnose_audusd_windows(data, flat_mask)

    logging.info(
        "AUD/USD: 診断専用データの確認終了（DB保存なし）"
    )


def collect_symbol(symbol: str, ticker: str) -> int:
    """5分足を取得し、品質を検査してNeonへ保存する。"""

    logging.info("%s: 価格データ取得開始", symbol)

    data = yf.download(
        ticker,
        period="5d",
        interval="5m",
        auto_adjust=False,
        progress=False,
        threads=False,
    )

    if data.empty:
        raise RuntimeError(
            f"{symbol}: Yahoo Financeから価格データを取得できません"
        )

    # yfinanceの列がMultiIndexの場合にも対応する
    if getattr(data.columns, "nlevels", 1) > 1:
        data.columns = data.columns.get_level_values(0)

    required = {"Open", "High", "Low", "Close"}

    if not required.issubset(data.columns):
        raise ValueError(
            f"{symbol}: 必要な価格列がありません: {list(data.columns)}"
        )

    # 診断：Yahoo Finance取得直後のOHLCを確認
    flat_mask = (
        (data["Open"] == data["High"])
        & (data["High"] == data["Low"])
        & (data["Low"] == data["Close"])
    )

    flat_count = int(flat_mask.sum())

    logging.info(
        "%s: Yahoo取得直後のOHLC全値一致=%d本 / 全体=%d本",
        symbol,
        flat_count,
        len(data),
    )

    if flat_count > 0:
        logging.warning(
            "%s: Yahoo取得直後のOHLC全値一致データ（先頭5件）:\n%s",
            symbol,
            data.loc[
                flat_mask,
                ["Open", "High", "Low", "Close"],
            ].head(5).to_string(),
        )

    # 取得したデータの時間間隔を検査
    duplicate_count, gap_count = inspect_data(symbol, data)

    # 保存するデータを作成
    rows = []
    missing_count = 0
    invalid_count = 0

    for timestamp, bar in data.iterrows():

        prices = bar[["Open", "High", "Low", "Close"]]

        if prices.isna().any():
            missing_count += 1
            continue

        open_price = float(bar["Open"])
        high_price = float(bar["High"])
        low_price = float(bar["Low"])
        close_price = float(bar["Close"])

        # OHLC価格の整合性を確認
        if (
            high_price < low_price
            or high_price < open_price
            or high_price < close_price
            or low_price > open_price
            or low_price > close_price
        ):
            invalid_count += 1
            logging.warning(
                "%s: OHLC不整合 timestamp=%s",
                symbol,
                timestamp,
            )
            continue

        rows.append(
            (
                symbol,
                timestamp.to_pydatetime(),
                open_price,
                high_price,
                low_price,
                close_price,
                "yfinance",
            )
        )

    logging.info(
        "%s: 保存可能=%d本、価格欠損=%d本、OHLC不整合=%d本",
        symbol,
        len(rows),
        missing_count,
        invalid_count,
    )

    if duplicate_count > 0:
        raise RuntimeError(
            f"{symbol}: Yahoo Financeの取得データに重複時刻があります"
        )

    if invalid_count > 0:
        raise RuntimeError(
            f"{symbol}: OHLC価格に不整合があります"
        )

    if not rows:
        raise RuntimeError(
            f"{symbol}: 保存可能な価格データがありません"
        )

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
        "%s: 取得=%d本、保存可能=%d本、新規登録=%d本",
        symbol,
        len(data),
        len(rows),
        inserted,
    )

    logging.info(
        "%s: 価格データ検査完了（時間間隔の空白=%d件）",
        symbol,
        gap_count,
    )

    return inserted


def main():
    total = 0
    failed_symbols = []

    for symbol, ticker in SYMBOLS.items():
        try:
            total += collect_symbol(symbol, ticker)

        except Exception:
            logging.exception(
                "%s: 価格データ取得・検査・保存に失敗",
                symbol,
            )
            failed_symbols.append(symbol)

    # 通常の価格収集とは独立して診断を実施する
    try:
        collect_audusd_diagnostic()

    except Exception:
        logging.exception(
            "AUD/USD: 診断専用データの取得・確認に失敗"
        )

    logging.info(
        "ORION価格収集終了：新規登録合計=%d本",
        total,
    )

    if failed_symbols:
        raise RuntimeError(
            "価格データ収集に失敗した通貨ペア: "
            + ", ".join(failed_symbols)
        )

    logging.info("ORION価格収集：全通貨ペア正常終了")


if __name__ == "__main__":
    main()
