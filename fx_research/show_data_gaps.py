
import logging

from fx_research.db import get_connection


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)


def show_data_gaps():
    """Neonに保存された市場データ欠損履歴を表示する。"""

    sql = """
        SELECT
            symbol,
            previous_timestamp,
            next_timestamp,
            duration_minutes,
            missing_bars,
            classification,
            first_detected_at,
            last_detected_at,
            detection_count
        FROM data_gaps
        ORDER BY previous_timestamp DESC, symbol
    """

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()

    print("\n========== PROJECT ORION ==========")
    print("         DATA GAP HISTORY")
    print("===================================\n")

    if not rows:
        print("欠損履歴はまだ登録されていません。")
        return

    for row in rows:
        (
            symbol,
            previous,
            next_time,
            duration,
            missing_bars,
            classification,
            first_detected,
            last_detected,
            detection_count,
        ) = row

        print(f"通貨ペア       : {symbol}")
        print(f"欠損開始前     : {previous}")
        print(f"欠損終了後     : {next_time}")
        print(f"欠損時間       : {duration:.1f} 分")
        print(f"欠損5分足本数  : {missing_bars}")
        print(f"分類           : {classification}")
        print(f"初回検出       : {first_detected}")
        print(f"最終検出       : {last_detected}")
        print(f"検出回数       : {detection_count}")
        print("-----------------------------------")

    print(f"\n登録された欠損履歴: {len(rows)}件")


def main():
    try:
        show_data_gaps()

    except Exception:
        logging.exception("欠損履歴の取得に失敗しました")
        raise


if __name__ == "__main__":
    main()
