from linebot import LineBotApi
from linebot.models import TextSendMessage
import pandas as pd
import yfinance as yf
import matplotlib.pyplot as plt

def send_line_notification(message):    
    # トークンとユーザーID
    CHANNEL_ACCESS_TOKEN = 'rqISRcqCU7mstgaP1rxVVTEaVgmbWYEbTqR4HZPDqM7HuHk78/Nj9Okrq/5yhj0xqrn36a0fEcgAh/fSJdKFdq8sdDUf6aqcxCeJvodw16XlcwWqMycpV4Y37N7mru2cSFBSbkgBrtO0BKqTNUiMNQdB04t89/1O/w1cDnyilFU='
    USER_ID = 'U0e89974679349b0e3875e081aaf5f806'

    try:
        line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
        line_bot_api.push_message(USER_ID, messages=TextSendMessage(text=message))
    except Exception as e:
        print(f"LINE通知に失敗しました: {e}")

# ==========================================
# 1. 15分足データと、フィルター用の1時間足データを取得
# ==========================================
print("為替データをダウンロード中...")
# 15分足は過去1か月分（1mo）を取得
df = yf.download("AUDJPY=X", period="1mo", interval="15m")
# 上位足（1時間足）は過去2か月分を取得
df_1h = yf.download("AUDJPY=X", period="2mo", interval="1h")

# ==========================================
# 2. 上位足（1時間足）のトレンド判定（20本移動平均線）
# ==========================================
df_1h['SMA_Trend'] = df_1h['Close'].rolling(window=20).mean()
# 15分足のデータに、その時刻の1時間足のトレンド情報を結合（マージ）する
df_1h_resampled = df_1h[['SMA_Trend']].reindex(df.index, method='ffill')
df['Trend_1h'] = df_1h_resampled['SMA_Trend']

# ==========================================
# 3. 15分足の移動平均線を計算（短期: 5本、長期: 20本）
# ==========================================
df['SMA_Short'] = df['Close'].rolling(window=5).mean()
df['SMA_Long'] = df['Close'].rolling(window=20).mean()

# ==========================================
# 4. チャンスを厳選する売買サイン判定ロジック
# ==========================================
df['Signal'] = 0

# 【条件変更】短期＞長期 かつ 「今の価格が1時間足の移動平均線より上（上昇トレンド）」のときだけ買いゾーン(1)
df.loc[(df['SMA_Short'] > df['SMA_Long']) & (df['Close'] > df['Trend_1h']), 'Signal'] = 1

# 【条件変更】短期＜長期 かつ 「今の価格が1時間足の移動平均線より下（下落トレンド）」のときだけ売りゾーン(-1に変えることで判定を明確化)
df.loc[(df['SMA_Short'] < df['SMA_Long']) & (df['Close'] < df['Trend_1h']), 'Signal'] = -1

# 前の15分足からシグナルが変化した瞬間を特定
df['Action'] = df['Signal'].diff()

# ==========================================
# 5. グラフの保存（クラウド環境エラー防止のため画面表示ではなく画像保存に変更）
# ==========================================
plt.figure(figsize=(12, 6))
plt.plot(df.index, df['Close'], label='AUD/JPY Close', color='black', alpha=0.5)
plt.plot(df.index, df['SMA_Short'], label='5-min SMA (Short)', color='blue')
plt.plot(df.index, df['SMA_Long'], label='20-min SMA (Long)', color='orange')

buy_signals = df[df['Action'] == 1]
if not buy_signals.empty:
    plt.scatter(buy_signals.index, buy_signals['Close'], marker='^', color='green', s=100, label='BUY Signal')

sell_signals = df[df['Action'] == -1]
if not sell_signals.empty:
    plt.scatter(sell_signals.index, sell_signals['Close'], marker='v', color='red', s=100, label='SELL Signal')

plt.title('AUD/JPY 15m Trading Signals with 1h Trend Filter')
plt.legend()
plt.grid()
plt.savefig('trading_chart.png') # グラフを画像として保存
plt.close()

# ==========================================
# 6. 最新の判定結果とLINE送信
# ==========================================
latest_data = df.iloc[-1]
previous_data = df.iloc[-2]

latest_date = df.index[-1].strftime('%Y-%m-%d %H:%M')
latest_close = latest_data['Close'].item() if hasattr(latest_data['Close'], 'item') else latest_data['Close']
latest_action_val = latest_data['Action'].item() if hasattr(latest_data['Action'], 'item') else latest_data['Action']

print("\n" + "="*40)
print(f"【データ基準時刻】: {latest_date}")
print(f"【最新為替レート】: {latest_close:.2f} 円")
print("-"*40)

# シグナルが「新しく発生した瞬間」を検知
if latest_action_val != 0 and not pd.isna(latest_action_val):
    current_signal = latest_data['Signal'].item() if hasattr(latest_data['Signal'], 'item') else latest_data['Signal']
    
    if current_signal == 1:
        msg = f"🎉 【15分足・最新サイン】買い（トレンド順張り）\n🚨時刻: {latest_date}\nレート: {latest_close:.2f}円\n上位足が上昇トレンド中のゴールデンクロスを検知しました！"
    elif current_signal == -1:
        msg = f"🚨 【15分足・最新サイン】売り（トレンド順張り）\n🚨時刻: {latest_date}\nレート: {latest_close:.2f}円\n上位足が下落トレンド中のデッドクロスを検知しました！"
    else:
        msg = f" ⚠️ 【15分足】サインがクリアされました（トレンド転換、またはレンジ入り）。\n時刻: {latest_date}"

    print(f"信号変化（{latest_action_val}）を検知しました。LINEを送信します。")
    send_line_notification(msg)
else:
    print(f"直近の15分足シグナルに変化はありません。({latest_date})")
    current_signal = latest_data['Signal'].item() if hasattr(latest_data['Signal'], 'item') else latest_data['Signal']
    if current_signal == 1:
        print("【現在の状態】安全な買いゾーン（上位足・下位足ともに上昇）")
    elif current_signal == -1:
        print("【現在の状態】安全な売りゾーン（上位足・下位足ともに下落）")
    else:
        print("【現在の状態】様子見ゾーン（トレンドと逆方向、または揉み合い中）")

print("="*40)
