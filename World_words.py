"""世界のことば ベスト10: 今日話題のワードをLINEに知らせる(追加ライブラリ不要)。

- Google トレンド(急上昇ワード): 日本・アメリカ
- Wikipedia 日本語版: 前日によく見られた記事(世界の関心の目安)
"""
import json
import os
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

TOP_N = 10
TRENDS = [("🇯🇵 日本の急上昇", "JP"), ("🇺🇸 アメリカの急上昇", "US")]  # ★国を足せます(例: ("🇬🇧 イギリス","GB"))
UA = "Mozilla/5.0 (world-words-bot; personal use)"
SKIP_PREFIX = ("特別:", "Wikipedia:", "ファイル:", "カテゴリ:", "Category:", "Special:",
               "ヘルプ:", "Help:", "Portal:", "プロジェクト:", "Template:", "ノート:")
SKIP_EXACT = {"メインページ", "Main_Page", "-"}


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def local(tag):
    return tag.rsplit("}", 1)[-1]


def parse_trends(xml_bytes, n=TOP_N):
    """Google トレンドRSSから (ワード, 検索回数の目安) を取り出す"""
    root = ET.fromstring(xml_bytes)
    out = []
    for item in root.iter("item"):
        title, traffic = None, ""
        for ch in item:
            name = local(ch.tag)
            if name == "title":
                title = (ch.text or "").strip()
            elif name == "approx_traffic":
                traffic = (ch.text or "").strip()
        if title:
            out.append((title, traffic))
        if len(out) >= n:
            break
    return out


def get_trends(geo):
    return parse_trends(fetch(f"https://trends.google.com/trending/rss?geo={geo}"))


def get_wikipedia(n=TOP_N):
    now = datetime.now(timezone.utc)
    last_err = None
    for back in (1, 2):
        d = now - timedelta(days=back)
        url = ("https://wikimedia.org/api/rest_v1/metrics/pageviews/top/"
               f"ja.wikipedia/all-access/{d:%Y/%m/%d}")
        try:
            data = json.loads(fetch(url))
            arts = data["items"][0]["articles"]
            out = []
            for a in arts:
                t = a["article"]
                if t in SKIP_EXACT or t.startswith(SKIP_PREFIX):
                    continue
                out.append((t.replace("_", " "), a["views"]))
                if len(out) >= n:
                    break
            return out, d.strftime("%m/%d")
        except Exception as e:
            last_err = e
    raise last_err


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
    lines = [f"🌍 世界のことば ベスト10 {today}"]
    ok = 0

    for label, geo in TRENDS:
        try:
            items = get_trends(geo)
            lines += ["", label]
            for i, (w, t) in enumerate(items, 1):
                lines.append(f"{i}. {w}" + (f" ({t})" if t else ""))
            ok += 1
        except Exception as e:
            print(f"取得失敗 {geo}: {e}")

    try:
        items, day = get_wikipedia()
        lines += ["", f"📖 Wikipediaでよく見られた記事({day})"]
        for i, (w, v) in enumerate(items, 1):
            lines.append(f"{i}. {w} ({v:,}回)")
        ok += 1
    except Exception as e:
        print(f"取得失敗 Wikipedia: {e}")

    if ok == 0:
        raise SystemExit(1)

    lines += ["", "※()内は検索回数・閲覧数の目安"]
    send_line("\n".join(lines))
    print("送信OK")


if __name__ == "__main__":
    main()

