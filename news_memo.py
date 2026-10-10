"""ニュース温度計: 注目ワードの記事数を数えて、LINEに知らせる(追加ライブラリ不要)。

- 記事数は Google ニュースのRSSから「過去24時間」の件数を数える(上限約100件)
- 毎日の件数を news_history.csv に貯めて、貯まったら「普段の何倍か」を出す
"""
import csv
import json
import os
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

# ★ここを書き換えると、見るワードを変えられる
KEYWORDS = [
    "関税", "トランプ", "FOMC", "雇用統計",
    "日銀", "利上げ", "為替介入", "円安", "円高",
    "解散", "内閣",
]
HISTORY_FILE = "news_history.csv"
BASELINE_DAYS = 30   # 「普段」を計算する日数
MIN_DAYS = 3         # これ以上貯まったら倍率を表示
HOT_RATIO = 1.5      # この倍率以上で🔥

JST = timezone(timedelta(hours=9))


def count_articles(keyword):
    """過去24時間の記事数(RSSの上限は約100件)"""
    q = urllib.parse.quote(f"{keyword} when:1d")
    url = f"https://news.google.com/rss/search?q={q}&hl=ja&gl=JP&ceid=JP:ja"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        root = ET.fromstring(r.read())
    return len(root.findall(".//item"))


def load_history():
    rows = []
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
    return rows


def save_history(rows):
    with open(HISTORY_FILE, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "keyword", "count"])
        w.writeheader()
        w.writerows(rows)


def send_line(text):
    token = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
    user_id = os.environ["LINE_USER_ID"]
    body = json.dumps({"to": user_id, "messages": [{"type": "text", "text": text}]}).encode()
    req = urllib.request.Request(
        "https://api.line.me/v2/bot/message/push",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
    )
    urllib.request.urlopen(req, timeout=30).read()


def main():
    today = datetime.now(JST).strftime("%Y-%m-%d")

    counts = {}
    for kw in KEYWORDS:
        try:
            counts[kw] = count_articles(kw)
        except Exception as e:
            print(f"取得失敗 {kw}: {e}")

    if not counts:
        raise SystemExit(1)

    # 履歴(今日の分は入れ直す)
    rows = [r for r in load_history() if r["date"] != today]
    past_days = sorted({r["date"] for r in rows})[-BASELINE_DAYS:]
    base = {}
    for kw in counts:
        vals = [int(r["count"]) for r in rows if r["keyword"] == kw and r["date"] in past_days]
        base[kw] = sum(vals) / len(vals) if vals else None

    for kw, c in counts.items():
        rows.append({"date": today, "keyword": kw, "count": c})
    save_history(rows)

    # メッセージ作成
    have_base = len(past_days) >= MIN_DAYS
    lines = [f"📰 ニュース温度計 {today}", ""]
    total, total_base = 0, 0.0
    for kw, c in sorted(counts.items(), key=lambda x: -x[1]):
        total += c
        if have_base and base[kw]:
            total_base += base[kw]
            ratio = c / base[kw]
            mark = "🔥" if ratio >= HOT_RATIO else ""
            lines.append(f"{kw}: {c}件 (普段の{ratio:.1f}倍){mark}")
        else:
            lines.append(f"{kw}: {c}件")
    lines.append("")
    if have_base and total_base:
        r = total / total_base
        lines.append(f"全体: 普段の{r:.1f}倍" + ("  荒れやすい日かも" if r >= HOT_RATIO else ""))
    else:
        lines.append(f"データ貯め中({len(past_days)}/{MIN_DAYS}日)。貯まると「普段の何倍か」が出ます")
    lines.append("※件数は1ワードあたり約100件が上限")

    send_line("\n".join(lines))
    print("送信OK")


if __name__ == "__main__":
    main()
