import os
import pandas as pd
import requests
import yfinance as yf
from dotenv import load_dotenv

load_dotenv()

CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
USER_ID = os.getenv("LINE_USER_ID")
IS_MANUAL_RUN = os.getenv("IS_MANUAL_RUN", "false").lower() == "true"

CSV_FILE = "signals_history.csv"


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
        else:
            print(f"LINE APIエラー: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"LINE通知処理エラー: {e}")
        return False


# 1. データの取得（5分足 & 1時間足）
df = yf.download("AUDJPY=X", period="5d", interval="5m")
df_1h = yf.download("AUDJPY=X", period="14d", interval="1h")

if isinstance(df.columns, pd.MultiIndex):
    df.columns = df.columns.droplevel(1)
if isinstance(df_1h.columns, pd.MultiIndex):
    df_1h.columns = df_1h.columns.droplevel(1)

# 2. 上位足（1時間足）のトレンド判定
df_1h["SMA_Trend"] = df_1h["Close"].rolling(window=20).mean()
df_1h["SMA_Slope"] = df_1h["SMA_Trend"].diff()

df = pd.merge_asof(
    df.sort_index(),
    df_1h[["SMA_Trend", "SMA_Slope"]].sort_index(),
    left_index=True,
    right_index=True,
)

# 3. 5分足テクニカル指標
df["SMA_Short"] = df["Close"].rolling(window=5).mean()
df["SMA_Long"] = df["Close"].rolling(window=20).mean()

delta = df["Close"].diff()
gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
rs = gain / loss
df["RSI"] = 100 - (100 / (1 + rs))

high_low = df["High"] - df["Low"]
high_close = (df["High"] - df["Close"].shift()).abs()
low_close = (df["Low"] - df["Close"].shift()).abs()
tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
df["ATR"] = tr.rolling(window=14).mean()

# 直近ブレイクアウト判定用（過去3本の高値/安値）
df["High_Max3"] = df["High"].shift(1).rolling(window=3).max()
df["Low_Min3"] = df["Low"].shift(1).rolling(window=3).min()

# 4. サイン判定
df["Signal"] = 0
if df.index.tz is None:
    df_jst = df.index.tz_localize("UTC").tz_convert("Asia/Tokyo")
else:
    df_jst = df.index.tz_convert("Asia/Tokyo")

is_market_active = ~((df_jst.hour >= 6) & (df_jst.hour <= 8))

# 買い条件（条件を厳格化）
buy_cond = (
    (df["SMA_Short"] > df["SMA_Long"])
    & (df["Close"] > df["SMA_Trend"])
    & (df["SMA_Slope"] > 0)
    & (df["RSI"] >= 52)
    & (df["RSI"] <= 68)
    & (df["Close"] > df["High_Max3"])  # 直近3本の高値を更新
    & is_market_active
)
df.loc[buy_cond, "Signal"] = 1

# 売り条件（条件を厳格化）
sell_cond = (
    (df["SMA_Short"] < df["SMA_Long"])
    & (df["Close"] < df["SMA_Trend"])
    & (df["SMA_Slope"] < 0)
    & (df["RSI"] >= 32)
    & (df["RSI"] <= 48)
    & (df["Close"] < df["Low_Min3"])  # 直近3本の安値を更新
    & is_market_active
)
df.loc[sell_cond, "Signal"] = -1

df["Action"] = df["Signal"].diff()


# 5. シグナル結果の検証機能
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

        sig_type = row["Type"]
        tp = float(row["TP"])
        sl = float(row["SL"])

        # 判定期間を少し長めに設定（最大48本分 = 4時間分）
        future_data = m_df[m_df.index > sig_time].head(48)
        if future_data.empty:
            continue

        for _, f_row in future_data.iterrows():
            high = float(f_row["High"])
            low = float(f_row["Low"])

            if sig_type == "BUY":
                if high >= tp:
                    history_df.loc[idx, "Result"] = "WIN"
                    updated = True
                    break
                elif low <= sl:
                    history_df.loc[idx, "Result"] = "LOSE"
                    updated = True
                    break
            elif sig_type == "SELL":
                if low <= tp:
                    history_df.loc[idx, "Result"] = "WIN"
                    updated = True
                    break
                elif high >= sl:
                    history_df.loc[idx, "Result"] = "LOSE"
                    updated = True
                    break

    return history_df, updated


# CSVの読み込みまたは新規作成
if os.path.exists(CSV_FILE):
    history_df = pd.read_csv(CSV_FILE)
else:
    history_df = pd.DataFrame(
        columns=[
            "Timestamp",
            "Type",
            "Entry",
            "TP",
            "SL",
            "RSI",
            "ATR",
            "Result",
        ]
    )

# 過去シグナルの結果更新
history_df, was_updated = verify_past_signals(history_df, df)

# 勝率計算
total_finished = len(history_df[history_df["Result"].isin(["WIN", "LOSE"])])
wins = len(history_df[history_df["Result"] == "WIN"])
win_rate = (wins / total_finished * 100) if total_finished > 0 else 0.0

# 6. 直近データの判定＆記録
target_data = df.iloc[-2]
target_index_jst = df_jst[-2]

latest_date = target_index_jst.strftime("%Y-%m-%d %H:%M")
latest_close = float(target_data["Close"])
latest_rsi = float(target_data["RSI"])
latest_atr = float(target_data["ATR"])
latest_action_val = float(target_data["Action"])
current_signal = int(target_data["Signal"])

# TP/SL幅の拡大（最低0.08円＝8pip以上の幅を保証）
dynamic_tp_width = max(latest_atr * 2.2, 0.10)
dynamic_sl_width = max(latest_atr * 1.8, 0.08)

signal_sent = False

if current_signal == 1 and latest_action_val > 0:
    tp_price = latest_close + dynamic_tp_width
    sl_price = latest_close - dynamic_sl_width

    new_row = pd.DataFrame(
        [
            {
                "Timestamp": target_index_jst.strftime("%Y-%m-%d %H:%M:%S"),
                "Type": "BUY",
                "Entry": latest_close,
                "TP": tp_price,
                "SL": sl_price,
                "RSI": latest_rsi,
                "ATR": latest_atr,
                "Result": "Pending",
            }
        ]
    )
    history_df = pd.concat([history_df, new_row], ignore_index=True)

    msg = (
        f"🎯 【5分足】買いシグナル発信\n"
        f"⏰ 時刻: {latest_date}\n"
        f"💰 レート: {latest_close:.2f}円\n"
        f"──────────────\n"
        f"📈 利確(TP)目安: {tp_price:.2f}円 (+{dynamic_tp_width:.2f})\n"
        f"📉 損切(SL)目安: {sl_price:.2f}円 (-{dynamic_sl_width:.2f})\n"
        f"──────────────\n"
        f"📊 蓄積データ勝率: {win_rate:.1f}% ({wins}/{total_finished}勝)"
    )
    send_line_notification(msg)
    signal_sent = True

elif current_signal == -1 and latest_action_val < 0:
    tp_price = latest_close - dynamic_tp_width
    sl_price = latest_close + dynamic_sl_width

    new_row = pd.DataFrame(
        [
            {
                "Timestamp": target_index_jst.strftime("%Y-%m-%d %H:%M:%S"),
                "Type": "SELL",
                "Entry": latest_close,
                "TP": tp_price,
                "SL": sl_price,
                "RSI": latest_rsi,
                "ATR": latest_atr,
                "Result": "Pending",
            }
        ]
    )
    history_df = pd.concat([history_df, new_row], ignore_index=True)

    msg = (
        f"🎯 【5分足】売りシグナル発信\n"
        f"⏰ 時刻: {latest_date}\n"
        f"💰 レート: {latest_close:.2f}円\n"
        f"──────────────\n"
        f"📈 利確(TP)目安: {tp_price:.2f}円 (-{dynamic_tp_width:.2f})\n"
        f"📉 損切(SL)目安: {sl_price:.2f}円 (+{dynamic_sl_width:.2f})\n"
        f"──────────────\n"
        f"📊 蓄積データ勝率: {win_rate:.1f}% ({wins}/{total_finished}勝)"
    )
    send_line_notification(msg)
    signal_sent = True

# 履歴を書き込み保存
history_df.to_csv(CSV_FILE, index=False)

if IS_MANUAL_RUN and not signal_sent:
    test_msg = (
        f"🔧 【手動テスト】学習・検証型モデル動作確認\n"
        f"⏰ 時刻: {latest_date}\n"
        f"💰 レート: {latest_close:.2f}円 / RSI: {latest_rsi:.1f}\n"
        f"📊 過去シグナル検証勝率: {win_rate:.1f}% ({wins}/{total_finished}勝)\n"
        f"💡 システムは正常稼働中です。"
    )
    send_line_notification(test_msg)
    print("手動実行テスト通知を送信しました。")
elif not signal_sent:
    print(f"新規シグナルなし (現在の過去検証勝率: {win_rate:.1f}%)")
