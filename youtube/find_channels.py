"""直近30日で200万再生以上を稼いだ「有名すぎない」YouTubeチャンネルを探す。

使い方:
  export YOUTUBE_API_KEY=xxxx
  python3 find_channels.py --min-views 2000000 --max-subs 1000000

注意: YouTube Data API ではチャンネルの「期間別再生数」は取れないため、
「直近30日に投稿された動画の再生数合計」で近似している。
"""
import argparse, csv, json, os, sys, urllib.parse, urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone

API = "https://www.googleapis.com/youtube/v3/"
KEY = os.environ.get("YOUTUBE_API_KEY")

# 芸能人・超有名どころの手動除外（チャンネル名の部分一致）
EXCLUDE_NAMES = ["ヒカル", "HikakinTV", "HIKAKIN", "はじめしゃちょー", "東海オンエア",
                 "フィッシャーズ", "コムドット", "Kizuna", "Official", "公式", "TBS", "日テレ",
                 "テレビ朝日", "フジテレビ", "NHK", "ANN", "FNN", "ジャニーズ", "STARTO",
                 "avex", "Sony Music", "VEVO"]


def get(endpoint, **params):
    params["key"] = KEY
    url = API + endpoint + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url) as r:
        return json.load(r)


def chunks(xs, n=50):
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-views", type=int, default=2_000_000)
    ap.add_argument("--max-subs", type=int, default=1_000_000, help="これ以上の登録者は有名として除外")
    ap.add_argument("--pages", type=int, default=3, help="1日あたりの検索ページ数 (1ページ=50件=100ユニット、30日×3ページ=9000ユニット)")
    ap.add_argument("--region", default="JP")
    ap.add_argument("--out", default="channels.csv")
    a = ap.parse_args()
    if not KEY:
        sys.exit("環境変数 YOUTUBE_API_KEY を設定してください")

    since = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    video_ids = set()

    # 1) 急上昇（カテゴリ別）: 1ユニット/回で安い
    cats = get("videoCategories", part="snippet", regionCode=a.region)
    for c in [None] + [i["id"] for i in cats["items"] if i["snippet"]["assignable"]]:
        token = None
        for _ in range(4):
            p = dict(part="id", chart="mostPopular", regionCode=a.region, maxResults=50)
            if c: p["videoCategoryId"] = c
            if token: p["pageToken"] = token
            try:
                r = get("videos", **p)
            except Exception:
                break
            video_ids.update(i["id"] for i in r["items"])
            token = r.get("nextPageToken")
            if not token: break

    # 2) キーワードなしで、直近30日を1日ずつ区切って「その日に投稿された動画の再生数上位」を取る
    #    (検索は1回あたり最大500件までなので、日ごとに分けて取りこぼしを減らす。100ユニット/ページ)
    now = datetime.now(timezone.utc)
    for d in range(30):
        start = (now - timedelta(days=d + 1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        end = (now - timedelta(days=d)).strftime("%Y-%m-%dT%H:%M:%SZ")
        token = None
        for _ in range(a.pages):
            p = dict(part="id", type="video", order="viewCount", publishedAfter=start,
                     publishedBefore=end, regionCode=a.region, relevanceLanguage="ja", maxResults=50)
            if token: p["pageToken"] = token
            r = get("search", **p)
            video_ids.update(i["id"]["videoId"] for i in r["items"])
            token = r.get("nextPageToken")
            if not token: break
    print(f"候補動画: {len(video_ids)}", file=sys.stderr)

    # 3) 動画の再生数を取得し、30日以内の動画をチャンネル別に集計
    ch_views, ch_count, ch_top = defaultdict(int), defaultdict(int), {}
    for ids in chunks(list(video_ids)):
        for v in get("videos", part="snippet,statistics", id=",".join(ids))["items"]:
            if v["snippet"]["publishedAt"] < since:
                continue
            cid, views = v["snippet"]["channelId"], int(v["statistics"].get("viewCount", 0))
            ch_views[cid] += views
            ch_count[cid] += 1
            if views > ch_top.get(cid, ("", 0))[1]:
                ch_top[cid] = (v["snippet"]["title"], views)

    # 4) チャンネル情報で有名どころを除外
    cands = [c for c, n in ch_views.items() if n >= a.min_views]
    rows = []
    for ids in chunks(cands):
        for ch in get("channels", part="snippet,statistics", id=",".join(ids))["items"]:
            name = ch["snippet"]["title"]
            subs = int(ch["statistics"].get("subscriberCount", 0))
            if subs >= a.max_subs or any(x.lower() in name.lower() for x in EXCLUDE_NAMES):
                continue
            rows.append(dict(channel=name, subscribers=subs,
                             views_30d_new_videos=ch_views[ch["id"]], videos_30d=ch_count[ch["id"]],
                             top_video=ch_top[ch["id"]][0], top_video_views=ch_top[ch["id"]][1],
                             url=f"https://www.youtube.com/channel/{ch['id']}"))
    rows.sort(key=lambda r: -r["views_30d_new_videos"])
    with open(a.out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["channel"])
        w.writeheader(); w.writerows(rows)
    for r in rows:
        print(f'{r["views_30d_new_videos"]:>12,}  登録者{r["subscribers"]:>9,}  {r["channel"]}  {r["url"]}')
    print(f"\n{len(rows)} チャンネル → {a.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
