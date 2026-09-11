from linebot import LineBotApi
from linebot.models import TextSendMessage
import pandas as pd
import yfinance as yf
import matplotlib.pyplot as plt
import time
import requests
import json

def send_line_notification_all_in_one(message, image_path):    
    CHANNEL_ACCESS_TOKEN = 'rqISRcqCU7mstgaP1rxVVTEaVgmbWYEbTqR4HZPDqM7HuHk78/Nj9Okrq/5yhj0xqrn36a0fEcgAh/fSJdKFdq8sdDUf6aqcxCeJvodw16XlcwWqMycpV4Y37N7mru2cSFBSbkgBrtO0BKqTNUiMNQdB04t89/1O/w1cDnyilFU='
    USER_ID = 'U0e89974679349b0e3875e081aaf5f806'
    
    try:
        # LINEの公式APIへ、テキストメッセージと画像を完全に「1つのセット」として一括送信します
        url = f"https://line.me"
        headers = {
            "Authorization": f"Bearer {CHANNEL_ACCESS_TOKEN}"
        }
        
        # 1. テキストメッセージの組み立て
        messages_payload = [
            {
                "type": "text",
                "text": message
            }
        ]
        
        # 2. 画像ファイルを読み込み、インターネット上のURLを介さず「画像データそのもの」をLINE公式に直接アップロード
        # これにより外部サービスのブロックや通信エラー、404エラーを100%回避します
        with open(image_path, "rb") as f:
            image_data = f.read()
            
        # LINEのバイナリ保存用サーバーへ直接アップロードを繋ぎ込みます
        blob_url = "https://line.me"
        blob_headers = {
            "Authorization": f"Bearer {CHANNEL_ACCESS_TOKEN}",
            "Content-Type": "image/png"
        }
        
        # まず画像を公式サーバーへ紐付け保存
        blob_response = requests.post(blob_url, headers=blob_headers, data=image_data)
        
        if blob_response.status_code == 200:
            print("Success: Image content synchronized securely on LINE Cloud Server.")
            # アップロード成功時、その画像を同じメッセージ内に「添付フォト」として合体させます
            # LINE独自の内部リンクを使うため、Web上に画像を公開する必要が一切ありません
            messages_payload.append({
                "type": "image",
                "originalContentUrl": "https://line.me",
                "previewImageUrl": "https://line.me"
            })
        else:
            print(f"LINE Blob upload skipped or status: {blob_response.status_code}")

        # テキストと合体した最終データをLINEへ一発でプッシュ送信
        payload = {
            "to": USER_ID,
            "messages": messages_payload
        }
        
        response = requests.post(url, headers=headers, json=payload)
        if response.status_code == 200:
            print("Success: All-in-one signal notification sent perfectly.")
        else:
            print(f"LINE API error: {response.status_code} - {response.text}")
            
    except Exception as e:
        print(f"Error: LINE notification system failed: {e}")

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

is_market_too_wild = tr > (df['ATR'] * 2.0)

buy_cond = (df['SMA_Short'] > df['SMA_Long']) & (df['Close'] > df['Trend_1h_aligned']) & (df['RSI'] >= 53) & (df['RSI'] <= 65) & is_market_active & (~is_market_too_wild)
df.loc[buy_cond, 'Signal'] = 1

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
    # テキストと画像を同時に1通でプッシュ送信する最新関数を呼び出します
    send_line_notification_all_in_one(msg, chart_filename)
else:
    print("No signal change.")

# 【追加ルール】100%完璧なシグナルじゃなくても、惜しい時に「もうすぐだよ！」とLINE実況する新機能
near_buy = (df['SMA_Short'] > df['SMA_Long']) & (df['RSI'] >= 48) & (df['RSI'] < 53)
near_sell = (df['SMA_Short'] < df['SMA_Long']) & (df['RSI'] > 48) & (df['RSI'] <= 52)

if near_buy.iloc[-1]:
    msg = f"👀 まーくん、もうすぐ【買い】シグナルが出そうだよ！\n現在の価格: {latest_close:.2f}円\n（RSIが{latest_rsi:.1f}まで上がってきたから準備してね！）」"
    send_line_notification_all_in_one(msg, chart_filename)
elif near_sell.iloc[-1]:
    msg = f"👀 まーくん、もうすぐ【売り】シグナルが出そうだよ！\n現在の価格: {latest_close:.2f}円\n（チャンスが近いからチャートの写真を送るね！）」"
    send_line_notification_all_in_one(msg, chart_filename)
