from linebot import LineBotApi
from linebot.models import TextSendMessage
import pandas as pd
import yfinance as yf
import matplotlib.pyplot as plt

def send_line_notification(message):   
    # トークンとユーザーID（ご自身のものに差し替えてください）
    CHANNEL_ACCESS_TOKEN = 'rqISRcqCU7mstgaP1rxVVTEaVgmbWYEbTqR4HZPDqM7HuHk78/Nj9Okrq/5yhj0xqrn36a0fEcgAh/fSJdKFdq8sdDUf6aqcxCeJvodw16XlcwWqMycpV4Y37N7mru2cSFBSbkgBrtO0BKqTNUiMNQdB04t89/1O/w1cDnyilFU='
    USER_ID = 'U0e89974679349b0e3875e081aaf5f806'

    try:
        line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
        line_bot_api.push_message(USER_ID, messages=TextSendMessage(text=message))
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

# 15分足データに1時間足のSMA_Trendを安全に結合
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

# 時間フィルター条件（日本時間 6:00 〜 8:59 はスプレッド拡大回避のため取引対象外にする）
is_market_active = ~((df_jst.hour >= 6) & (df_jst.hour <= 8))

# 【安全な買いの条件】
# ① 短期線が長期線を上抜けている
# ② 価格が1時間足の移動平均線より上にある（長期トレンドが円安方向）
# ③ RSIが53以上65以下（50を明確に超えて上昇の勢いを確認、かつ天井圏の手前）
buy_cond = (
    (df['SMA_Short'] > df['SMA_Long']) &
    (df['Close'] > df['Trend_1h_aligned']) &
    (df['RSI'] >= 53) &
    (df['RSI'] <= 65) &
    is_market_active
)
df.loc[buy_cond, 'Signal'] = 1

# 【安全な売りの条件】
# ① 短期線が長期線を下抜けている
# ② 価格が1時間足の移動平均線より下にある（長期トレンドが円高方向）
# ③ RSIが35以上48以下（底値掴みを徹底回避するため、上限を48に引き下げ）
sell_cond = (
    (df['SMA_Short'] < df['SMA_Long']) &
    (df['Close'] < df['Trend_1h_aligned']) &
    (df['RSI'] >= 35) &
    (df['RSI'] <= 48) &
    is_market_active
)
df.loc[sell_cond, 'Signal'] = -1

# 前の15分足からシグナルが変化した瞬間を特定
df['Action'] = df['Signal'].diff()

# ==========================================
# 5. 厳密な「確定足（1本前）」の判定処理
# ==========================================
# yfinanceの一番最後の行[-1]は未確定なため、値が固定された「1本前の足[-2]」を基準にします。
target_data = df.iloc[-2]
target_index_jst = df_jst[-2]

latest_date = target_index_jst.strftime('%Y-%m-%d %H:%M')
latest_close = target_data['Close'].item() if hasattr(target_data['Close'], 'item') else target_data['Close']
latest_rsi = target_data['RSI'].item() if hasattr(target_data['RSI'], 'item') else target_data['RSI']
latest_action_val = target_data['Action'].item() if hasattr(target_data['Action'], 'item') else target_data['Action']

# ==========================================
# 6. 最新の判定結果とLINE送信（決済目安の追加）
# ==========================================
print("\n" + "="*40)
print(f"【確定データ基準時刻（JST）】: {latest_date}")
print(f"【最新確定レート】: {latest_close:.2f} 円 / 【RSI】: {latest_rsi:.1f}")
print("-"*40)

# 目安となる利確・損切り幅（20pips = 0.20円）
PIPS_WIDTH = 0.20

if latest_action_val != 0 and not pd.isna(latest_action_val):
    current_signal = target_data['Signal'].item() if hasattr(target_data['Signal'], 'item') else target_data['Signal']

    if current_signal == 1:
        tp_price = latest_close + PIPS_WIDTH
        sl_price = latest_close - PIPS_WIDTH
        msg = (f"🎯 【厳選サイン】買い（高確率ゾーン）\n"
               f"⏰ 時刻: {latest_date} (日本時間)\n"
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
               f"⏰ 時刻: {latest_date} (日本時間)\n"
               f"💰 レート: {latest_close:.2f}円 (RSI: {latest_rsi:.1f})\n"
               f"ーーー\n"
               f"📈 利確目安(TP): {tp_price:.2f}円\n"
               f"📉 損切目安(SL): {sl_price:.2f}円\n"
               f"ーーー\n"
               f"上位足順張り ＆ 底値圏を避けた絶好の売りシグナルです！")
    else:
        msg = f"⚠️ 【15分足】過熱感が基準を超えた、またはトレンド変化のためサインをクリアしました。\n⏰ 時刻: {latest_date} (日本時間)"

    print(f"信号変化（{latest_action_val}）を検知。LINEを送信します。")
    send_line_notification(msg)
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
