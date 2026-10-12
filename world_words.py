"""世界のニュース ベスト10: 今日の主なニュースの見出しをLINEに知らせる(追加ライブラリ不要)。

Google ニュースのRSS(国際・トップニュース)から、見出しと報道元を取ります。
"""
import json
import os
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

# ★(見出し, URL, 表示件数) 。件数を変えたり、行を足したり消したりできます
BASE = "hl=ja&gl=JP&ceid=JP:ja"
SECTIONS = [
    ("🌍 世界のニュース", f"https://news.google.com/rss/headlines/section/topic/WORLD?{BASE}", 10),
    ("🇯🇵 日本のトップニュース", f"https://news.google.com/rss?{BASE}", 5),
]
UA = "Mozilla/5.0 (world-news-bot; personal use)"


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def parse_headlines(xml_bytes, n):
    """RSSから (見出し, 報道元) を最大n本取り出す"""
    root = ET.fromstring(xml_bytes)
    out, seen = [], set()
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        if not title:
            continue
        # Googleニュースの見出しは「見出し - 報道元」の形
        if " - " in title:
            head, src = title.rsplit(" - ", 1)
        else:
            head, src = title, ""
        key = head[:8]
        if key in seen:      # ほぼ同じ見出しの重複を除く
            continue
        seen.add(key)
        out.append((head.strip(), src.strip()))
        if len(out) >= n:
            break
    return out


def send_line(text):
    token = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
    user_id = os.environ["LINE_USER_ID"]
    body = json.dumps({"to": user_id, "messages": [{"type": "text", "text": text[:4900]}]}).encode()
    req = urllib.request.Request(
        "https://api.line.me/v2/bot/message/push", data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
    )
    urllib.request.urlopen(req, timeout=30).read()


def main():
    today = (datetime.now(timezone.utc) + timedelta(hours=9)).strftime("%Y-%m-%d")
    lines = [f"📰 今日のニュース {today}"]
    ok = 0

    for label, url, n in SECTIONS:
        try:
            items = parse_headlines(fetch(url), n)
            if not items:
                continue
            lines += ["", label]
            for i, (head, src) in enumerate(items, 1):
                lines.append(f"{i}. {head}" + (f"({src})" if src else ""))
            ok += 1
        except Exception as e:
            print(f"取得失敗 {label}: {e}")

    if ok == 0:
        raise SystemExit(1)

    send_line("\n".join(lines))
    print("送信OK")


if __name__ == "__main__":
    main()
