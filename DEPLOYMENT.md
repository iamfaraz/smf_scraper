# Deployment Guide

## Docker (Self-Hosted)

Two files are already included in the project: `Dockerfile` and `docker-compose.yml`.

**To run:**
```bash
docker compose up -d          # build + start in background
docker compose logs -f        # follow logs
docker compose down           # stop
```

The `data/` folder is mounted as a volume so your saved scrapes survive container restarts/rebuilds.

---

## cPanel Deployment

cPanel runs Python apps via **Passenger** (WSGI). The process:

### 1. Upload files
Upload everything (`app.py`, `wayback.py`, `templates/`, `requirements.txt`) to a directory like `~/smf_archiver/` via File Manager or SFTP. Do **not** upload `data/` — cPanel will need a writable path (see step 4).

### 2. Create a Python app in cPanel
- Go to **Software → Setup Python App**
- Click **Create Application**
- Set:
  - **Python version**: 3.11 (or highest available)
  - **Application root**: `smf_archiver`
  - **Application URL**: the subdomain/path you want (e.g. `archive.yourdomain.com`)
  - **Application startup file**: `passenger_wsgi.py` (you'll create this)
  - **Application Entry point**: `application`

### 3. Create `passenger_wsgi.py`
cPanel's Passenger needs a WSGI entry point. Create this file in your app root:

```python
# passenger_wsgi.py
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from app import app as application
```

### 4. Fix the data directory path
The default `DATA_DIR` in `app.py` uses `os.path.dirname(__file__)` which works fine — but make sure the `data/` folder exists in your app root and is writable:
```bash
mkdir ~/smf_archiver/data
chmod 755 ~/smf_archiver/data
```

### 5. Install dependencies
In cPanel's Python App panel, after creating the app, there's a **pip install** field — paste the contents of `requirements.txt` one by one, or use the terminal:
```bash
source ~/virtualenv/smf_archiver/3.11/bin/activate
pip install -r ~/smf_archiver/requirements.txt
```

### 6. Restart the app
Hit **Restart** in the Python App panel. Your app will be live at the configured URL.

---

## SSE Caveat for cPanel

The scraping uses **Server-Sent Events** (streaming responses). Many shared cPanel hosts buffer responses and will break SSE. Check if your host supports it — the `X-Accel-Buffering: no` header is already set in `app.py` which helps with nginx-based setups. If SSE doesn't work, you may need a VPS instead (which is where Docker shines).
