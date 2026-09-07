from linebot import LineBotApi
from linebot.models import TextSendMessage, ImageSendMessage
import pandas as pd
import yfinance as yf
import matplotlib.pyplot as plt
import time
import requests
import json

def send_line_notification_with_blob(message, image_path):    
    CHANNEL_ACCESS_TOKEN = 'rqISRcqCU7mstgaP1rxVVTEaVgmbWYEbTqR4HZPDqM7HuHk78/Nj9Okrq/5yhj0xqrn36a0fEcgAh/fSJdKFdq8sdDUf6aqcxCeJvodw16XlcwWqMycpV4Y37N7mru2cSFBSbkgBrtO0BKqTNUiMNQdB04t89/1O/w1cDnyilFU='
    USER_ID = 'U0e89974679349b0e3875e081aaf5f806'
    
    try:
        line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
        line_bot_api.push_message(USER_ID, messages=TextSendMessage(text=message))
        
        # LINE公式のアップロードサーバーへバイナリとして直接画像を送信してフォトエラーを回避
        url = "https://line.me"
        headers = {
            "Authorization": f"Bearer {CHANNEL_ACCESS_TOKEN}",
            "Content-Type": "image/png"
        }
        
        with open(image_path, "rb") as f:
            image_data = f.read()
            
        response = requests.post(url, headers=headers, data=image_data)
        if response.status_code == 200:
            print("Success: Image content uploaded directly to LINE Server.")
        else:
            print(f"LINE Blob upload failed: {response.status_code} - {response.text}")
            
    except Exception as e:
        print(f"Error: LINE notification failed: {e}")

print("Downloading data...")
df = yf.download("AUDJPY=X", period="5d", interval="15m")
df_1h = yf.download("AUDJPY=X", period="7d", interval="1h")

if isinstance(df.columns, pd.MultiIndex):
    df.columns = df.columns.droplevel(1)
if isinstance(df_1h.columns, pd.MultiIndex):
    df_1h.columns = df_1h.columns.droplevel(1)

df_1h['SMA_Trend'] = df_1h['Close'].rolling(window=20).mean()
df = pd.merge_asof(df.sort_index(), df_1h[['SMA_Trend']].sort_index(), left_index=True, right_index=True)
df = df.rename(columns={'SMA_Trend': 'Trend_1h_aligned'})

df['SMA_Short'] = df['Close'].rolling(window=5).mean()
df['SMA_Long'] = df['Close'].rolling(window=20).mean()

delta = df['Close'].diff()
gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
rs = gain / loss
df['RSI'] = 100 - (100 / (1 + rs))

# ATR (直近14本の平均値幅 = 変動の激しさ) の計算
high_low = df['High'] - df['Low']
high_close = (df['High'] - df['Close'].shift()).abs()
low_close = (df['Low'] - df['Close'].shift()).abs()
tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
df['ATR'] = tr.rolling(window=14).mean()

df['Signal'] = 0

if df.index.tz is None:
    df_jst = df.index.tz_localize('UTC').tz_convert('Asia/Tokyo')
else:
    df_jst = df.index.tz_convert('Asia/Tokyo')

is_market_active = ~((df_jst.hour >= 6) & (df_jst.hour <= 8))

# 【最重要】大荒れ相場フィルターのロジック
# 今の15分足の値幅(tr)が、過去14本の平均値幅(ATR)の2.0倍を超えて大暴れしている時は取引しない
is_market_too_wild = tr > (df['ATR'] * 2.0)

# 【勝率重視】買い条件（相場が大荒れしていない時だけ有効）
buy_cond = (df['SMA_Short'] > df['SMA_Long']) & (df['Close'] > df['Trend_1h_aligned']) & (df['RSI'] >= 53) & (df['RSI'] <= 65) & is_market_active & (~is_market_too_wild)
df.loc[buy_cond, 'Signal'] = 1

