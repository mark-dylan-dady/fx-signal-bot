import requests
import pandas as pd
import yfinance as yf
import matplotlib.pyplot as plt

def upload_image_to_imgur(image_path):
    headers = {'Authorization': 'Client-ID 544ba839e44d8b0'}
    try:
        with open(image_path, 'rb') as f:
            image_data = f.read()
            
        response = requests.post(
            'https://api.imgur.com/3/image',
            headers=headers,
            data={'image': image_data}
        )
        
        if response.status_code == 200:
            return response.json()['data']['link']
        else:
            print(f"Imgurアップロード失敗: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"画像読み込みエラー: {e}")
        return None

def send_line_notification(message, image_path=None):
    CHANNEL_ACCESS_TOKEN = 'rqISRcqCU7mstgaP1rxVVTEaVgmbWYEbTqR4HZPDqM7HuHk78/Nj9Okrq/5yhj0xqrn36a0fEcgAh/fSJdKFdq8sdDUf6aqcxCeJvodw16XlcwWqMycpV4Y37N7mru2cSFBSbkgBrtO0BKqTNUiMNQdB04t89/1O/w1cDnyilFU='
    USER_ID = 'U0e89974679349b0e3875e081aaf5f806'

    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Authorization": f"Bearer {CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    messages_payload = [{"type": "text", "text": message}]

    if image_path:
        print("テスト画像をクラウドへアップロード中...")
        uploaded_url = upload_image_to_imgur(image_path)
        
        if uploaded_url:
            print(f"画像アップロード成功: {uploaded_url}")
            messages_payload.append({
                "type": "image",
                "originalContentUrl": uploaded_url,
                "previewImageUrl": uploaded_url
            })

    payload = {
        "to": USER_ID,
        "messages": messages_payload
    }

    try:
        response = requests.post(url, headers=headers, json=payload)
        if response.status_code == 200:
            print("【テスト成功】LINEへの画像付き通知が完了しました！")
            return True
        else:
            print(f"LINE APIエラー: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"LINE通知処理に失敗しました: {e}")
        return False

# データの取得とチャート生成
df = yf.download("AUDJPY=X", period="5d", interval="15m")
if isinstance(df.columns, pd.MultiIndex):
    df.columns = df.columns.droplevel(1)

df['SMA_Short'] = df['Close'].rolling(window=5).mean()
df['SMA_Long'] = df['Close'].rolling(window=20).mean()

df_plot = df.tail(50)
plt.figure(figsize=(10, 5))
plt.plot(df_plot.index, df_plot['Close'], label='AUD/JPY Close', color='black', alpha=0.6)
plt.plot(df_plot.index, df_plot['SMA_Short'], label='5-min SMA', color='dodgerblue')
plt.plot(df_plot.index, df_plot['SMA_Long'], label='20-min SMA', color='orange')
plt.title('AUD/JPY 15m Speed Signal Chart (TEST)', fontsize=12)
plt.grid(True, linestyle='--', alpha=0.5)
plt.legend(loc='upper left')
plt.tight_layout()

chart_filename = 'trading_chart.png'
plt.savefig(chart_filename, dpi=150)
plt.close()

# ★ テストメッセージを強制的送信 ★
test_msg = "🧪 【動作テスト送信】\nLINE画像通知システムの正常稼働テストです。\nチャート画像が下部に添付されていれば大成功です！"
send_line_notification(test_msg, image_path=chart_filename)
