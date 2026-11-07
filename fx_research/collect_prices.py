
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

# 5通貨ペア共通の診断対象（UTC）
DIAGNOSTIC_WINDOWS = [
    (
        "2026-10-30 21:00",
        "2026-10-30 21:30",
    ),
    (
        "2026-10-30 23:10",
        "2026-10-30 23:40",
    ),
]


def normalize_columns(data):
    """yfinanceのMultiIndex列を通常の列名にそろえる。"""

    if getattr(data.columns, "nlevels", 1) > 1:
        data.columns = data.columns.get_level_values(0)

    required = {"Open", "High", "Low", "Close"}

    if not required.issubset(data.columns):
        raise ValueError(
            "必要な価格列がありません: "
            + str(list(data.columns))
        )

    return data


def to_utc(timestamp):
    """タイムスタンプをUTCにそろえる。"""

    if timestamp.tzinfo is not None:
        return timestamp.tz_convert("UTC")

    # yfinanceの通常データはタイムゾーン付きだが、
    # 万一naiveの場合はUTCとして扱う。
    return timestamp.tz_localize("UTC")


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


def diagnose_symbol_windows(symbol, data):
    """
    指定区間について、Yahoo取得直後の価格を詳しく記録する。
    DBへの保存は行わない。
    """

    logging.info(
        "%s: 5通貨ペア比較診断開始",
        symbol,
    )

    data = data.sort_index()

    utc_timestamps = [
        to_utc(timestamp)
        for timestamp in data.index
    ]

    flat_mask = (
        (data["Open"] == data["High"])
        & (data["High"] == data["Low"])
        & (data["Low"] == data["Close"])
    )

    flat_count = int(flat_mask.sum())

    logging.info(
        "%s: 診断データOHLC全値一致=%d本 / 全体=%d本",
        symbol,
        flat_count,
        len(data),
    )

    for window_start, window_end in DIAGNOSTIC_WINDOWS:

        logging.info(
            "%s: 診断対象区間 %s ～ %s UTC",
            symbol,
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
                "%s: 指定区間に取得データがありません",
                symbol,
            )
            continue

        # 区間の前後1本も診断対象に含める
        first_position = max(0, target_positions[0] - 1)
        last_position = min(
            len(data) - 1,
            target_positions[-1] + 1,
        )

        logging.info(
            "%s: 診断対象データ=%d本（前後1本を含む）",
            symbol,
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

            if is_flat and previous_close is not None:
                if bar["Close"] == previous_close:
                    flat_type = "UNCHANGED_CLOSE"
                else:
                    flat_type = "FLAT_BUT_MOVED"
            elif is_flat:
                flat_type = "FLAT_NO_PREVIOUS"
            else:
                flat_type = "NOT_FLAT"

            logging.info(
                (
                    "%s DIAG: timestamp=%s "
                    "previous_timestamp=%s "
                    "previous_close=%s "
                    "Open=%s High=%s Low=%s Close=%s "
                    "flat=%s flat_type=%s gap_minutes=%s"
                ),
                symbol,
                timestamp,
                previous_timestamp,
                previous_close,
                bar["Open"],
                bar["High"],
                bar["Low"],
                bar["Close"],
                is_flat,
                flat_type,
                gap_minutes,
            )


def collect_comparison_diagnostic():
    """
    5通貨ペアを診断専用に10日間取得する。
    この関数ではDBへの保存を一切行わない。
    """

    logging.info(
        "=================================================="
    )
    logging.info(
        "5通貨ペア比較診断開始（period=10d / DB保存なし）"
    )
    logging.info(
        "=================================================="
    )

    failed_symbols = []

    for symbol, ticker in SYMBOLS.items():

        try:
            logging.info(
                "%s: 診断専用データ取得開始 ticker=%s",
                symbol,
                ticker,
            )

            data = yf.download(
                ticker,
                period="10d",
                interval="5m",
                auto_adjust=False,
                progress=False,
                threads=False,
            )

            if data.empty:
                raise RuntimeError(
                    f"{symbol}: 診断データを取得できません"
                )

            data = normalize_columns(data)
            data = data.sort_index()

            logging.info(
                "%s: 診断専用データ取得件数=%d本",
                symbol,
                len(data),
            )

            logging.info(
                "%s: 診断専用データ最初の時刻=%s",
                symbol,
                data.index.min(),
            )

            logging.info(
                "%s: 診断専用データ最後の時刻=%s",
                symbol,
                data.index.max(),
            )

            diagnose_symbol_windows(symbol, data)

            logging.info(
                "%s: 比較診断完了",
                symbol,
            )

        except Exception:
            logging.exception(
                "%s: 比較診断に失敗",
                symbol,
            )
            failed_symbols.append(symbol)

    logging.info(
        "=================================================="
    )

    if failed_symbols:
        logging.warning(
            "比較診断に失敗した通貨ペア: %s",
            ", ".join(failed_symbols),
        )
    else:
        logging.info(
            "5通貨ペアすべての比較診断が完了"
        )

    logging.info(
        "5通貨ペア比較診断終了（DB保存なし）"
    )
    logging.info(
        "=================================================="
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

    data = normalize_columns(data)

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

    # 通常の価格収集とは独立して5通貨ペア比較診断を実施
    collect_comparison_diagnostic()

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
