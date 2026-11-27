"""旧FXシグナルの約定価格・コスト感度を検証する独立スクリプト。

本番の fx_signal.py / workflow / LINE 通知は変更しない。
実行: python fx_signal_audit.py
必要: pandas, yfinance
出力: audit_trade_comparison.csv, audit_summary.csv
"""

from pathlib import Path

import pandas as pd
import yfinance as yf

from fx_signal import (
    COST_YEN,
    MAX_BARS,
    PAIRS,
    build_signals,
    calc_tp_sl,
    judge_trade,
)

# 現行コストに加え、コストが増えた場合の感度を見る
COST_SCENARIOS = {
    "cost_0.5pip": 0.005,
    "cost_1.0pip": 0.010,
    "cost_1.5pip": 0.015,
}
OUTPUT_DETAIL = Path("audit_trade_comparison.csv")
OUTPUT_SUMMARY = Path("audit_summary.csv")


def judge_with_cost(sig_type, entry, tp, sl, future_df, cost_yen):
    """現行と同じ足内判定。TP/SL同時到達は保守的にLOSE。"""
    for _, bar in future_df.iterrows():
        high = float(bar["High"])
        low = float(bar["Low"])
        if sig_type == "BUY":
            hit_tp, hit_sl = high >= tp, low <= sl
        else:
            hit_tp, hit_sl = low <= tp, high >= sl

        if hit_sl:
            return "LOSE", -abs(entry - sl) - cost_yen
        if hit_tp:
            return "WIN", abs(tp - entry) - cost_yen

    if len(future_df) >= MAX_BARS:
        last_close = float(future_df["Close"].iloc[-1])
        raw_pnl = (
            last_close - entry if sig_type == "BUY" else entry - last_close
        )
        return "TIMEOUT", raw_pnl - cost_yen

    return "PENDING", float("nan")


def summarize_rows(rows, scenario_name):
    """完了取引だけを集計。TIMEOUTも勝率の分母に含める。"""
    df = pd.DataFrame(rows)
    if df.empty:
        return {
            "Scenario": scenario_name,
            "Count": 0,
            "Wins": 0,
            "Losses": 0,
            "Timeouts": 0,
            "WinRate_pct": float("nan"),
            "TotalPnL_pips": 0.0,
            "AveragePnL_pips": float("nan"),
        }

    done = df[df["Result"].isin(["WIN", "LOSE", "TIMEOUT"])]
    count = len(done)
    wins = int((done["Result"] == "WIN").sum())
    losses = int((done["Result"] == "LOSE").sum())
    timeouts = int((done["Result"] == "TIMEOUT").sum())
    pnl_pips = pd.to_numeric(done["PnL_yen"], errors="coerce") * 100

    return {
        "Scenario": scenario_name,
        "Count": count,
        "Wins": wins,
        "Losses": losses,
        "Timeouts": timeouts,
        "WinRate_pct": round(wins / count * 100, 2) if count else float("nan"),
        "TotalPnL_pips": round(pnl_pips.sum(), 2),
        "AveragePnL_pips": round(pnl_pips.mean(), 2) if count else float("nan"),
    }


