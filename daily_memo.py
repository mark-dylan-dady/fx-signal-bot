"""毎朝のLINE相場メモ

シグナルが出ない日も、毎朝LINEに「今の相場の様子」と
「シグナルまであと何条件か」を送ります。
・1時間足のトレンドの向きと強さ
・5分足の条件クリア数(あと一歩度)
・値動きの活発さ
・データ貯金箱(実際に貯まったシグナルの件数と成績)
"""
import os

import pandas as pd
import requests
import yfinance as yf
from dotenv import load_dotenv

load_dotenv()

CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
USER_ID = os.getenv("LINE_USER_ID")

# ==========================================
# 設定（fxbot_multipair.py と同じ値にそろえてください）
# ==========================================
PAIRS = ["AUDJPY=X", "EURJPY=X"]
MIN_SLOPE = 0.03
RSI_BUY_LOW, RSI_BUY_HIGH = 55, 65
RSI_SELL_LOW, RSI_SELL_HIGH = 37, 43

SAMPLE_GOAL = 50  # データ貯金箱の目標件数（1ペアあたり）
WEEKDAYS = ["月", "火", "水", "木", "金", "土", "日"]


def send_line(message):
    if not CHANNEL_ACCESS_TOKEN or not USER_ID:
        print("LINEのトークンまたはユーザーIDが未設定のため、送信はスキップしました。")
        return False
    res = requests.post(
        "https://api.line.me/v2/bot/message/push",
        headers={
            "Authorization": f"Bearer {CHANNEL_ACCESS_TOKEN}",
            "Content-Type": "application/json",
        },
        json={"to": USER_ID, "messages": [{"type": "text", "text": message}]},
        timeout=30,
    )
    print("LINE送信:", res.status_code)
    return res.status_code == 200


