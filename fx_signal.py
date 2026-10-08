import os

import pandas as pd
import requests
import yfinance as yf
from dotenv import load_dotenv

load_dotenv()

CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
USER_ID = os.getenv("LINE_USER_ID")
IS_MANUAL_RUN = os.getenv("IS_MANUAL_RUN", "false").lower() == "true"

# ==========================================
# 設定（現時点のベスト設定）
# ==========================================
TP_ATR_MULT = 1.3
SL_ATR_MULT = 1.3
MIN_TP_WIDTH = 0.05
MIN_SL_WIDTH = 0.08
MAX_BARS = 48
COST_YEN = 0.005
MIN_SLOPE = 0.03
RSI_BUY_LOW, RSI_BUY_HIGH = 55, 65
RSI_SELL_LOW, RSI_SELL_HIGH = 37, 43

# 監視する通貨ペア（USDJPYは成績が悪いため除外）
PAIRS = ["AUDJPY=X", "EURJPY=X"]

# ==========================================
# 見逃し回収の設定
# GitHubの定期実行は間隔が空くことがあるため、実行のたびに
# 「直近の足をさかのぼって」シグナルを探し、記録していないものを回収します。
# ==========================================
LOOKBACK_HOURS = 24         # 通常は直近24時間をさかのぼって調べる
FIRST_LOOKBACK_HOURS = 72   # 記録ファイルがまだ無い最初の1回だけ、3日分さかのぼる
LIVE_MINUTES = 20           # この分数以内に出たシグナルは「リアルタイム」扱い
MAX_LATE_LINES = 8          # 見逃し回収の通知に載せる最大件数

HISTORY_COLUMNS = ["Timestamp", "Type", "Entry", "TP", "SL", "RSI", "ATR", "Result", "PnL"]
NUM_COLUMNS = ["Entry", "TP", "SL", "RSI", "ATR", "PnL"]


