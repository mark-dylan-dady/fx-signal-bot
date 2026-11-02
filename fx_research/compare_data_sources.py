
from fx_research.db import get_connection


def compare_data_sources():
    """
    Compare Yahoo Finance and Dukascopy price data.
    Results are saved in source_price_comparisons.
    """

    sql = """
    WITH compared AS (
        SELECT
            COALESCE(y.symbol, d.symbol) AS symbol,
            COALESCE(y.timestamp, d.timestamp) AS timestamp,

            y.open AS yahoo_open,
            y.high AS yahoo_high,
            y.low AS yahoo_low,
            y.close AS yahoo_close,

            d.open AS dukascopy_open,
            d.high AS dukascopy_high,
            d.low AS dukascopy_low,
            d.close AS dukascopy_close,

            CASE
                WHEN y.symbol IS NOT NULL
                 AND d.symbol IS NOT NULL
                    THEN 'BOTH'
                WHEN y.symbol IS NOT NULL
                    THEN 'YAHOO_ONLY'
                ELSE 'DUKASCOPY_ONLY'
            END AS comparison_status

        FROM price_bars y
        FULL OUTER JOIN dukascopy_price_bars d
            ON y.symbol = d.symbol
           AND y.timestamp = d.timestamp
    )

    INSERT INTO source_price_comparisons (
        symbol,
        timestamp,
        yahoo_open,
        yahoo_high,
        yahoo_low,
        yahoo_close,
        dukascopy_open,
        dukascopy_high,
        dukascopy_low,
        dukascopy_close,
        close_diff,
        close_diff_pct,
        comparison_status,
        compared_at
    )

    SELECT
        symbol,
        timestamp,
        yahoo_open,
        yahoo_high,
        yahoo_low,
        yahoo_close,
        dukascopy_open,
        dukascopy_high,
        dukascopy_low,
        dukascopy_close,

        CASE
            WHEN yahoo_close IS NOT NULL
             AND dukascopy_close IS NOT NULL
            THEN dukascopy_close - yahoo_close
            ELSE NULL
        END,

        CASE
            WHEN yahoo_close IS NOT NULL
             AND dukascopy_close IS NOT NULL
             AND yahoo_close <> 0
            THEN
                (dukascopy_close - yahoo_close)
                / yahoo_close * 100
            ELSE NULL
        END,

        comparison_status,
        NOW()

    FROM compared

    ON CONFLICT (symbol, timestamp)
    DO UPDATE SET
        yahoo_open = EXCLUDED.yahoo_open,
        yahoo_high = EXCLUDED.yahoo_high,
        yahoo_low = EXCLUDED.yahoo_low,
        yahoo_close = EXCLUDED.yahoo_close,
        dukascopy_open = EXCLUDED.dukascopy_open,
        dukascopy_high = EXCLUDED.dukascopy_high,
        dukascopy_low = EXCLUDED.dukascopy_low,
        dukascopy_close = EXCLUDED.dukascopy_close,
        close_diff = EXCLUDED.close_diff,
        close_diff_pct = EXCLUDED.close_diff_pct,
        comparison_status = EXCLUDED.comparison_status,
        compared_at = NOW()

    RETURNING comparison_status;
    """

    conn = get_connection()

    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            results = cur.fetchall()
            conn.commit()

        counts = {
            "BOTH": 0,
            "YAHOO_ONLY": 0,
            "DUKASCOPY_ONLY": 0,
        }

        for row in results:
            status = row[0]
            if status in counts:
                counts[status] += 1

        print("=" * 55)
        print("PROJECT ORION: DATA SOURCE COMPARISON")
        print("=" * 55)
        print(f"Compared records : {len(results)}")
        print(f"Both sources     : {counts['BOTH']}")
        print(f"Yahoo only       : {counts['YAHOO_ONLY']}")
        print(f"Dukascopy only   : {counts['DUKASCOPY_ONLY']}")
        print("-" * 55)
        print("Comparison results saved successfully.")
        print("=" * 55)

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


if __name__ == "__main__":
    compare_data_sources()
