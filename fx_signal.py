import requests
import pandas as pd
import yfinance as yf
import matplotlib.pyplot as plt
import base64
from io import BytesIO

def send_line_notification(message, image_path=None):
    CHANNEL_ACCESS_TOKEN = 'rqISRcqCU7mstgaP1rxVVTEaVgmbWYEbTqR4HZPDqM7HuHk78/Nj9Okrq/5yhj0xqrn36a0fEcgAh/fSJdKFdq8sdDUf6aqcxCeJvodw16XlcwWqMycpV4Y37N7mru2cSFBSbkgBrtO0BKqTNUiMNQdB04t89/1O/w1cDnyilFU='
    USER_ID = 'U0e89974679349b0e3875e081aaf5f806'

    # Imgurの安定した最新API
    headers_imgur = {'Authorization': 'Client-ID c9822a1ea917bd9'}
    image_url = None

    if image_path:
        try:
            with open(image_path, 'rb') as f:
                img_data = f.read()
            # 画像を直リンク可能なURLへ変換
            res = requests.post('https://api.imgur.com/3/upload', headers=headers_imgur, data={'image': img_data})
            if res.status_code == 200:
                image_url = res.json()['data']['link']
                print(f"画像変換成功: {image_url}")
            else:
                print(f"画像変換失敗: {res.status_code}")
        except Exception as e:
            print(f"画像処理エラー: {e}")

    # LINE API 送信処理
    url = "https://api.line.me/v2/bot/message/push"
    headers_line = {
        "Authorization": f"Bearer {CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    messages_payload = [{"type": "text", "text": message}]

    if image_url:
        messages_payload.append({
            "type": "image",
            "originalContentUrl": image_url,
            "previewImageUrl": image_url
        })

    payload = {
        "to": USER_ID,
        "messages": messages_payload
    }

    try:
        response = requests.post(url, headers=headers_line, json=payload)
        if response.status_code == 200:
            print("【成功】LINEへの画像送信が完了しました！")
            return True
        else:
            print(f"LINE APIエラー: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"LINE通知処理に失敗しました: {e}")
        return False

# 1. データの取得
df = yf.download("AUDJPY=X", period="5d", interval="15m")
if isinstance(df.columns, pd.MultiIndex):
    df.columns = df.columns.droplevel(1)

df['SMA_Short'] = df['Close'].rolling(window=5).mean()
df['SMA_Long'] = df['Close'].rolling(window=20).mean()

# 2. チャート画像の生成・保存
df_plot = df.tail(50)
plt.figure(figsize=(10, 5))
plt.plot(df_plot.index, df_plot['Close'], label='AUD/JPY Close', color='black', alpha=0.6)
plt.plot(df_plot.index, df_plot['SMA_Short'], label='5-min SMA', color='dodgerblue')
plt.plot(df_plot.index, df_plot['SMA_Long'], label='20-min SMA', color='orange')
plt.title('AUD/JPY 15m Speed Signal Chart', fontsize=12)
plt.grid(True, linestyle='--', alpha=0.5)
plt.legend(loc='upper left')
plt.tight_layout()

chart_filename = 'trading_chart.png'
plt.savefig(chart_filename, dpi=150)
plt.close()

# ★ テスト送信 ★
test_msg = "🧪 【動作テスト送信】\n画像の表示チェックです！"
send_line_notification(test_msg, image_path=chart_filename)