def analyze_pair(pair):
    label = pair.replace("=X", "")
    history_path = Path(f"signals_history_{label}.csv")
    if not history_path.exists():
        print(f"[SKIP] {history_path} がありません")
        return [], []

    history = pd.read_csv(history_path)
    if history.empty:
        return [], []

    # build_signals と同じデータ取得・指標計算を利用。元ファイルは変更しない。
    market, market_jst = build_signals(pair)
    market = market.copy()
    market.index = market_jst.tz_localize(None)

    details = []
    summaries = []

    for _, signal in history.iterrows():
        sig_time = pd.to_datetime(signal["Timestamp"])
        sig_type = str(signal["Type"])
        matches = market.index[market.index == sig_time]
        if len(matches) == 0:
            details.append({
                "Pair": label,
                "Timestamp": sig_time,
                "Type": sig_type,
                "Scenario": "DATA_NOT_FOUND",
                "Entry_yen": float("nan"),
                "Result": "DATA_NOT_FOUND",
                "PnL_yen": float("nan"),
                "Note": "Yahoo取得データ内にシグナル足が見つからない",
            })
            continue

        pos = market.index.get_loc(matches[0])
        if not isinstance(pos, int) or pos + 1 >= len(market):
            continue

        signal_bar = market.iloc[pos]
        next_bar = market.iloc[pos + 1]
        atr = float(signal["ATR"])
        if pd.isna(atr):
            continue

        # A: CSVに保存されたシグナル足終値を使う従来条件
        old_entry = float(signal["Entry"])
        old_tp, old_sl, _, _ = calc_tp_sl(old_entry, atr, sig_type)
        old_future = market.iloc[pos + 1 : pos + 1 + MAX_BARS]
        old_result, old_pnl = judge_trade(
            sig_type, old_entry, old_tp, old_sl, old_future
        )
        details.append({
            "Pair": label,
            "Timestamp": sig_time,
            "Type": sig_type,
            "Scenario": "signal_close_original_cost",
            "Entry_yen": old_entry,
            "Result": old_result or "PENDING",
            "PnL_yen": old_pnl,
            "Note": "シグナル足終値。現行ロジックで再判定",
        })

        # B: 次の5分足始値で約定したと仮定。TP/SLも約定価格から再設定。
        next_entry = float(next_bar["Open"])
        next_tp, next_sl, _, _ = calc_tp_sl(next_entry, atr, sig_type)
        next_future = market.iloc[pos + 1 : pos + 1 + MAX_BARS]

        for scenario, cost in COST_SCENARIOS.items():
            result, pnl = judge_with_cost(
                sig_type, next_entry, next_tp, next_sl, next_future, cost
            )
            details.append({
                "Pair": label,
                "Timestamp": sig_time,
                "Type": sig_type,
                "Scenario": f"next_5m_open_{scenario}",
                "Entry_yen": next_entry,
                "Result": result,
                "PnL_yen": pnl,
                "Note": "次の5分足始値で約定した仮定。実際のBid/Askではない",
            })

    detail_df = pd.DataFrame(details)
    for scenario in detail_df["Scenario"].dropna().unique() if not detail_df.empty else []:
        if scenario == "DATA_NOT_FOUND":
            continue
        scenario_rows = detail_df[
            (detail_df["Pair"] == label) & (detail_df["Scenario"] == scenario)
        ].to_dict("records")
        summary = summarize_rows(scenario_rows, f"{label}_{scenario}")
        summary["Pair"] = label
        summaries.append(summary)

    return details, summaries


def main():
    all_details = []
    all_summaries = []

    for pair in PAIRS:
        try:
            details, summaries = analyze_pair(pair)
            all_details.extend(details)
            all_summaries.extend(summaries)
        except Exception as exc:
            print(f"[ERROR] {pair}: {type(exc).__name__}: {exc}")

    if all_details:
        pd.DataFrame(all_details).to_csv(OUTPUT_DETAIL, index=False)
        print(f"明細を保存: {OUTPUT_DETAIL}")

    if all_summaries:
        summary_df = pd.DataFrame(all_summaries)
        summary_df = summary_df[
            [
                "Pair", "Scenario", "Count", "Wins", "Losses", "Timeouts",
                "WinRate_pct", "TotalPnL_pips", "AveragePnL_pips",
            ]
        ]
        summary_df.to_csv(OUTPUT_SUMMARY, index=False)
        print("\n=== 検証サマリー ===")
        print(summary_df.to_string(index=False))
        print(f"\n集計を保存: {OUTPUT_SUMMARY}")

    print(
        "\n注意: 次の5分足始値は約定価格の近似です。"
        "実際のBid/Askスプレッド、スリッページ、通知遅延は含みません。"
    )


if __name__ == "__main__":
    main()
