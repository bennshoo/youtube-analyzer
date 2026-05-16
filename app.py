import os
import re
from datetime import datetime, timezone, timedelta

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

load_dotenv()

app = Flask(__name__)

YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY")
YT_BASE = "https://www.googleapis.com/youtube/v3"


def extract_channel_identifier(url):
    url = url.strip()

    patterns = [
        (r"youtube\.com/channel/([UC][A-Za-z0-9_-]{22})", "id"),
        (r"youtube\.com/@([A-Za-z0-9._-]+)", "handle"),
        (r"youtube\.com/user/([A-Za-z0-9._-]+)", "username"),
        (r"youtube\.com/c/([A-Za-z0-9._-]+)", "custom"),
    ]
    for pattern, kind in patterns:
        m = re.search(pattern, url)
        if m:
            return {"type": kind, "value": m.group(1)}

    if url.startswith("@"):
        return {"type": "handle", "value": url[1:]}

    return None


def resolve_channel(identifier):
    params = {
        "part": "id,snippet,contentDetails",
        "key": YOUTUBE_API_KEY,
        "maxResults": 1,
    }

    if identifier["type"] == "id":
        params["id"] = identifier["value"]
    elif identifier["type"] == "handle":
        params["forHandle"] = identifier["value"]
    elif identifier["type"] == "username":
        params["forUsername"] = identifier["value"]
    elif identifier["type"] == "custom":
        # Custom URLs often work as handles; fall back to search if not
        params["forHandle"] = identifier["value"]

    resp = requests.get(f"{YT_BASE}/channels", params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    if not data.get("items"):
        if identifier["type"] == "custom":
            # Try a search as a last resort
            search_params = {
                "part": "snippet",
                "q": identifier["value"],
                "type": "channel",
                "maxResults": 1,
                "key": YOUTUBE_API_KEY,
            }
            search_resp = requests.get(f"{YT_BASE}/search", params=search_params, timeout=10)
            search_resp.raise_for_status()
            search_data = search_resp.json()
            if not search_data.get("items"):
                return None
            channel_id = search_data["items"][0]["snippet"]["channelId"]
            ch_params = {
                "part": "id,snippet,contentDetails",
                "id": channel_id,
                "key": YOUTUBE_API_KEY,
            }
            ch_resp = requests.get(f"{YT_BASE}/channels", params=ch_params, timeout=10)
            ch_resp.raise_for_status()
            ch_data = ch_resp.json()
            if not ch_data.get("items"):
                return None
            return ch_data["items"][0]
        return None

    return data["items"][0]


def get_recent_video_ids(uploads_playlist_id, limit=100):
    video_ids = []
    page_token = None

    while len(video_ids) < limit:
        params = {
            "part": "contentDetails",
            "playlistId": uploads_playlist_id,
            "maxResults": min(50, limit - len(video_ids)),
            "key": YOUTUBE_API_KEY,
        }
        if page_token:
            params["pageToken"] = page_token

        resp = requests.get(f"{YT_BASE}/playlistItems", params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        for item in data.get("items", []):
            video_ids.append(item["contentDetails"]["videoId"])

        page_token = data.get("nextPageToken")
        if not page_token:
            break

    return video_ids


def get_video_details(video_ids):
    details = []
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i : i + 50]
        params = {
            "part": "snippet,statistics",
            "id": ",".join(batch),
            "key": YOUTUBE_API_KEY,
        }
        resp = requests.get(f"{YT_BASE}/videos", params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        details.extend(data.get("items", []))
    return details


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/analyze", methods=["POST"])
def analyze():
    if not YOUTUBE_API_KEY:
        return jsonify({"error": "YOUTUBE_API_KEY is not set on the server."}), 500

    body = request.get_json(silent=True) or {}
    url = body.get("url", "").strip()
    if not url:
        return jsonify({"error": "No URL provided."}), 400

    identifier = extract_channel_identifier(url)
    if not identifier:
        return jsonify({"error": "Could not parse a YouTube channel URL. Try a link like https://www.youtube.com/@handle"}), 400

    try:
        channel = resolve_channel(identifier)
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 403:
            return jsonify({"error": "YouTube API quota exceeded or API key invalid."}), 502
        return jsonify({"error": f"YouTube API error: {e}"}), 502

    if not channel:
        return jsonify({"error": "Channel not found."}), 404

    uploads_playlist_id = channel["contentDetails"]["relatedPlaylists"]["uploads"]
    channel_name = channel["snippet"]["title"]
    thumbnail = (
        channel["snippet"]
        .get("thumbnails", {})
        .get("default", {})
        .get("url", "")
    )

    try:
        video_ids = get_recent_video_ids(uploads_playlist_id, limit=100)
        videos_raw = get_video_details(video_ids)
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 403:
            return jsonify({"error": "YouTube API quota exceeded or API key invalid."}), 502
        return jsonify({"error": f"YouTube API error: {e}"}), 502

    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    views_last_30 = 0
    processed = []

    for v in videos_raw:
        snippet = v.get("snippet", {})
        stats = v.get("statistics", {})

        published_str = snippet.get("publishedAt", "")
        try:
            published = datetime.fromisoformat(published_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            published = datetime.min.replace(tzinfo=timezone.utc)

        view_count = int(stats.get("viewCount", 0))

        if published >= cutoff:
            views_last_30 += view_count

        processed.append(
            {
                "date": published.strftime("%Y-%m-%d"),
                "title": snippet.get("title", ""),
                "views": view_count,
                "url": f"https://www.youtube.com/watch?v={v['id']}",
                "_ts": published.timestamp(),
            }
        )

    processed.sort(key=lambda x: x["_ts"], reverse=True)
    for v in processed:
        del v["_ts"]

    return jsonify(
        {
            "channel_name": channel_name,
            "thumbnail": thumbnail,
            "views_last_30_days": views_last_30,
            "video_count": len(processed),
            "videos": processed,
        }
    )


if __name__ == "__main__":
    app.run(debug=True, port=5000)
