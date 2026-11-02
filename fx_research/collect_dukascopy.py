
import argparse
import csv
import math
from datetime import datetime, timezone
from pathlib import Path

from fx_research.db import get_connection


SYMBOL_FILES = {
    "AUD/JPY": "audjpy",
    "EUR/JPY": "eurjpy",
}


def read_csv_file(file_path, symbol):
    """Dukascopy CSVを読み込み、価格データを検証する。"""

    valid_rows = []
    invalid_count = 0

    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(
            f"CSVファイルが見つかりません: {path}"
        )

    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)

        required_columns = {
            "timestamp", "open", "high", "low", "close"
        }

        if not required_columns.issubset(set(reader.fieldnames or [])):
            raise ValueError(
                f"{path}: CSVの列名が正しくありません"
            )

        for row in reader:
            try:
                timestamp_ms = int(row["timestamp"])

                timestamp = datetime.fromtimestamp(
                    timestamp_ms / 1000,
                    tz=timezone.utc
                )

                open_price = float(row["open"])
                high_price = float(row["high"])
                low_price = float(row["low"])
                close_price = float(row["close"])

                prices = [
                    open_price,
                    high_price,
                    low_price,
                    close_price,
                ]

                if not all(math.isfinite(price) for price in prices):
                    raise ValueError("価格に無効な数値があります")

                if any(price <= 0 for price in prices):
                    raise ValueError("価格が0以下です")

                if high_price < max(open_price, close_price, low_price):
                    raise ValueError("Highが不正です")

                if low_price > min(open_price, close_price, high_price):
                    raise ValueError("Lowが不正です")

                if timestamp.minute % 5 != 0 or timestamp.second != 0:
                    raise ValueError("5分足の時刻ではありません")

                valid_rows.append((
                    symbol,
                    timestamp,
                    open_price,
                    high_price,
                    low_price,
                    close_price,
                    "dukascopy",
                    "BID",
                ))

            except (ValueError, TypeError, OverflowError):
                invalid_count += 1

    return valid_rows, invalid_count


def save_rows(rows):
    """Dukascopy価格データをNeonに保存する。"""

    insert_sql = """
    INSERT INTO dukascopy_price_bars (
        symbol,
        timestamp,
        open,
        high,
        low,
        close,
        source,
        price_type
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (symbol, timestamp) DO NOTHING;
    """

    inserted_count = 0

    with get_connection() as conn:
        with conn.cursor() as cur:
            for row in rows:
                cur.execute(insert_sql, row)
                inserted_count += cur.rowcount

    return inserted_count


def main():
    parser = argparse.ArgumentParser(
        description="Dukascopyの5分足データをNeonに保存する"
    )

    parser.add_argument("--audjpy", required=True)
    parser.add_argument("--eurjpy", required=True)

    args = parser.parse_args()

    print("=" * 60)
    print("PROJECT ORION: DUKASCOPY DATA COLLECTION")
    print("=" * 60)

    all_rows = []
    total_invalid = 0

    for symbol, file_path in [
        ("AUD/JPY", args.audjpy),
        ("EUR/JPY", args.eurjpy),
    ]:
        rows, invalid_count = read_csv_file(file_path, symbol)

        all_rows.extend(rows)
        total_invalid += invalid_count

        print(f"{symbol}")
        print(f"  CSV rows valid : {len(rows)}")
        print(f"  Invalid rows   : {invalid_count}")

    inserted_count = save_rows(all_rows)
    duplicate_count = len(all_rows) - inserted_count

    print("-" * 60)
    print(f"Total valid rows : {len(all_rows)}")
    print(f"New rows saved   : {inserted_count}")
    print(f"Duplicates       : {duplicate_count}")
    print(f"Invalid rows     : {total_invalid}")
    print("=" * 60)


if __name__ == "__main__":
    main()
