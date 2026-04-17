# SMF Topic Archiver - Developed Using Claude Code

A web application for discovering, scraping, and preserving archived copies of Simple Machines Forum (SMF) threads via the Wayback Machine.

## What It Does

SMF Topic Archiver lets you:

- Find all archived captures of an SMF forum topic across multiple dates
- Scrape multi-page threads, selecting the best Wayback capture per page
- Save scraped threads as persistent JSON records with full post metadata
- View saved archives with filtering, pagination, and export options
- Load additional pages into an existing saved archive at any time

## Tech Stack

- **Backend:** Python 3.11, Flask 3.0, BeautifulSoup4, lxml, Requests
- **Frontend:** Vanilla JavaScript, HTML5/Jinja2, Server-Sent Events (SSE)
- **Storage:** File-based JSON in `data/`
- **Deployment:** Docker / Docker Compose, or cPanel Passenger WSGI

## Getting Started

### Local Development

```bash
pip install -r requirements.txt
python app.py
```

App runs at `http://localhost:5110`.

### Docker (Recommended)

```bash
docker compose up -d
```

App runs at `http://localhost:5110`. Scraped data is persisted to `./data/` on the host.

```bash
docker compose logs -f   # follow logs
docker compose down      # stop
```

## Usage

1. **Find captures** — Paste an SMF topic URL (e.g. `http://example.com/index.php?topic=42.0`) into the home page and click *Find Captures*. Optionally filter by date range.
2. **Scrape** — Click a capture's *Scrape* link. The app detects the total page count and selects the best Wayback capture for each page individually.
3. **Save** — After scraping (all pages or a partial batch), click *Save* to persist the archive.
4. **View** — Open a saved archive from the home page. Filter by author or word count, paginate, load more pages, or export to JSON/CSV.

## Project Structure

```
app.py              # Flask routes and API endpoints
wayback.py          # Wayback Machine CDX queries, HTTP helpers, SMF parsing
templates/
  index.html        # Home page — capture discovery and saved scrapes list
  scrape.html       # Batch scraping interface with real-time progress
  view.html         # Saved archive viewer with filters and export
data/               # Saved scrape JSON files (git-ignored)
requirements.txt
Dockerfile
docker-compose.yml
DEPLOYMENT.md       # Docker and cPanel deployment details
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/captures` | Query Wayback CDX for all captures of a topic URL |
| `POST` | `/api/detect` | Fetch a capture to detect page count |
| `POST` | `/api/captures_for_page` | Find captures for a specific page offset |
| `POST` | `/api/scrape` | Batch-scrape pages (SSE streaming) |
| `POST` | `/api/scrape_page` | Scrape a single page (SSE streaming) |
| `POST` | `/api/save` | Create a new saved archive |
| `PATCH` | `/api/saved/<id>` | Append or replace posts in an existing archive |
| `GET` | `/api/saved` | List all saved archives |
| `GET` | `/api/saved/<id>` | Load a saved archive |
| `DELETE` | `/api/saved/<id>` | Delete a saved archive |

## Saved Archive Format

Each saved archive is a JSON file in `data/`:

```json
{
  "meta": {
    "id": "0553a31666f7",
    "title": "Thread Title - Forum Name",
    "timestamp": "20151201000000",
    "original": "http://example.com/index.php?topic=42.0",
    "total_posts": 342,
    "pages_scraped": 5,
    "total_pages": 23,
    "unique_authors": 28,
    "saved_at": "2026-04-17 17:42"
  },
  "posts": [
    {
      "post_id": "12345",
      "author": "Username",
      "author_role": "Administrator",
      "date_raw": "December 01, 2015, 10:30:00 am",
      "page_offset": 0,
      "content": "Post text here...",
      "word_count": 125,
      "source_url": "https://web.archive.org/web/20151201000000/..."
    }
  ]
}
```

## Deployment

See [DEPLOYMENT.md](DEPLOYMENT.md) for full instructions covering Docker and cPanel Passenger WSGI setups.

> **Note:** SSE-based real-time progress requires a server that does not buffer responses. Many shared hosting providers buffer by default, which breaks the live progress display. A VPS is recommended for full functionality.

## Dependencies

```
flask==3.0.3
requests==2.31.0
beautifulsoup4==4.12.3
lxml==5.2.1
```

Gunicorn is installed automatically in the Docker image for production serving.
