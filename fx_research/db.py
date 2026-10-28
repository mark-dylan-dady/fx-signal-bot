
import os
import psycopg


def get_connection():
    """Neon PostgreSQLへの接続を取得する。"""
    database_url = os.environ.get("DATABASE_URL")

    if not database_url:
        raise RuntimeError("環境変数 DATABASE_URL が設定されていません")

    return psycopg.connect(database_url)


def init_db():
    """研究用の価格データテーブルを作成する。"""
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS price_bars (
        symbol TEXT NOT NULL,
        timestamp TIMESTAMPTZ NOT NULL,
        open DOUBLE PRECISION NOT NULL,
        high DOUBLE PRECISION NOT NULL,
        low DOUBLE PRECISION NOT NULL,
        close DOUBLE PRECISION NOT NULL,
        source TEXT NOT NULL DEFAULT 'yfinance',
        fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY (symbol, timestamp)
    );
    """

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(create_table_sql)


if __name__ == "__main__":
    init_db()
    print("Project ORION: price_bars テーブルの初期化が完了しました")
