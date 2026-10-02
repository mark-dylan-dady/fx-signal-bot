import os
import pandas as pd
import requests
import yfinance as yf
from dotenv import load_dotenv

load_dotenv()

CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
USER_ID = os.getenv("LINE_USER_ID")
IS_MANUAL_RUN = os.getenv("IS_MANUAL_RUN", "false").lower() == "true"

CSV_FILE = "signals_history.csv"

# ==========================================
# 設定（ここだけ変えれば、本番もバックテストも同じ条件になります）
# ==========================================
TP_ATR_MULT = 1.3    # 利確幅 = ATR × この倍率
SL_ATR_MULT = 1.3    # 損切幅 = ATR × この倍率
MIN_TP_WIDTH = 0.05  # 利確幅の最低値（円）＝5pips
MIN_SL_WIDTH = 0.08  # 損切幅の最低値（円）＝8pips
MAX_BARS = 48        # エントリー後、何本(=4時間)まで様子を見るか
COST_YEN = 0.005     # 1回の取引コスト(スプレッド)の想定：0.5pips。業者に合わせて変更
MIN_SLOPE = 0.03   # 1時間でこれ以上動いている時だけ「トレンドあり」と判定

def send_line_notification(message):
    if not CHANNEL_ACCESS_TOKEN or not USER_ID:
        print("エラー: LINEアクセストークンまたはユーザーIDが未設定です。")
        return False

    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Authorization": f"Bearer {CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {"to": USER_ID, "messages": [{"type": "text", "text": message}]}

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


# ==========================================
# 共通の部品（本番とバックテストで同じものを使う）
# ==========================================
def calc_tp_sl(entry, atr, sig_type):
    """【修正】TP/SLの計算を1か所にまとめました。
    本番もバックテストもこの関数を使うので、条件がズレません。"""
    tp_width = max(atr * TP_ATR_MULT, MIN_TP_WIDTH)
    sl_width = max(atr * SL_ATR_MULT, MIN_SL_WIDTH)
    if sig_type == "BUY":
        return entry + tp_width, entry - sl_width, tp_width, sl_width
    return entry - tp_width, entry + sl_width, tp_width, sl_width


def judge_trade(sig_type, entry, tp, sl, future_df):
    """エントリー後の値動き(future_df)を見て、結果と損益(円)を返す。
    まだ決着がついていなければ (None, None) を返す。

    【修正】
    ・同じ足でTPとSLの両方に触れた場合は「負け」にする（先に判定）。
      どちらが先か分からないので、厳しめに見るのが安全です。
    ・MAX_BARS本たっても決着しなかった場合は「TIMEOUT」として、
      その時点の価格で損益を計算します（今までは数えられていませんでした）。
    ・損益からは取引コスト(COST_YEN)を引いています。
    """
    for _, f_row in future_df.iterrows():
        high = float(f_row["High"])
        low = float(f_row["Low"])

        if sig_type == "BUY":
            hit_tp = high >= tp
            hit_sl = low <= sl
        else:
            hit_tp = low <= tp
            hit_sl = high >= sl

        if hit_sl:  # 同時に触れたときも負け扱い
            return "LOSE", -abs(entry - sl) - COST_YEN
        if hit_tp:
            return "WIN", abs(tp - entry) - COST_YEN

    if len(future_df) >= MAX_BARS:
        last_close = float(future_df["Close"].iloc[-1])
        pnl = (last_close - entry) if sig_type == "BUY" else (entry - last_close)
        return "TIMEOUT", pnl - COST_YEN

    return None, None  # まだ結果が出ていない


def summarize(result_df):
    """勝率だけでなく『1回あたりの平均損益(pips)』も計算する。"""
    done = result_df[result_df["Result"].isin(["WIN", "LOSE", "TIMEOUT"])]
    total = len(done)
    wins = int((done["Result"] == "WIN").sum())
    loses = int((done["Result"] == "LOSE").sum())
    timeouts = int((done["Result"] == "TIMEOUT").sum())
    pnl = pd.to_numeric(done["PnL"], errors="coerce").dropna()
    return {
        "total": total,
        "wins": wins,
        "loses": loses,
        "timeouts": timeouts,
        "win_rate": (wins / total * 100) if total > 0 else 0.0,
        "avg_pips": (pnl.mean() * 100) if len(pnl) > 0 else 0.0,
        "total_pips": (pnl.sum() * 100) if len(pnl) > 0 else 0.0,
    }


# 1. データの取得（5分足 & 1時間足）
df = yf.download("EURJPY=X", period="60d", interval="5m")
df_1h = yf.download("AUDJPY=X", period="730d", interval="1h")

if isinstance(df.columns, pd.MultiIndex):
    df.columns = df.columns.droplevel(1)
if isinstance(df_1h.columns, pd.MultiIndex):
    df_1h.columns = df_1h.columns.droplevel(1)

# 2. 上位足（1時間足）のトレンド判定
df_1h["SMA_Trend"] = df_1h["Close"].rolling(window=20).mean()
df_1h["SMA_Slope"] = df_1h["SMA_Trend"].diff()

# 【修正】1時間足の値を1本ずらす。
# ずらさないと「まだ終わっていない1時間の終値」まで使ってしまい、
# バックテストで未来の情報を先取りして成績が良く見えてしまいます。
df_1h[["SMA_Trend", "SMA_Slope"]] = df_1h[["SMA_Trend", "SMA_Slope"]].shift(1)

df = pd.merge_asof(
    df.sort_index(),
    df_1h[["SMA_Trend", "SMA_Slope"]].sort_index(),
    left_index=True,
    right_index=True,
)

# 3. 5分足テクニカル指標
df["SMA_Short"] = df["Close"].rolling(window=5).mean()
df["SMA_Long"] = df["Close"].rolling(window=20).mean()

delta = df["Close"].diff()
gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
rs = gain / loss
df["RSI"] = 100 - (100 / (1 + rs))

high_low = df["High"] - df["Low"]
high_close = (df["High"] - df["Close"].shift()).abs()
low_close = (df["Low"] - df["Close"].shift()).abs()
tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
df["ATR"] = tr.rolling(window=14).mean()

# 直近ブレイクアウト判定用（過去3本の高値/安値）
df["High_Max3"] = df["High"].shift(1).rolling(window=3).max()
df["Low_Min3"] = df["Low"].shift(1).rolling(window=3).min()

# 4. サイン判定
df["Signal"] = 0
if df.index.tz is None:
    df_jst = df.index.tz_localize("UTC").tz_convert("Asia/Tokyo")
else:
    df_jst = df.index.tz_convert("Asia/Tokyo")

# 21時以降、または午前6時未満の「動く時間帯」だけに限定
is_market_active = (df_jst.hour >= 21) | (df_jst.hour < 6)

# 買い条件
buy_cond = (
    (df["SMA_Short"] > df["SMA_Long"])
    & (df["Close"] > df["SMA_Trend"])
    & (df["SMA_Slope"] > MIN_SLOPE)
    & (df["RSI"] >= 55)
    & (df["RSI"] <= 65)
    & (df["Close"] > df["High_Max3"])  # 直近3本の高値を更新
    & is_market_active
)
df.loc[buy_cond, "Signal"] = 1

# 売り条件
sell_cond = (
    (df["SMA_Short"] < df["SMA_Long"])
    & (df["Close"] < df["SMA_Trend"])
    & (df["SMA_Slope"] < -MIN_SLOPE)
    & (df["RSI"] >= 35)
    & (df["RSI"] <= 45)
    & (df["Close"] < df["Low_Min3"])  # 直近3本の安値を更新
    & is_market_active
)
df.loc[sell_cond, "Signal"] = -1

df["Action"] = df["Signal"].diff()


# 5. シグナル結果の検証機能
def verify_past_signals(history_df, market_df):
    updated = False

    m_df = market_df.copy()
    if m_df.index.tz is not None:
        m_df.index = m_df.index.tz_convert("Asia/Tokyo").tz_localize(None)

    for idx, row in history_df.iterrows():
        if row["Result"] != "Pending":
            continue

        sig_time = pd.to_datetime(row["Timestamp"])
        if sig_time.tzinfo is not None:
            sig_time = sig_time.tz_convert("Asia/Tokyo").tz_localize(None)

        sig_type = row["Type"]
        entry = float(row["Entry"])
        tp = float(row["TP"])
        sl = float(row["SL"])

        future_data = m_df[m_df.index > sig_time].head(MAX_BARS)
        if future_data.empty:
            continue

        result, pnl = judge_trade(sig_type, entry, tp, sl, future_data)
        if result is not None:
            history_df.loc[idx, "Result"] = result
            history_df.loc[idx, "PnL"] = pnl
            updated = True

    return history_df, updated


# CSVの読み込みまたは新規作成
if os.path.exists(CSV_FILE):
    history_df = pd.read_csv(CSV_FILE)
else:
    history_df = pd.DataFrame(
        columns=["Timestamp", "Type", "Entry", "TP", "SL", "RSI", "ATR", "Result", "PnL"]
    )

# 【修正】古いCSVには損益(PnL)の列がないので追加し、過去のWIN/LOSEも計算して埋める
if "PnL" not in history_df.columns:
    history_df["PnL"] = float("nan")
for col in ["Entry", "TP", "SL", "PnL"]:
    history_df[col] = pd.to_numeric(history_df[col], errors="coerce")

win_missing = (history_df["Result"] == "WIN") & history_df["PnL"].isna()
lose_missing = (history_df["Result"] == "LOSE") & history_df["PnL"].isna()
history_df.loc[win_missing, "PnL"] = (
    (history_df["TP"] - history_df["Entry"]).abs() - COST_YEN
)
history_df.loc[lose_missing, "PnL"] = (
    -(history_df["SL"] - history_df["Entry"]).abs() - COST_YEN
)

# 過去シグナルの結果更新
history_df, was_updated = verify_past_signals(history_df, df)

# 勝率・平均損益の計算
stats = summarize(history_df)
win_rate = stats["win_rate"]
wins = stats["wins"]
total_finished = stats["total"]
avg_pips = stats["avg_pips"]

# 6. 直近データの判定＆記録
target_data = df.iloc[-2]
target_index_jst = df_jst[-2]

latest_date = target_index_jst.strftime("%Y-%m-%d %H:%M")
latest_close = float(target_data["Close"])
latest_rsi = float(target_data["RSI"])
latest_atr = float(target_data["ATR"])
latest_action_val = float(target_data["Action"])
current_signal = int(target_data["Signal"])

signal_sent = False

is_buy = current_signal == 1 and latest_action_val > 0
is_sell = current_signal == -1 and latest_action_val < 0

# 【修正】買いと売りで同じ処理が2回書かれていたので、1つにまとめました
if is_buy or is_sell:
    sig_type = "BUY" if is_buy else "SELL"
    tp_price, sl_price, tp_width, sl_width = calc_tp_sl(latest_close, latest_atr, sig_type)

    new_row = pd.DataFrame(
        [
            {
                "Timestamp": target_index_jst.strftime("%Y-%m-%d %H:%M:%S"),
                "Type": sig_type,
                "Entry": latest_close,
                "TP": tp_price,
                "SL": sl_price,
                "RSI": latest_rsi,
                "ATR": latest_atr,
                "Result": "Pending",
                "PnL": float("nan"),
            }
        ]
    )
    history_df = pd.concat([history_df, new_row], ignore_index=True)

    label = "買い" if is_buy else "売り"
    sign = "+" if is_buy else "-"      # 利確方向の符号
    sign_sl = "-" if is_buy else "+"   # 損切方向の符号
    msg = (
        f"🎯 【5分足】{label}シグナル発信\n"
        f"⏰ 時刻: {latest_date}\n"
        f"💰 レート: {latest_close:.2f}円\n"
        f"──────────────\n"
        f"📈 利確(TP)目安: {tp_price:.2f}円 ({sign}{tp_width:.2f})\n"
        f"📉 損切(SL)目安: {sl_price:.2f}円 ({sign_sl}{sl_width:.2f})\n"
        f"──────────────\n"
        f"📊 蓄積データ勝率: {win_rate:.1f}% ({wins}/{total_finished}勝)\n"
        f"💹 1回あたり平均: {avg_pips:+.1f}pips"
    )
    send_line_notification(msg)
    signal_sent = True

# 履歴を書き込み保存
history_df.to_csv(CSV_FILE, index=False)

if IS_MANUAL_RUN and not signal_sent:
    test_msg = (
        f"🔧 【手動テスト】学習・検証型モデル動作確認\n"
        f"⏰ 時刻: {latest_date}\n"
        f"💰 レート: {latest_close:.2f}円 / RSI: {latest_rsi:.1f}\n"
        f"📊 過去シグナル検証勝率: {win_rate:.1f}% ({wins}/{total_finished}勝)\n"
        f"💹 1回あたり平均: {avg_pips:+.1f}pips\n"
        f"💡 システムは正常稼働中です。"
    )
    send_line_notification(test_msg)
    print("手動実行テスト通知を送信しました。")
elif not signal_sent:
    print(f"新規シグナルなし (現在の過去検証勝率: {win_rate:.1f}%)")


# ==========================================
# バックテスト実行関数（過去データでの検証）
# ==========================================
def run_backtest(df):
    trades = []

    for i in range(len(df)):
        row = df.iloc[i]

        if row["Signal"] == 0 or pd.isna(row["Action"]) or row["Action"] == 0:
            continue
        if pd.isna(row["ATR"]):
            continue

        entry_price = float(row["Close"])
        sig_type = "BUY" if row["Signal"] == 1 else "SELL"

        # 【修正】本番と同じ関数でTP/SLを計算（最低幅も同じ）
        tp, sl, _, _ = calc_tp_sl(entry_price, float(row["ATR"]), sig_type)

        # エントリー後の未来MAX_BARS本の動きを検証（本番と同じ判定関数）
        future_df = df.iloc[i + 1 : i + 1 + MAX_BARS]
        result, pnl = judge_trade(sig_type, entry_price, tp, sl, future_df)

        if result is not None:  # データの終わりで判定できないものだけ除外
            trades.append({"Result": result, "PnL": pnl})

    s = summarize(pd.DataFrame(trades, columns=["Result", "PnL"]))

    print("\n========== 【バックテスト結果】 ==========")
    print(f"総トレード数: {s['total']}件")
    print(f"勝ち: {s['wins']}件 / 負け: {s['loses']}件 / 時間切れ: {s['timeouts']}件")
    print(f"勝率: {s['win_rate']:.1f}%")
    print(f"1回あたり平均損益: {s['avg_pips']:+.1f}pips")
    print(f"合計損益: {s['total_pips']:+.1f}pips（コスト{COST_YEN * 100:.1f}pips/回を差し引き済み）")
    print("==========================================")


# バックテストの実行
run_backtest(df)
