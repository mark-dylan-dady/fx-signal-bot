from linebot import LineBotApi
from linebot.models import TextSendMessage

def send_line_notification(message):	
# 先ほど発行した長いトークンをここに貼り付けます
    CHANNEL_ACCESS_TOKEN = 'rqISRcqCU7mstgaP1rxVVTEaVgmbWYEbTqR4HZPDqM7HuHk78/Nj9Okrq/5yhj0xqrn36a0fEcgAh/fSJdKFdq8sdDUf6aqcxCeJvodw16XlcwWqMycpV4Y37N7mru2cSFBSbkgBrtO0BKqTNUiMNQdB04t89/1O/w1cDnyilFU='

# Uから始まるあなたのユーザーIDをここに貼り付けます
    USER_ID = 'U0e89974679349b0e3875e081aaf5f806'

    try:
        line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
        line_bot_api.push_message(USER_ID, messages=TextSendMessage(text=message))
    except Exception as e:
        print(f"LINE通知に失敗しました: {e}")

import pandas as pd
import yfinance as yf
import matplotlib.pyplot as plt

# 1. 豪ドル/円（AUD/JPY）の過去データを取得
print("為替データをダウンロード中...")
df = yf.download("AUDJPY=X", start="2025-01-01", interval="1d")

# 2. 移動平均線を計算（短期: 5日、長期: 20日）
df['SMA_Short'] = df['Close'].rolling(window=5).mean()
df['SMA_Long'] = df['Close'].rolling(window=20).mean()

# 3. 売買サイン（タイミング）の判定ロジック
df['Signal'] = 0
# 短期が長期を上回ったら「1 (買いシグナル)」
df.loc[df['SMA_Short'] > df['SMA_Long'], 'Signal'] = 1

# 4. 前日からシグナルが変化した瞬間（交差したタイミング）を特定
df['Action'] = df['Signal'].diff()

# 5. グラフで結果を表示する
plt.figure(figsize=(12, 6))
plt.plot(df.index, df['Close'], label='AUD/JPY Close', color='black', alpha=0.5)
plt.plot(df.index, df['SMA_Short'], label='5-day SMA (Short)', color='blue')
plt.plot(df.index, df['SMA_Long'], label='20-day SMA (Long)', color='orange')

# 買いタイミングを「緑の▲」でプロット
buy_signals = df[df['Action'] == 1]
plt.scatter(buy_signals.index, buy_signals['Close'], marker='^', color='green', s=100, label='BUY Signal')

# 売りタイミングを「赤の▼」でプロット
sell_signals = df[df['Action'] == -1]
plt.scatter(sell_signals.index, sell_signals['Close'], marker='v', color='red', s=100, label='SELL Signal')

plt.title('AUD/JPY Trading Signals (Golden Cross / Death Cross)')
plt.legend()
plt.grid()
plt.show()

# --- ここから追加 ---
# 最新（一番最後）のデータ行を取得
latest_data = df.iloc[-1]
latest_date = df.index[-1].strftime('%Y-%m-%d')
latest_close = latest_data['Close'].item()

print("\n" + "="*40)
print(f"【データ基準日】: {latest_date}")
print(f"【最新為替レート】: {latest_close:.2f} 円")
print(f" 短期移動平均線(5日): {latest_data['SMA_Short'].item():.2f} 円")
print(f" 長期移動平均線(20日): {latest_data['SMA_Long'].item():.2f} 円")
print("-"*40)


# 最新（今日）とその1つ前（昨日）のデータを取得
latest_data = df.iloc[-1]
previous_data = df.iloc[-2]

latest_date = df.index[-1].strftime('%Y-%m-%d')
latest_action = latest_data['Action']

print(f"\n" + "="*40)
print(f"【判定結果】")

# 条件：今日のActionが1または-1で、かつ昨日のActionと異なる場合（＝今日切り替わった瞬間）

# .item() を使って、確実に数値（1, -1, 0）として取得する
latest_action_val = latest_action.item() if hasattr(latest_action, 'item') else latest_action
previous_action_val = previous_data['Action'].item() if hasattr(previous_data['Action'], 'item') else previous_data['Action']

# 数値同士で比較を行う
if latest_action_val in [1, -1] and latest_action_val != previous_action_val:

    if latest_action_val == 1:
        msg = f"🎉 【最新サイン】買い（GOLDEN CROSS）\n本日 {latest_date} に買いシグナルが発生しました！"
    else:
        msg = f"🚨 【最新サイン】売り（DEATH CROSS）\n本日 {latest_date} に売りシグナルが発生しました！"

    print(f"信号変化を検知しました。LINEを送信します。")
    send_line_notification(msg)

else:
# シグナルが変わっていない場合のログ表示
    print(f"本日のシグナルに変化はありません。({latest_date})")
# ここも安全のために .item() を使うか、そのまま判定
    current_signal = latest_data['Signal'].item() if hasattr(latest_data['Signal'], 'item') else latest_data['Signal']
    if current_signal == 1:
        print("【現在の状態】買いゾーン（短期が長期の上を推移中）")
    else:
        print("【現在の状態】売りゾーン（短期が長期の下を推移中）")


print("="*40)