def send_line_notification(message):
    if not CHANNEL_ACCESS_TOKEN or not USER_ID:
        print("エラー: LINEアクセストークンまたはユーザーIDが未設定です。")
        return False
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Authorization": f"Bearer {CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {"to": USER_ID, "messages": [{"type": "text", "text": message}]}
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        if response.status_code == 200:
            print("【成功】LINE通知を送信しました。")
            return True
        print(f"LINE APIエラー: {response.status_code} - {response.text}")
        return False
    except Exception as e:
        print(f"LINE通知処理エラー: {e}")
        return False


def calc_tp_sl(entry, atr, sig_type):
    tp_width = max(atr * TP_ATR_MULT, MIN_TP_WIDTH)
    sl_width = max(atr * SL_ATR_MULT, MIN_SL_WIDTH)
    if sig_type == "BUY":
        return entry + tp_width, entry - sl_width, tp_width, sl_width
    return entry - tp_width, entry + sl_width, tp_width, sl_width


def judge_trade(sig_type, entry, tp, sl, future_df):
    for _, f_row in future_df.iterrows():
        high = float(f_row["High"])
        low = float(f_row["Low"])
        if sig_type == "BUY":
            hit_tp, hit_sl = high >= tp, low <= sl
        else:
            hit_tp, hit_sl = low <= tp, high >= sl
        if hit_sl:  # 同じ足でTPとSLの両方に触れた場合は負け扱い
            return "LOSE", -abs(entry - sl) - COST_YEN
        if hit_tp:
            return "WIN", abs(tp - entry) - COST_YEN
    if len(future_df) >= MAX_BARS:
        last_close = float(future_df["Close"].iloc[-1])
        pnl = (last_close - entry) if sig_type == "BUY" else (entry - last_close)
        return "TIMEOUT", pnl - COST_YEN
    return None, None


def summarize(result_df):
    done = result_df[result_df["Result"].isin(["WIN", "LOSE", "TIMEOUT"])]
    total = len(done)
    wins = int((done["Result"] == "WIN").sum())
    pnl = pd.to_numeric(done["PnL"], errors="coerce").dropna()
    return {
        "total": total,
        "wins": wins,
        "win_rate": (wins / total * 100) if total > 0 else 0.0,
        "avg_pips": (pnl.mean() * 100) if len(pnl) > 0 else 0.0,
    }


def build_signals(pair):
    df = yf.download(pair, period="60d", interval="5m")
    df_1h = yf.download(pair, period="730d", interval="1h")

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)
    if isinstance(df_1h.columns, pd.MultiIndex):
        df_1h.columns = df_1h.columns.droplevel(1)

    # 1時間足のトレンド（未来の情報が混ざらないよう1本ずらす）
    df_1h["SMA_Trend"] = df_1h["Close"].rolling(window=20).mean()
    df_1h["SMA_Slope"] = df_1h["SMA_Trend"].diff()
    df_1h[["SMA_Trend", "SMA_Slope"]] = df_1h[["SMA_Trend", "SMA_Slope"]].shift(1)

    df = pd.merge_asof(
        df.sort_index(),
        df_1h[["SMA_Trend", "SMA_Slope"]].sort_index(),
        left_index=True,
        right_index=True,
    )

    df["SMA_Short"] = df["Close"].rolling(window=5).mean()
    df["SMA_Long"] = df["Close"].rolling(window=20).mean()

    delta = df["Close"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    df["RSI"] = 100 - (100 / (1 + gain / loss))

    high_low = df["High"] - df["Low"]
    high_close = (df["High"] - df["Close"].shift()).abs()
    low_close = (df["Low"] - df["Close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df["ATR"] = tr.rolling(window=14).mean()

    df["High_Max3"] = df["High"].shift(1).rolling(window=3).max()
    df["Low_Min3"] = df["Low"].shift(1).rolling(window=3).min()

    df["Signal"] = 0
    df_jst = (
        df.index.tz_localize("UTC").tz_convert("Asia/Tokyo")
        if df.index.tz is None
        else df.index.tz_convert("Asia/Tokyo")
    )
    # 0時・23時を除外（検証の結果、勝率が悪かったため）
    is_market_active = ((df_jst.hour >= 21) & (df_jst.hour != 23)) | ((df_jst.hour < 6) & (df_jst.hour != 0))

    buy_cond = (
        (df["SMA_Short"] > df["SMA_Long"])
        & (df["Close"] > df["SMA_Trend"])
        & (df["SMA_Slope"] > MIN_SLOPE)
        & (df["RSI"] >= RSI_BUY_LOW) & (df["RSI"] <= RSI_BUY_HIGH)
        & (df["Close"] > df["High_Max3"])
        & is_market_active
    )
    df.loc[buy_cond, "Signal"] = 1

    sell_cond = (
        (df["SMA_Short"] < df["SMA_Long"])
        & (df["Close"] < df["SMA_Trend"])
        & (df["SMA_Slope"] < -MIN_SLOPE)
        & (df["RSI"] >= RSI_SELL_LOW) & (df["RSI"] <= RSI_SELL_HIGH)
        & (df["Close"] < df["Low_Min3"])
        & is_market_active
    )
    df.loc[sell_cond, "Signal"] = -1

    df["Action"] = df["Signal"].diff()
    return df, df_jst


# ==========================================
# 履歴CSVの読み書き
# ==========================================
def load_history(csv_file):
    if os.path.exists(csv_file):
        h = pd.read_csv(csv_file)
    else:
        h = pd.DataFrame(columns=HISTORY_COLUMNS)
    for col in HISTORY_COLUMNS:
        if col not in h.columns:
            h[col] = float("nan") if col in NUM_COLUMNS else ""
    for col in NUM_COLUMNS:
        h[col] = pd.to_numeric(h[col], errors="coerce")
    return h[HISTORY_COLUMNS].copy()


def verify_past_signals(history_df, market_df):
    """結果待ち(Pending)のシグナルを、その後の値動きで判定し直す"""
    m_df = market_df.copy()
    if m_df.index.tz is not None:
        m_df.index = m_df.index.tz_convert("Asia/Tokyo").tz_localize(None)

    for idx, row in history_df.iterrows():
        if row["Result"] != "Pending":
            continue
        sig_time = pd.to_datetime(row["Timestamp"])
        future_data = m_df[m_df.index > sig_time].head(MAX_BARS)
        if future_data.empty:
            continue
        result, pnl = judge_trade(
            row["Type"], float(row["Entry"]), float(row["TP"]), float(row["SL"]), future_data
        )
        if result is not None:
            history_df.loc[idx, "Result"] = result
            history_df.loc[idx, "PnL"] = pnl
    return history_df


# ==========================================
# 見逃し回収：直近の足をさかのぼってシグナルを探す
# ==========================================
def find_signal_events(df, df_jst, hours):
    """直近hours時間の確定した足から、シグナルが出た足(連続の最初の1本)を全部探す。
    最後の1本は未確定なので対象外。"""
    since = pd.Timestamp.now(tz="Asia/Tokyo") - pd.Timedelta(hours=hours)
    is_buy = (df["Signal"] == 1) & (df["Action"] > 0)
    is_sell = (df["Signal"] == -1) & (df["Action"] < 0)
    events = []
    for i in range(len(df) - 1):
        if not (is_buy.iloc[i] or is_sell.iloc[i]):
            continue
        t = df_jst[i]
        if t < since:
            continue
        events.append((i, "BUY" if is_buy.iloc[i] else "SELL", t))
    return events


def age_text(minutes):
    m = int(minutes)
    if m < 60:
        return f"{m}分前"
    h, mm = divmod(m, 60)
    if h < 24:
        return f"{h}時間{mm}分前"
    d, hh = divmod(h, 24)
    return f"{d}日{hh}時間前"


RESULT_TEXT = {
    "WIN": "🏆利確",
    "LOSE": "💧損切",
    "TIMEOUT": "⌛時間切れ",
}


def process_pair(pair):
    label = pair.replace("=X", "")
    csv_file = f"signals_history_{label}.csv"
    first_time = not os.path.exists(csv_file)

    df, df_jst = build_signals(pair)
    history_df = load_history(csv_file)
    known = set(zip(history_df["Timestamp"].astype(str), history_df["Type"].astype(str)))

    lookback = FIRST_LOOKBACK_HOURS if first_time else LOOKBACK_HOURS
    events = find_signal_events(df, df_jst, lookback)

    # まだ記録していないシグナルだけを新規として回収する
    new_rows = []
    for i, sig_type, t in events:
        ts = t.strftime("%Y-%m-%d %H:%M:%S")
        if (ts, sig_type) in known:
            continue
        entry = float(df["Close"].iloc[i])
        atr = float(df["ATR"].iloc[i])
        rsi = float(df["RSI"].iloc[i])
        if pd.isna(atr) or pd.isna(rsi):
            continue
        tp, sl, tp_w, sl_w = calc_tp_sl(entry, atr, sig_type)
        result, pnl = judge_trade(sig_type, entry, tp, sl, df.iloc[i + 1: i + 1 + MAX_BARS])
        new_rows.append({
            "row": {
                "Timestamp": ts, "Type": sig_type, "Entry": entry, "TP": tp, "SL": sl,
                "RSI": rsi, "ATR": atr,
                "Result": result if result is not None else "Pending",
                "PnL": pnl if pnl is not None else float("nan"),
            },
            "time": t, "tp_w": tp_w, "sl_w": sl_w,
        })

    if new_rows:
        add = pd.DataFrame([n["row"] for n in new_rows], columns=HISTORY_COLUMNS)
        history_df = add if history_df.empty else pd.concat([history_df, add], ignore_index=True)

    # 以前から結果待ちだったシグナルも、最新の値動きで判定し直す
    history_df = verify_past_signals(history_df, df)
    history_df.to_csv(csv_file, index=False)

    stats = summarize(history_df)
    stats_line = (
        f"📊 {label}累積勝率: {stats['win_rate']:.1f}% ({stats['wins']}/{stats['total']}勝)\n"
        f"💹 平均: {stats['avg_pips']:+.1f}pips"
    )

    # ---- LINE通知 ----
    now_jst = pd.Timestamp.now(tz="Asia/Tokyo")
    live, late = [], []
    for n in new_rows:
        age = (now_jst - n["time"]).total_seconds() / 60
        (live if age <= LIVE_MINUTES else late).append((n, age))

    sent = False
    for n, _ in live:  # リアルタイムのシグナル: 従来どおり詳細を送る
        r = n["row"]
        is_buy = r["Type"] == "BUY"
        sign, sign_sl = ("+", "-") if is_buy else ("-", "+")
        msg = (
            f"🎯 【{label} 5分足】{'買い' if is_buy else '売り'}シグナル\n"
            f"⏰ 時刻: {n['time'].strftime('%Y-%m-%d %H:%M')}\n"
            f"💰 レート: {r['Entry']:.2f}円\n"
            f"──────────────\n"
            f"📈 TP目安: {r['TP']:.2f}円 ({sign}{n['tp_w']:.2f})\n"
            f"📉 SL目安: {r['SL']:.2f}円 ({sign_sl}{n['sl_w']:.2f})\n"
            f"──────────────\n"
            f"{stats_line}"
        )
        send_line_notification(msg)
        sent = True

    if late:  # 見逃し回収: 1通にまとめて送る（検証用データとして記録）
        late.sort(key=lambda x: x[0]["time"])
        lines = [f"📝 【{label}】見逃し回収 {len(late)}件",
                 "(実行の合間に出ていたシグナルを、さかのぼって見つけました)"]
        for n, age in late[:MAX_LATE_LINES]:
            r = n["row"]
            kind = "買い" if r["Type"] == "BUY" else "売り"
            if r["Result"] in RESULT_TEXT:
                res = f"{RESULT_TEXT[r['Result']]} {r['PnL'] * 100:+.1f}pips"
            else:
                res = "⏳結果待ち"
            lines.append(f"・{n['time'].strftime('%m/%d %H:%M')} {kind} {r['Entry']:.2f}円 {res} ({age_text(age)})")
        if len(late) > MAX_LATE_LINES:
            lines.append(f"…ほか{len(late) - MAX_LATE_LINES}件")
        lines.append(stats_line)
        send_line_notification("\n".join(lines))
        sent = True

    print(f"[{label}] 調べた期間{lookback}時間 / シグナル{len(events)}件 / 新規{len(new_rows)}件 "
          f"/ 累積勝率{stats['win_rate']:.1f}% ({stats['total']}件)")
    return {"label": label, "stats": stats, "sent": sent, "found": len(events), "new": len(new_rows)}


def main():
    results = []
    for pair in PAIRS:
        try:
            results.append(process_pair(pair))
        except Exception as e:  # 片方の通貨ペアで失敗しても、もう片方は続ける
            print(f"[{pair}] エラー: {type(e).__name__}: {e}")

    if IS_MANUAL_RUN and not any(r["sent"] for r in results):
        lines = ["🔧 【手動テスト】動作確認"]
        for r in results:
            s = r["stats"]
            lines.append(
                f"{r['label']}: 勝率{s['win_rate']:.1f}% ({s['wins']}/{s['total']}件) 平均{s['avg_pips']:+.1f}pips"
                f" / 直近のシグナル{r['found']}件"
            )
        lines.append("💡 システムは正常稼働中です。")
        send_line_notification("\n".join(lines))
        print("手動実行テスト通知を送信しました。")


if __name__ == "__main__":
    main()
