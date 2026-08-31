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
# 時間軸を基準に、5分足データに1時間足のSMA_Trendを安全に結合します
df = pd.merge_asof(df.sort_index(), df_1h[['SMA_Trend']].sort_index(), left_index=True, right_index=True, direction='backward')
df = df.rename(columns={'SMA_Trend': 'Trend_1h_aligned'})

# ==========================================
# 3. 15分足の移動平均線とRSI（14期間）を計算
# ==========================================
# 移動平均線（短期: 5本、長期: 20本）
df['SMA_Short'] = df['Close'].rolling(window=5).mean()
df['SMA_Long'] = df['Close'].rolling(window=20).mean()

# RSIの計算
delta = df['Close'].diff()
gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
rs = gain / loss
df['RSI'] = 100 - (100 / (1 + rs))

# ==========================================
# 4. 高確率ゾーンを厳選する売買サイン判定ロジック
# ==========================================
df['Signal'] = 0


# 【条件】短期＞長期 ＆ 1時間足より上 ＆ 「RSIが50以上65以下（天井掴みを回避）」
df.loc[(df['SMA_Short'] > df['SMA_Long']) & (df['Close'] > df['Trend_1h_aligned']) & (df['RSI'] >= 50) & (df['RSI'] <= 65), 'Signal'] = 1

# 【条件】短期＜長期 ＆ 1時間足より下 ＆ 「RSIが35以上50以下（底掴みを回避）」
df.loc[(df['SMA_Short'] < df['SMA_Long']) & (df['Close'] < df['Trend_1h_aligned']) & (df['RSI'] >= 35) & (df['RSI'] <= 50), 'Signal'] = -1

# 前の15分足からシグナルが変化した瞬間を特定
df['Action'] = df['Signal'].diff()

# ==========================================
# 5. グラフの保存
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

plt.title('AUD/JPY 15m Signals with 1h Trend & RSI Filter')
plt.legend()
plt.grid()
plt.savefig('trading_chart.png')
plt.close()

# ==========================================
# 6. 最新の判定結果とLINE送信
# ==========================================
latest_data = df.iloc[-1]
latest_date = df.index[-1].strftime('%Y-%m-%d %H:%M')
latest_close = latest_data['Close'].item() if hasattr(latest_data['Close'], 'item') else latest_data['Close']
latest_rsi = latest_data['RSI'].item() if hasattr(latest_data['RSI'], 'item') else latest_data['RSI']
latest_action_val = latest_data['Action'].item() if hasattr(latest_data['Action'], 'item') else latest_data['Action']

print("\n" + "="*40)
print(f"【データ基準時刻】: {latest_date}")
print(f"【最新為替レート】: {latest_close:.2f} 円 / 【RSI】: {latest_rsi:.1f}")
print("-"*40)

if latest_action_val != 0 and not pd.isna(latest_action_val):
    current_signal = latest_data['Signal'].item() if hasattr(latest_data['Signal'], 'item') else latest_data['Signal']
    
    if current_signal == 1:
        msg = f"🎯 【厳選サイン】買い（高確率ゾーン）\n⏰ 時刻: {latest_date}\n💰 レート: {latest_close:.2f}円 (RSI: {latest_rsi:.1f})\n上位足順張り ＆ 天井圏を避けた絶好の買いシグナルです！"
    elif current_signal == -1:
        msg = f"🎯 【厳選サイン】売り（高確率ゾーン）\n⏰ 時刻: {latest_date}\n💰 レート: {latest_close:.2f}円 (RSI: {latest_rsi:.1f})\n上位足順張り ＆ 底値圏を避けた絶好の売りシグナルです！"
    else:
        msg = f"⚠️ 【15分足】過熱感が基準を超えた、またはトレンド変化のためサインをクリアしました。\n⏰ 時刻: {latest_date}"

    print(f"信号変化（{latest_action_val}）を検知。LINEを送信します。")
    send_line_notification(msg)
else:
    print(f"直近のシグナルに変化はありません。")
    current_signal = latest_data['Signal'].item() if hasattr(latest_data['Signal'], 'item') else latest_data['Signal']
    if current_signal == 1:
        print(f"【現在の状態】高確率・買いゾーン継続中 (RSI: {latest_rsi:.1f})")
    elif current_signal == -1:
        print(f"【現在の状態】高確率・売りゾーン継続中 (RSI: {latest_rsi:.1f})")
    else:
        print(f"【現在の状態】様子見ゾーン（揉み合い、または過熱圏内）(RSI: {latest_rsi:.1f})")

print("="*40)
