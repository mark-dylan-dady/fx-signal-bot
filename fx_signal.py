import os
import pandas as pd
import requests
import yfinance as yf
from dotenv import load_dotenv

load_dotenv()

CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
USER_ID = os.getenv("LINE_USER_ID")

# 手動実行フラグの取得
IS_MANUAL_RUN = os.getenv("IS_MANUAL_RUN", "false").lower() == "true"


def send_line_notification(message):
    if not CHANNEL_ACCESS_TOKEN or not USER_ID:
        print(
            "エラー: LINE_CHANNEL_ACCESS_TOKEN または LINE_USER_ID が設定されていません。"
        )
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


# 1. データの取得（1分足 と 1時間足）
df = yf.download("AUDJPY=X", period="1d", interval="1m")
df_1h = yf.download("AUDJPY=X", period="7d", interval="1h")

if isinstance(df.columns, pd.MultiIndex):
    df.columns = df.columns.droplevel(1)
if isinstance(df_1h.columns, pd.MultiIndex):
    df_1h.columns = df_1h.columns.droplevel(1)

# 2. 上位足（1時間足）のトレンド判定（大波の方向）
df_1h["SMA_Trend"] = df_1h["Close"].rolling(window=20).mean()
df_1h["SMA_Slope"] = df_1h["SMA_Trend"].diff()

df = pd.merge_asof(
    df.sort_index(),
    df_1h[["SMA_Trend", "SMA_Slope"]].sort_index(),
    left_index=True,
    right_index=True,
)

# 3. 1分足のテクニカル指標計算（高速トリガー）
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

# 4. サイン判定（1分足ベース）
df["Signal"] = 0
if df.index.tz is None:
    df_jst = df.index.tz_localize("UTC").tz_convert("Asia/Tokyo")
else:
    df_jst = df.index.tz_convert("Asia/Tokyo")

# 早朝のボラティリティ低い時間を除外
is_market_active = ~((df_jst.hour >= 6) & (df_jst.hour <= 8))

# 買い条件: 1時間足が上昇 ＆ 1分足で短期が中期を上抜け・RSI適正範囲
buy_cond = (
    (df["SMA_Short"] > df["SMA_Long"])
    & (df["Close"] > df["SMA_Trend"])
    & (df["SMA_Slope"] > 0)
    & (df["RSI"] >= 50)
    & (df["RSI"] <= 65)
    & is_market_active
)
df.loc[buy_cond, "Signal"] = 1

# 売り条件: 1時間足が下落 ＆ 1分足で短期が中期を下抜け・RSI適正範囲
sell_cond = (
    (df["SMA_Short"] < df["SMA_Long"])
    & (df["Close"] < df["SMA_Trend"])
    & (df["SMA_Slope"] < 0)
    & (df["RSI"] >= 35)
    & (df["RSI"] <= 50)
    & is_market_active
)
df.loc[sell_cond, "Signal"] = -1

df["Action"] = df["Signal"].diff()

# 5. リアルタイム判定＆通知（確定直前の1分足）
target_data = df.iloc[-2]
target_index_jst = df_jst[-2]

latest_date = target_index_jst.strftime("%Y-%m-%d %H:%M")
latest_close = (
    target_data["Close"].item()
    if hasattr(target_data["Close"], "item")
    else target_data["Close"]
)
latest_rsi = (
    target_data["RSI"].item()
    if hasattr(target_data["RSI"], "item")
    else target_data["RSI"]
)
latest_atr = (
    target_data["ATR"].item()
    if hasattr(target_data["ATR"], "item")
    else target_data["ATR"]
)
latest_action_val = (
    target_data["Action"].item()
    if hasattr(target_data["Action"], "item")
    else target_data["Action"]
)
current_signal = (
    target_data["Signal"].item()
    if hasattr(target_data["Signal"], "item")
    else target_data["Signal"]
)

# 1分足向け：薄利多売用に利確・損切り幅をタイトに設定（ATRの1.0倍 / 1.2倍）
dynamic_tp_width = latest_atr * 1.0
dynamic_sl_width = latest_atr * 1.2

signal_sent = False

if current_signal == 1 and latest_action_val > 0:
    tp_price = latest_close + dynamic_tp_width
    sl_price = latest_close - dynamic_sl_width
    msg = (
        f"⚡ 【1分足スキャル】買いシグナル\n"
        f"⏰ 時刻: {latest_date}\n"
        f"💰 レート: {latest_close:.2f}円\n"
        f"──────────────\n"
        f"📊 【条件】1時間足上昇 ＋ 1分足ブレイク\n"
        f"・RSI: {latest_rsi:.1f} / ATR: {latest_atr:.3f}円\n"
        f"──────────────\n"
        f"📈 薄利TP目安: {tp_price:.2f}円 (+{dynamic_tp_width:.2f})\n"
        f"📉 タイトSL目安: {sl_price:.2f}円 (-{dynamic_sl_width:.2f})"
    )
    send_line_notification(msg)
    signal_sent = True

elif current_signal == -1 and latest_action_val < 0:
    tp_price = latest_close - dynamic_tp_width
    sl_price = latest_close + dynamic_sl_width
    msg = (
        f"⚡ 【1分足スキャル】売りシグナル\n"
        f"⏰ 時刻: {latest_date}\n"
        f"💰 レート: {latest_close:.2f}円\n"
        f"──────────────\n"
        f"📊 【条件】1時間足下落 ＋ 1分足ブレイク\n"
        f"・RSI: {latest_rsi:.1f} / ATR: {latest_atr:.3f}円\n"
        f"──────────────\n"
        f"📈 薄利TP目安: {tp_price:.2f}円 (-{dynamic_tp_width:.2f})\n"
        f"📉 タイトSL目安: {sl_price:.2f}円 (+{dynamic_sl_width:.2f})"
    )
    send_line_notification(msg)
    signal_sent = True

# 手動実行用テスト通知
if IS_MANUAL_RUN and not signal_sent:
    test_msg = (
        f"🔧 【手動テスト】1分足モード動作確認\n"
        f"⏰ 時刻: {latest_date}\n"
        f"💰 レート: {latest_close:.2f}円 / RSI: {latest_rsi:.1f}\n"
        f"💡 シグナルなし（正常稼働中）"
    )
    send_line_notification(test_msg)
    print("手動実行テスト通知を送信しました。")
elif not signal_sent:
    print("新規エントリーシグナルなし")
