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
# 設定（現時点のベスト設定。テスト7回目で反映）
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

# 【今回追加】EURJPYを監視対象に追加（USDJPYは成績が悪いため除外）
# AUDJPYは引き続き本番、EURJPYはサンプルを貯めるための並行監視
PAIRS = ["AUDJPY=X", "EURJPY=X"]


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
        response = requests.post(url, headers=headers, json=payload)
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
        if hit_sl:
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


def verify_past_signals(history_df, market_df):
    updated = False
    m_df = market_df.copy()
    if m_df.index.tz is not None:
        m_df.index = m_df.index.tz_convert("Asia/Tokyo").tz_localize(None)

    for idx, row in history_df.iterrows():
        if row["Result"] != "Pending":
            continue
        sig_time = pd.to_datetime(row["Timestamp"])
        if sig_time.tzinfo is not None:
            sig_time = sig_time.tz_convert("Asia/Tokyo").tz_localize(None)

        future_data = m_df[m_df.index > sig_time].head(MAX_BARS)
        if future_data.empty:
            continue

        result, pnl = judge_trade(row["Type"], float(row["Entry"]), float(row["TP"]), float(row["SL"]), future_data)
        if result is not None:
            history_df.loc[idx, "Result"] = result
            history_df.loc[idx, "PnL"] = pnl
            updated = True

    return history_df, updated


def process_pair(pair):
    csv_file = f"signals_history_{pair.replace('=X', '')}.csv"
    df, df_jst = build_signals(pair)

    if os.path.exists(csv_file):
        history_df = pd.read_csv(csv_file)
    else:
        history_df = pd.DataFrame(columns=["Timestamp", "Type", "Entry", "TP", "SL", "RSI", "ATR", "Result", "PnL"])
    if "PnL" not in history_df.columns:
        history_df["PnL"] = float("nan")
    for col in ["Entry", "TP", "SL", "PnL"]:
        history_df[col] = pd.to_numeric(history_df[col], errors="coerce")

    history_df, _ = verify_past_signals(history_df, df)
    stats = summarize(history_df)

    target_data = df.iloc[-2]
    target_index_jst = df_jst[-2]
    latest_date = target_index_jst.strftime("%Y-%m-%d %H:%M")
    latest_close = float(target_data["Close"])
    latest_rsi = float(target_data["RSI"])
    latest_atr = float(target_data["ATR"])
    latest_action_val = float(target_data["Action"])
    current_signal = int(target_data["Signal"])

    is_buy = current_signal == 1 and latest_action_val > 0
    is_sell = current_signal == -1 and latest_action_val < 0
    signal_sent = False
    pair_label = pair.replace("=X", "")

    if is_buy or is_sell:
        sig_type = "BUY" if is_buy else "SELL"
        tp_price, sl_price, tp_width, sl_width = calc_tp_sl(latest_close, latest_atr, sig_type)

        new_row = pd.DataFrame([{
            "Timestamp": target_index_jst.strftime("%Y-%m-%d %H:%M:%S"),
            "Type": sig_type, "Entry": latest_close, "TP": tp_price, "SL": sl_price,
            "RSI": latest_rsi, "ATR": latest_atr, "Result": "Pending", "PnL": float("nan"),
        }])
        history_df = pd.concat([history_df, new_row], ignore_index=True)

        label = "買い" if is_buy else "売り"
        sign, sign_sl = ("+", "-") if is_buy else ("-", "+")
        msg = (
            f"🎯 【{pair_label} 5分足】{label}シグナル\n"
            f"⏰ 時刻: {latest_date}\n"
            f"💰 レート: {latest_close:.2f}円\n"
            f"──────────────\n"
            f"📈 TP目安: {tp_price:.2f}円 ({sign}{tp_width:.2f})\n"
            f"📉 SL目安: {sl_price:.2f}円 ({sign_sl}{sl_width:.2f})\n"
            f"──────────────\n"
            f"📊 {pair_label}累積勝率: {stats['win_rate']:.1f}% ({stats['wins']}/{stats['total']}勝)\n"
            f"💹 平均: {stats['avg_pips']:+.1f}pips"
        )
        send_line_notification(msg)
        signal_sent = True

    history_df.to_csv(csv_file, index=False)

    if not signal_sent:
        print(f"[{pair_label}] 新規シグナルなし (累積勝率: {stats['win_rate']:.1f}%, {stats['total']}件)")

    return pair_label, stats, signal_sent


results = [process_pair(p) for p in PAIRS]

if IS_MANUAL_RUN and not any(r[2] for r in results):
    lines = ["🔧 【手動テスト】動作確認"]
    for label, stats, _ in results:
        lines.append(f"{label}: 勝率{stats['win_rate']:.1f}% ({stats['wins']}/{stats['total']}件) 平均{stats['avg_pips']:+.1f}pips")
    lines.append("💡 システムは正常稼働中です。")
    send_line_notification("\n".join(lines))
    print("手動実行テスト通知を送信しました。")
