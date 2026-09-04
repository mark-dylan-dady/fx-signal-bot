from linebot import LineBotApi
from linebot.models import TextSendMessage, ImageSendMessage
import pandas as pd
import yfinance as yf
import matplotlib.pyplot as plt

def send_line_notification(message, image_url=None):
    # LINEのトークンとユーザーID
    CHANNEL_ACCESS_TOKEN = 'rqISRcqCU7mstgaP1rxVVTEaVgmbWYEbTqR4HZPDqM7HuHk78/Nj9Okrq/5yhj0xqrn36a0fEcgAh/fSJdKFdq8sdDUf6aqcxCeJvodw16XlcwWqMycpV4Y37N7mru2cSFBSbkgBrtO0BKqTNUiMNQdB04t89/1O/w1cDnyilFU='
    USER_ID = 'U0e89974679349b0e3875e081aaf5f806'

    try:
        line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)

        # 1. まず判定テキストメッセージを送信
        line_bot_api.push_message(USER_ID, messages=TextSendMessage(text=message))

        # 2. 画像URLが指定されている場合は、続けて最新チャート画像を送信
        if image_url:
            image_message = ImageSendMessage(
              original_content_url=image_url,
              preview_image_url=image_url
            )
            line_bot_api.push_message(USER_ID, messages=image_message)
            print("LINEへの最新チャート画像添付に成功しました。")

    except Exception as e:
        print(f"LINE通知に失敗しました: {e}")

# =========================================
# 1. データの取得（15分足と1時間足）
# =========================================
print("為替データをダウンロード中...")
df = yf.download("AUDJPY=X", period="5d", interval="15m")
df_1h = yf.download("AUDJPY=X", period="7d", interval="1h")

# マルチインデックスの平坦化
if isinstance(df.columns, pd.MultiIndex):
df.columns = df.columns.droplevel(1)
if isinstance(df_1h.columns, pd.MultiIndex):
df_1h.columns = df_1h.columns.droplevel(1)

# =========================================
# 2. 上位足（1時間足）のトレンド判定（20本移動平均線）
# =========================================
df_1h['SMA_Trend'] = df_1h['Close'].rolling(window=20).mean()

# 15分足データに1時間足のSMA_Trendを結合
df = pd.merge_asof(df.sort_index(), df_1h[['SMA_Trend']].sort_index(), left_index=True, right_index=True)
df = df.rename(columns={'SMA_Trend': 'Trend_1h_aligned'})

# =========================================
# 3. 15分足のテクニカル指標計算
# =========================================
df['SMA_Short'] = df['Close'].rolling(window=5).mean()
df['SMA_Long'] = df['Close'].rolling(window=20).mean()

# RSIの計算
delta = df['Close'].diff()
gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
rs = gain / loss
df['RSI'] = 100 - (100 / (1 + rs))

# =========================================
# 4. 【円安特化・安全重視】売買サイン判定ロジック
# =========================================
df['Signal'] = 0

# 日本時間（JST）への変換処理
if df.index.tz is None:
df_jst = df.index.tz_localize('UTC').tz_convert('Asia/Tokyo')
else:
df_jst = df.index.tz_convert('Asia/Tokyo')

# 時間フィルター条件（日本時間 6:00 〜 8:59 は取引対象外）
is_market_active = ~((df_jst.hour >= 6) & (df_jst.hour <= 8))

# 【安全な買いの条件】（RSIを53に引き上げ、だましの上昇を完全スルー）
buy_cond = (df['SMA_Short'] > df['SMA_Long']) & (df['Close'] > df['Trend_1h_aligned']) & (df['RSI'] >= 53) & (df['RSI'] <= 65) & is_market_active
df.loc[buy_cond, 'Signal'] = 1

# 【安全な売りの条件】
sell_cond = (df['SMA_Short'] < df['SMA_Long']) & (df['Close'] < df['Trend_1h_aligned']) & (df['RSI'] >= 35) & (df['RSI'] <= 48) & is_market_active
df.loc[sell_cond, 'Signal'] = -1

# 前の15分足からシグナルが変化した瞬間を特定
df['Action'] = df['Signal'].diff()

# ==========================================
# 5. チャート画像の生成と保存（直近50本分を拡大して見やすく描写）
# ==========================================
df_plot = df.tail(50)

plt.figure(figsize=(10, 5))
plt.plot(df_plot.index, df_plot['Close'], label='AUD/JPY Close', color='black', alpha=0.6, linewidth=1.5)
plt.plot(df_plot.index, df_plot['SMA_Short'], label='5-min SMA', color='dodgerblue', linewidth=1.2)
plt.plot(df_plot.index, df_plot['SMA_Long'], label='20-min SMA', color='orange', linewidth=1.2)

