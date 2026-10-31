
import os
import psycopg


def init_research_tables():
    """研究用のアラート・検証・データ欠損テーブルを作成する。"""

    database_url = os.environ.get("DATABASE_URL")

    if not database_url:
        raise RuntimeError(
            "環境変数 DATABASE_URL が設定されていません"
        )

    create_alerts_sql = """
    CREATE TABLE IF NOT EXISTS market_alerts (
        id BIGSERIAL PRIMARY KEY,
        symbol TEXT NOT NULL,
        alert_timestamp TIMESTAMPTZ NOT NULL,
        change_pct DOUBLE PRECISION NOT NULL,
        baseline_pct DOUBLE PRECISION NOT NULL,
        ratio DOUBLE PRECISION NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (symbol, alert_timestamp)
    );
    """

    create_evaluations_sql = """
    CREATE TABLE IF NOT EXISTS alert_evaluations (
        id BIGSERIAL PRIMARY KEY,
        alert_id BIGINT NOT NULL
            REFERENCES market_alerts(id) ON DELETE CASCADE,
        horizon_minutes INTEGER NOT NULL,
        future_timestamp TIMESTAMPTZ,
        future_close DOUBLE PRECISION,
        price_change_pct DOUBLE PRECISION,
        evaluated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (alert_id, horizon_minutes)
    );
    """

    create_data_gaps_sql = """
    CREATE TABLE IF NOT EXISTS data_gaps (
        id BIGSERIAL PRIMARY KEY,
        symbol TEXT NOT NULL,
        previous_timestamp TIMESTAMPTZ NOT NULL,
        next_timestamp TIMESTAMPTZ NOT NULL,
        duration_minutes DOUBLE PRECISION NOT NULL,
        missing_bars INTEGER NOT NULL,
        classification TEXT NOT NULL,
        first_detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        last_detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        detection_count INTEGER NOT NULL DEFAULT 1,
        UNIQUE (symbol, previous_timestamp, next_timestamp)
    );
    """

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(create_alerts_sql)
            cur.execute(create_evaluations_sql)
            cur.execute(create_data_gaps_sql)

    print("Project ORION: research tables are ready.")
    print("- market_alerts")
    print("- alert_evaluations")
    print("- data_gaps")


if __name__ == "__main__":
    init_research_tables()