# ==========================================
# 相場データの取得と指標の計算（本番botと同じ計算）
# ==========================================
def load_market(pair):
    df = yf.download(pair, period="10d", interval="5m", progress=False)
    df_1h = yf.download(pair, period="30d", interval="1h", progress=False)
    if df.empty or df_1h.empty:
        raise ValueError("データが取得できませんでした")

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)
    if isinstance(df_1h.columns, pd.MultiIndex):
        df_1h.columns = df_1h.columns.droplevel(1)

    # 1時間足のトレンド（未来の情報が混ざらないよう1本ずらす）
    df_1h["SMA_Trend"] = df_1h["Close"].rolling(window=20).mean()
    df_1h["SMA_Slope"] = df_1h["SMA_Trend"].diff()
    df_1h[["SMA_Trend", "SMA_Slope"]] = df_1h[["SMA_Trend", "SMA_Slope"]].shift(1)

    df = pd.merge_asof(
        df.sort_index(),
        df_1h[["SMA_Trend", "SMA_Slope"]].sort_index(),
        left_index=True,
        right_index=True,
    )

    df["SMA_Short"] = df["Close"].rolling(window=5).mean()
    df["SMA_Long"] = df["Close"].rolling(window=20).mean()

    delta = df["Close"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    df["RSI"] = 100 - (100 / (1 + gain / loss))

    high_low = df["High"] - df["Low"]
    high_close = (df["High"] - df["Close"].shift()).abs()
    low_close = (df["Low"] - df["Close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df["ATR"] = tr.rolling(window=14).mean()

    df["High_Max3"] = df["High"].shift(1).rolling(window=3).max()
    df["Low_Min3"] = df["Low"].shift(1).rolling(window=3).min()
    return df


def rsi_label(kind, low, high, rsi):
    """RSIが帯に入っていない理由(高すぎ/低すぎ)が分かる文言"""
    if rsi > high:
        return f"RSI高すぎ(今{rsi:.1f}・{kind}帯{low}-{high})"
    if rsi < low:
        return f"RSI低すぎ(今{rsi:.1f}・{kind}帯{low}-{high})"
    return f"RSIが{kind}帯({low}-{high})に入る(今{rsi:.1f})"


def analyze(df):
    """直近の確定した5分足から、今の相場の様子をまとめる"""
    row = df.iloc[-2]
    last = df.index[-2]
    if last.tzinfo is None:
        last = last.tz_localize("UTC")
    last_jst = last.tz_convert("Asia/Tokyo")
    now = pd.Timestamp.now(tz="Asia/Tokyo")
    market_open = (now - last_jst) < pd.Timedelta(hours=6)

    close = float(row["Close"])
    rsi = float(row["RSI"])
    atr = float(row["ATR"])
    slope = float(row["SMA_Slope"])
    trend = float(row["SMA_Trend"])
    short_above = bool(row["SMA_Short"] > row["SMA_Long"])

    buy = [
        ("5分足の短期線が長期線の上", short_above),
        ("1時間足トレンドの上", close > trend),
        ("1時間足の傾きが上向き", slope > MIN_SLOPE),
        (rsi_label("買い", RSI_BUY_LOW, RSI_BUY_HIGH, rsi), RSI_BUY_LOW <= rsi <= RSI_BUY_HIGH),
        ("直近3本の高値を更新", close > float(row["High_Max3"])),
    ]
    sell = [
        ("5分足の短期線が長期線の下", not short_above),
        ("1時間足トレンドの下", close < trend),
        ("1時間足の傾きが下向き", slope < -MIN_SLOPE),
        (rsi_label("売り", RSI_SELL_LOW, RSI_SELL_HIGH, rsi), RSI_SELL_LOW <= rsi <= RSI_SELL_HIGH),
        ("直近3本の安値を更新", close < float(row["Low_Min3"])),
    ]

    if close > trend and slope > MIN_SLOPE:
        side, conds, arrow = "買い", buy, "📈"
        label, outlook = "上昇トレンド", "今夜は買いシグナルが出やすい日"
    elif close < trend and slope < -MIN_SLOPE:
        side, conds, arrow = "売り", sell, "📉"
        label, outlook = "下降トレンド", "今夜は売りシグナルが出やすい日"
    else:
        side = "買い" if sum(c for _, c in buy) >= sum(c for _, c in sell) else "売り"
        conds = buy if side == "買い" else sell
        arrow = "➡️"
        label, outlook = "方向感が弱い", "傾きが弱く、シグナルは出にくい日"

    atr_avg = float(df["ATR"].tail(1440).mean())  # 直近約5日の平均
    ratio = atr / atr_avg if atr_avg > 0 else 1.0
    vol = "活発" if ratio > 1.2 else ("静か" if ratio < 0.8 else "ふつう")

    return {
        "close": close, "slope": slope, "side": side, "conds": conds,
        "arrow": arrow, "label": label, "outlook": outlook,
        "atr_pips": atr * 100, "ratio": ratio, "vol": vol,
        "market_open": market_open, "last_jst": last_jst,
    }


def format_section(name, a):
    ok = sum(1 for _, c in a["conds"] if c)
    bar = "".join("✅" if c else "⬜" for _, c in a["conds"])
    missing = [t for t, c in a["conds"] if not c]
    lines = [
        f"【{name}】{a['close']:.2f}円",
        f"{a['arrow']} 1時間足: {a['label']}(傾き{a['slope']:+.3f})",
        f"→ {a['outlook']}",
        f"🎯 {a['side']}の条件 {ok}/5 {bar}",
    ]
    if missing:
        lines.append("あと: " + " / ".join(missing))
    lines.append(f"🌊 値動き: {a['vol']}(ATR {a['atr_pips']:.1f}pips)")
    return "\n".join(lines)


# ==========================================
# データ貯金箱（実際に貯まったシグナルの記録）
# ==========================================
def history_path(pair):
    name = pair.replace("=X", "")
    path = f"signals_history_{name}.csv"
    if os.path.exists(path):
        return path
    if name == "AUDJPY" and os.path.exists("signals_history.csv"):
        return "signals_history.csv"
    return None


def load_history(pair):
    path = history_path(pair)
    if path is None:
        return pd.DataFrame({
            "Type": pd.Series(dtype=str), "Result": pd.Series(dtype=str),
            "PnL": pd.Series(dtype=float), "Time": pd.Series(dtype="datetime64[ns]"),
        })
    h = pd.read_csv(path)
    if "PnL" not in h.columns:
        h["PnL"] = float("nan")
    h["PnL"] = pd.to_numeric(h["PnL"], errors="coerce")
    h["Time"] = pd.to_datetime(h["Timestamp"], errors="coerce")
    return h


def scoreboard(pairs):
    lines = ["🐷 データ貯金箱(実測)"]
    now_naive = pd.Timestamp.now(tz="Asia/Tokyo").tz_localize(None)
    last_sig = None
    recent = []

    for pair in pairs:
        name = pair.replace("=X", "")
        h = load_history(pair)
        done = h[h["Result"].isin(["WIN", "LOSE", "TIMEOUT"])]
        n = len(done)
        wins = int((done["Result"] == "WIN").sum())
        loses = int((done["Result"] == "LOSE").sum())
        pips = float(done["PnL"].sum() * 100) if n else 0.0
        filled = min(5, -(-n * 5 // SAMPLE_GOAL))  # 1件でもあれば最低1マス点灯（切り上げ）
        lines.append(f"{name} {n}/{SAMPLE_GOAL}件")
        lines.append(f"{'🟦' * filled}{'⬜' * (5 - filled)} 勝{wins}負{loses} {pips:+.1f}pips")

        if h["Time"].notna().any():
            t = h["Time"].max()
            if last_sig is None or t > last_sig:
                last_sig = t
        for _, r in h[h["Time"] > now_naive - pd.Timedelta(hours=24)].iterrows():
            recent.append((name, r))

    if recent:
        lines.append("")
        lines.append("🌙 昨夜からのシグナル")
        for name, r in recent:
            icon = {"WIN": "🏆", "LOSE": "💧", "TIMEOUT": "⌛"}.get(r["Result"], "⏳")
            res = {"WIN": "利確", "LOSE": "損切", "TIMEOUT": "時間切れ"}.get(r["Result"], "結果待ち")
            kind = "買い" if r["Type"] == "BUY" else "売り"
            lines.append(f" {name} {kind} {r['Time'].strftime('%H:%M')} {icon}{res}")

    lines.append("")
    if last_sig is not None:
        days = (now_naive - last_sig).days
        lines.append(f"⏱ 最後のシグナル: {last_sig.strftime('%m/%d %H:%M')}({days}日前)")
    else:
        lines.append("⏱ 最後のシグナル: まだありません")
    return "\n".join(lines)


def one_liner(analyses, closed):
    if closed:
        return "市場はお休み。走ったり畑仕事をしたり、のんびりどうぞ🚴🥕"
    if not analyses:
        return "データが取れない朝もあります。また明日！"
    avg = sum(a["ratio"] for a in analyses.values()) / len(analyses)
    if avg > 1.2:
        return "値動きが活発です。今夜は期待できるかも✨"
    if avg < 0.8:
        return "静かな相場です。気楽にいきましょう🚴"
    return "ふつうの値動きです。今夜のシグナルを気長に待ちましょう☕"


def main():
    now = pd.Timestamp.now(tz="Asia/Tokyo")
    analyses, errors = {}, []
    for pair in PAIRS:
        name = pair.replace("=X", "")
        try:
            analyses[name] = analyze(load_market(pair))
        except Exception as e:
            errors.append(f"【{name}】データ取得に失敗しました({type(e).__name__})")

    closed = bool(analyses) and not any(a["market_open"] for a in analyses.values())

    parts = [f"☀️ 朝の相場メモ {now.month}/{now.day}({WEEKDAYS[now.weekday()]}) {now:%H:%M}"]
    parts.append("⏰ シグナル解禁: 21〜22時台・1〜5時台")
    if closed:
        last = max(a["last_jst"] for a in analyses.values())
        parts.append(f"🛌 市場はお休み中(最終データ {last:%m/%d %H:%M})")
    else:
        for name, a in analyses.items():
            parts.append(format_section(name, a))
    parts.extend(errors)
    parts.append(scoreboard(PAIRS))
    parts.append("💬 " + one_liner(analyses, closed))

    msg = "\n\n".join(parts)
    print(msg)
    send_line(msg)


if __name__ == "__main__":
    main()