# シグナルのプロット
buy_signals = df_plot[df_plot['Action'] == 1]
if not buy_signals.empty:
plt.scatter(buy_signals.index, buy_signals['Close'], marker='^', color='limegreen', s=120, label='BUY', zorder=5)

sell_signals = df_plot[df_plot['Action'] == -1]
if not sell_signals.empty:
plt.scatter(sell_signals.index, sell_signals['Close'], marker='v', color='crimson', s=120, label='SELL', zorder=5)

plt.title('AUD/JPY 15m Speed Signal Chart', fontsize=12)
plt.grid(True, linestyle='--', alpha=0.5)
plt.legend(loc='upper left')
plt.xticks(rotation=15)
plt.tight_layout()

chart_filename = 'trading_chart.png'
plt.savefig(chart_filename, dpi=150)
plt.close()

# ==========================================
# 6. 【スピード最速化】リアルタイム（最新の足）の判定処理
# ==========================================
# タイムラグを無くすため、今動いているリアルタイムの末尾の足[-1]を基準にします
target_data = df.iloc[-1]
target_index_jst = df_jst[-1]

latest_date = target_index_jst.strftime('%Y-%m-%d %H:%M')
latest_close = target_data['Close'].item() if hasattr(target_data['Close'], 'item') else target_data['Close']
latest_rsi = target_data['RSI'].item() if hasattr(target_data['RSI'], 'item') else target_data['RSI']
latest_action_val = target_data['Action'].item() if hasattr(target_data['Action'], 'item') else target_data['Action']

# ==========================================
# 7. 最新の判定結果とLINE送信処理
# ==========================================
print("\n" + "="*40)
print(f"【最速リアルタイムデータ基準時刻（JST）】: {latest_date}")
print(f"【最新為替レート】: {latest_close:.2f} 円 / 【RSI】: {latest_rsi:.1f}")
print("-"*40)

# ★★★ ご自身の環境に合わせて必ず書き換えてください ★★★
GITHUB_USER = 'mark-dylan-daddy'
GITHUB_REPO = 'fx-signal-bot'
IMAGE_PUBLIC_URL = f"https://githubusercontent.com{GITHUB_USER}/{GITHUB_REPO}/main/{chart_filename}"

PIPS_WIDTH = 0.20

if latest_action_val != 0 and not pd.isna(latest_action_val):
current_signal = target_data['Signal'].item() if hasattr(target_data['Signal'], 'item') else target_data['Signal']

if current_signal == 1:
tp_price = latest_close + PIPS_WIDTH
sl_price = latest_close - PIPS_WIDTH
msg = (f"🎯 【厳選サイン】買い（高確率ゾーン）\n"
f"⏰ 時刻: {latest_date} (日本時間最速)\n"
f"💰 レート: {latest_close:.2f}円 (RSI: {latest_rsi:.1f})\n"
f"ーーー\n"
f"📈 利確目安(TP): {tp_price:.2f}円\n"
f"📉 損切目安(SL): {sl_price:.2f}円\n"
f"ーーー\n"
f"上位足順張り ＆ 天井圏を避けた絶好の買いシグナルです！")

elif current_signal == -1:
tp_price = latest_close - PIPS_WIDTH
sl_price = latest_close + PIPS_WIDTH
msg = (f"🎯 【厳選サイン】売り（高確率ゾーン）\n"
f"⏰ 時刻: {latest_date} (日本時間最速)\n"
f"💰 レート: {latest_close:.2f}円 (RSI: {latest_rsi:.1f})\n"
f"ーーー\n"
f"📈 利確目安(TP): {tp_price:.2f}円\n"
f"📉 損切目安(SL): {sl_price:.2f}円\n"
f"ーーー\n"
f"上位足順張り ＆ 底値圏を避けた絶好の売りシグナルです！")
else:
msg = f"⚠️ 【15分足】過熱感が基準を超えた、またはトレンド変化のためサインをクリアしました。\n⏰ 時刻: {latest_date} (日本時間最速)"

print(f"信号変化（{latest_action_val}）を最速検知。画像添付でLINE送信します。")
send_line_notification(msg, image_url=IMAGE_PUBLIC_URL)
else:
print(f"直近のシグナルに変化はありません。")
current_signal = target_data['Signal'].item() if hasattr(target_data['Signal'], 'item') else target_data['Signal']
if current_signal == 1:
print(f"【現在の状態】高確率・買いゾーン継続中 (RSI: {latest_rsi:.1f})")
elif current_signal == -1:
print(f"【現在の状態】高確率・売りゾーン継続中 (RSI: {latest_rsi:.1f})")
else:
print(f"【現在の状態】様子見ゾーン（揉み合い、または過熱圏内）(RSI: {latest_rsi:.1f})")

print("="*40)
