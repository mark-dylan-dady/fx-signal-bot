import requests
import pandas as pd
import yfinance as yf

def send_line_notification(message):
    CHANNEL_ACCESS_TOKEN = 'rqISRcqCU7mstgaP1rxVVTEaVgmbWYEbTqR4HZPDqM7HuHk78/Nj9Okrq/5yhj0xqrn36a0fEcgAh/fSJdKFdq8sdDUf6aqcxCeJvodw16XlcwWqMycpV4Y37N7mru2cSFBSbkgBrtO0BKqTNUiMNQdB04t89/1O/w1cDnyilFU='
    USER_ID = 'U0e89974679349b0e3875e081aaf5f806'

    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Authorization": f"Bearer {CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    payload = {
        "to": USER_ID,
        "messages": [{"type": "text", "text": message}]
    }

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

# 1. データの取得
df = yf.download("AUDJPY=X", period="5d", interval="15m")
df_1h = yf.download("AUDJPY=X", period="7d", interval="1h")

if isinstance(df.columns, pd.MultiIndex):
    df.columns = df.columns.droplevel(1)
if isinstance(df_1h.columns, pd.MultiIndex):
    df_1h.columns = df_1h.columns.droplevel(1)

# 2. 上位足トレンド判定
df_1h['SMA_Trend'] = df_1h['Close'].rolling(window=20).mean()
df = pd.merge_asof(df.sort_index(), df_1h[['SMA_Trend']].sort_index(), left_index=True, right_index=True)
df = df.rename(columns={'SMA_Trend': 'Trend_1h_aligned'})

# 3. テクニカル指標計算
df['SMA_Short'] = df['Close'].rolling(window=5).mean()
df['SMA_Long'] = df['Close'].rolling(window=20).mean()

delta = df['Close'].diff()
gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
rs = gain / loss
df['RSI'] = 100 - (100 / (1 + rs))

# 4. サイン判定
df['Signal'] = 0
if df.index.tz is None:
    df_jst = df.index.tz_localize('UTC').tz_convert('Asia/Tokyo')
else:
    df_jst = df.index.tz_convert('Asia/Tokyo')

is_market_active = ~((df_jst.hour >= 6) & (df_jst.hour <= 8))

buy_cond = (df['SMA_Short'] > df['SMA_Long']) & (df['Close'] > df['Trend_1h_aligned']) & (df['RSI'] >= 53) & (df['RSI'] <= 65) & is_market_active
df.loc[buy_cond, 'Signal'] = 1

sell_cond = (df['SMA_Short'] < df['SMA_Long']) & (df['Close'] < df['Trend_1h_aligned']) & (df['RSI'] >= 35) & (df['RSI'] <= 48) & is_market_active
df.loc[sell_cond, 'Signal'] = -1

df['Action'] = df['Signal'].diff()

# 5. リアルタイム判定＆通知
target_data = df.iloc[-1]
target_index_jst = df_jst[-1]

latest_date = target_index_jst.strftime('%Y-%m-%d %H:%M')
latest_close = target_data['Close'].item() if hasattr(target_data['Close'], 'item') else target_data['Close']
latest_rsi = target_data['RSI'].item() if hasattr(target_data['RSI'], 'item') else target_data['RSI']
latest_action_val = target_data['Action'].item() if hasattr(target_data['Action'], 'item') else target_data['Action']

PIPS_WIDTH = 0.20

if latest_action_val != 0 and not pd.isna(latest_action_val):
    current_signal = target_data['Signal'].item() if hasattr(target_data['Signal'], 'item') else target_data['Signal']

    if current_signal == 1:
        tp_price = latest_close + PIPS_WIDTH
        sl_price = latest_close - PIPS_WIDTH
        msg = (f"🎯 【厳選サイン】買い（高確率ゾーン）\n"
               f"⏰ 時刻: {latest_date}\n"
               f"💰 レート: {latest_close:.2f}円 (RSI: {latest_rsi:.1f})\n"
               f"ーーー\n"
               f"📈 利確(TP): {tp_price:.2f}円\n"
               f"📉 損切(SL): {sl_price:.2f}円")

    elif current_signal == -1:
        tp_price = latest_close - PIPS_WIDTH
        sl_price = latest_close + PIPS_WIDTH
        msg = (f"🎯 【厳選サイン】売り（高確率ゾーン）\n"
               f"⏰ 時刻: {latest_date}\n"
               f"💰 レート: {latest_close:.2f}円 (RSI: {latest_rsi:.1f})\n"
               f"ーーー\n"
               f"📈 利確(TP): {tp_price:.2f}円\n"
               f"📉 損切(SL): {sl_price:.2f}円")
    else:
        msg = f"⚠️ 【15分足】トレンド変化または過熱のためサイン解除\n⏰ 時刻: {latest_date}"

    send_line_notification(msg)
else:
    print("シグナル変化なし")
