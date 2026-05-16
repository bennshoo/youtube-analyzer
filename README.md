# YouTube Channel Analyzer

Paste any public YouTube channel URL and get:

- **Views in the last 30 days** — sum of views on videos published in the last 30 days
- **Full video table** — every video sorted newest → oldest, with date, title, view count, and comment count

## Setup

### 1. Get a YouTube Data API v3 key

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project → **APIs & Services → Library**
3. Enable **YouTube Data API v3**
4. Go to **Credentials → Create Credentials → API key**

### 2. Configure the key

```bash
cp .env.example .env
# Edit .env and paste your key
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Run

```bash
python app.py
```

Open [http://localhost:5000](http://localhost:5000) in your browser.

## Supported URL formats

- `https://www.youtube.com/@handle`
- `https://www.youtube.com/channel/UCxxxxxx`
- `https://www.youtube.com/user/username`
- `https://www.youtube.com/c/customname`

## Notes

- The YouTube Data API has a daily quota of **10,000 units**. Each analysis of a channel with N videos costs roughly `1 + ceil(N/50) + ceil(N/50)` quota units. A channel with 500 videos ≈ 21 units.
- Views in the last 30 days reflects views on videos *published* in that window — not total channel traffic (that requires OAuth access to YouTube Analytics, which only works for channels you own).
