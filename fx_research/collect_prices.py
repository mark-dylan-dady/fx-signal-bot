
        gap_count,
    )

    return len(data), rows, gap_count


def save_symbol_rows(conn, symbol: str, data_count: int, rows: list) -> int:
    """既存データを保護しながら、1通貨ペア分の価格データを保存する。"""

    sql = """
        INSERT INTO price_bars
            (symbol, timestamp, open, high, low, close, source)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (symbol, timestamp) DO NOTHING
    """

    # 通貨ペアごとに独立したトランザクションで保存する。
    # 1ペアの保存失敗が、ほかのペアの保存に影響しないようにする。
    with conn.transaction():
        with conn.cursor() as cur:
            cur.executemany(sql, rows)
            inserted = cur.rowcount

    logging.info(
        "%s: 取得=%d本、保存可能=%d本、新規登録=%d本",
        symbol,
        data_count,
        len(rows),
        inserted,
    )

    return inserted


def collect_prices():
    total = 0
    failed_symbols = []
    prepared_symbols = {}

    # 先にYahooから取得・検査する。
    # この段階ではNeonへの接続を行わない。
    for symbol, ticker in SYMBOLS.items():
        try:
            data_count, rows, gap_count = collect_symbol(symbol, ticker)
            prepared_symbols[symbol] = (data_count, rows, gap_count)

        except Exception:
            logging.exception(
                "%s: 価格データ取得・検査に失敗",
                symbol,
            )
            failed_symbols.append(symbol)

    # 5通貨ペア分の準備が終わってから、Neonへ1回だけ接続する。
    if prepared_symbols:
        try:
            with get_connection() as conn:
                for symbol, (data_count, rows, gap_count) in prepared_symbols.items():
                    try:
                        inserted = save_symbol_rows(
                            conn,
                            symbol,
                            data_count,
                            rows,
                        )
                        total += inserted

                    except Exception:
                        logging.exception(
                            "%s: Neonへの価格データ保存に失敗",
                            symbol,
                        )
                        failed_symbols.append(symbol)

        except Exception:
            logging.exception("Neonデータベースへの接続に失敗")
            failed_symbols.extend(
                symbol
                for symbol in prepared_symbols
                if symbol not in failed_symbols
            )

    logging.info(
        "ORION価格収集終了：新規登録合計=%d本",
        total,
    )

    if failed_symbols:
        raise RuntimeError(
            "価格データ収集・保存に失敗した通貨ペア: "
            + ", ".join(failed_symbols)
        )

    logging.info("ORION価格収集：全通貨ペア正常終了")


def main():
    parser = argparse.ArgumentParser(
        description="ORIONのFX価格収集・比較診断"
    )
    parser.add_argument(
        "--diagnostic",
        action="store_true",
        help="5通貨ペアの比較診断のみ実行する（DB保存なし）",
    )
    args = parser.parse_args()

    if args.diagnostic:
        collect_comparison_diagnostic()
    else:
        collect_prices()


if __name__ == "__main__":
    main()