# 【勝率重視】売り条件（相場が大荒れしていない時だけ有効）
sell_cond = (df['SMA_Short'] < df['SMA_Long']) & (df['Close'] < df['Trend_1h_aligned']) & (df['RSI'] >= 35) & (df['RSI'] <= 48) & is_market_active & (~is_market_too_wild)
df.loc[sell_cond, 'Signal'] = -1

df['Action'] = df['Signal'].diff()

df_plot = df.tail(50)
plt.figure(figsize=(10, 5))
plt.plot(df_plot.index, df_plot['Close'], label='AUD/JPY Close', color='black', alpha=0.6, linewidth=1.5)
plt.plot(df_plot.index, df_plot['SMA_Short'], label='5-min SMA', color='dodgerblue', linewidth=1.2)
plt.plot(df_plot.index, df_plot['SMA_Long'], label='20-min SMA', color='orange', linewidth=1.2)

buy_signals = df_plot[df_plot['Action'] == 1]
if not buy_signals.empty:
    plt.scatter(buy_signals.index, buy_signals['Close'], marker='^', color='limegreen', s=120, label='BUY', zorder=5)

sell_signals = df_plot[df_plot['Action'] == -1]
if not sell_signals.empty:
    plt.scatter(sell_signals.index, sell_signals['Close'], marker='v', color='crimson', s=120, label='SELL', zorder=5)

plt.title('AUD/JPY 15m Safe Filter Chart', fontsize=12)
plt.grid(True, linestyle='--', alpha=0.5)
plt.legend(loc='upper left')
plt.xticks(rotation=15)
plt.tight_layout()

chart_filename = 'trading_chart.png'
plt.savefig(chart_filename, dpi=150)
plt.close()

target_data = df.iloc[-1]
target_index_jst = df_jst[-1]

latest_date = target_index_jst.strftime('%Y-%m-%d %H:%M')
latest_close = target_data['Close'].item() if hasattr(target_data['Close'], 'item') else target_data['Close']
latest_rsi = target_data['RSI'].item() if hasattr(target_data['RSI'], 'item') else target_data['RSI']
latest_action_val = target_data['Action'].item() if hasattr(target_data['Action'], 'item') else target_data['Action']

current_atr = target_data['ATR'].item() if hasattr(target_data['ATR'], 'item') else target_data['ATR']
if pd.isna(current_atr) or current_atr <= 0:
    current_atr = 0.20 

dynamic_width = round(current_atr * 1.5, 2)

print(f"JST: {latest_date} / Close: {latest_close:.2f} / RSI: {latest_rsi:.1f} / Dynamic Width: {dynamic_width:.2f}")

if latest_action_val != 0 and not pd.isna(latest_action_val):
    current_signal = target_data['Signal'].item() if hasattr(target_data['Signal'], 'item') else target_data['Signal']
    if current_signal == 1:
        tp_price = latest_close + dynamic_width
        sl_price = latest_close - dynamic_width
        msg = (f"🎯 BUY Signal (Safe Trend)\n"
               f"⏰ Time: {latest_date} (JST)\n"
               f"💰 Rate: {latest_close:.2f} (RSI: {latest_rsi:.1f})\n"
               f"---\n"
               f"📊 Width: {dynamic_width:.2f}JPY\n"
               f"📈 TP: {tp_price:.2f}\n"
               f"📉 SL: {sl_price:.2f}")
    elif current_signal == -1:
        tp_price = latest_close - dynamic_width
        sl_price = latest_close + dynamic_width
        msg = (f"🎯 SELL Signal (Safe Trend)\n"
               f"⏰ Time: {latest_date} (JST)\n"
               f"💰 Rate: {latest_close:.2f} (RSI: {latest_rsi:.1f})\n"
               f"---\n"
               f"📊 Width: {dynamic_width:.2f}JPY\n"
               f"📈 TP: {tp_price:.2f}\n"
               f"📉 SL: {sl_price:.2f}")
    else:
        msg = f"⚠️ Signal Cleared\n⏰ Time: {latest_date} (JST)"
    
    time.sleep(5)
    send_line_notification_with_blob(msg, chart_filename)
else:
    print("No signal change.")
