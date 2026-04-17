# wayback.py
import re
import time
import random
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
from urllib.parse import urlparse

CDX_URL  = "http://web.archive.org/cdx/search/cdx"
WB_BASE  = "https://web.archive.org/web"
DELAY    = 2.0

# Split timeouts: (connect seconds, read seconds)
TIMEOUT  = (15, 90)
MAX_RETRIES = 4

_UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
]


def _headers():
    return {
        "User-Agent": random.choice(_UAS),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    }


def _make_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def build_wayback_url(timestamp: str, original: str) -> str:
    return f"{WB_BASE}/{timestamp}/{original}"


# ── URL helpers ───────────────────────────────────────────────────────────────

def extract_topic_id(url: str) -> str:
    m = re.search(r"topic=(\d+)", url)
    return m.group(1) if m else "unknown"


def extract_offset(url: str) -> int:
    m = re.search(r"topic=\d+\.(\d+)", url)
    return int(m.group(1)) if m else 0


def set_offset(url: str, offset: int) -> str:
    if re.search(r"topic=\d+\.\d+", url):
        return re.sub(r"(topic=\d+)\.\d+", rf"\g<1>.{offset}", url)
    return re.sub(r"(topic=\d+)", rf"\g<1>.{offset}", url)


def topic_root_original(url: str) -> str:
    tid    = extract_topic_id(url)
    parsed = urlparse(url)
    base   = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    return f"{base}?topic={tid}.0"


def _ts_human(ts: str) -> str:
    try:
        return f"{ts[0:4]}-{ts[4:6]}-{ts[6:8]} {ts[8:10]}:{ts[10:12]}"
    except Exception:
        return ts


def _date_to_ts(date_str: str, end: bool = False) -> str:
    date_str = date_str.strip().replace("/", "-")
    parts = date_str.split("-")
    year  = parts[0].zfill(4) if len(parts) > 0 else "0000"
    month = parts[1].zfill(2) if len(parts) > 1 else ("12" if end else "01")
    day   = parts[2].zfill(2) if len(parts) > 2 else ("31" if end else "01")
    time_ = "235959" if end else "000000"
    return f"{year}{month}{day}{time_}"


# ── CDX discovery ─────────────────────────────────────────────────────────────

def discover_captures(topic_url: str,
                      date_from: str = "",
                      date_to: str = "") -> list:
    tid    = extract_topic_id(topic_url)
    parsed = urlparse(topic_url)
    base   = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    search = f"{base}?topic={tid}.*"

    params = {
        "url":      search,
        "output":   "json",
        "fl":       "timestamp,original,statuscode,mimetype",
        "filter":   ["statuscode:200", "mimetype:text/html"],
        "collapse": "timestamp:8",
        "limit":    2000,
    }
    if date_from:
        params["from"] = _date_to_ts(date_from, end=False)
    if date_to:
        params["to"]   = _date_to_ts(date_to, end=True)

    session = _make_session()
    try:
        resp = session.get(CDX_URL, params=params, timeout=TIMEOUT, headers=_headers())
        resp.raise_for_status()
        rows = resp.json()
    except Exception as e:
        return [{"error": str(e)}]
    finally:
        session.close()

    if not rows or len(rows) <= 1:
        return []

    hdrs    = rows[0]
    entries = [dict(zip(hdrs, r)) for r in rows[1:]]

    result = []
    for e in sorted(entries, key=lambda x: x["timestamp"]):
        root = topic_root_original(e["original"])
        result.append({
            "timestamp":   e["timestamp"],
            "date_human":  _ts_human(e["timestamp"]),
            "original":    root,
            "wayback_url": build_wayback_url(e["timestamp"], root),
        })

    return result


# ── Find best CDX capture for a specific offset URL ──────────────────────────

def find_best_capture_for_offset(original_root: str, offset: int) -> dict | None:
    """
    Query CDX for all captures of this specific offset page and return
    the best one — defined as the capture with the most content
    (we use the one closest to the middle of the archive date range,
    as it's most likely to be a complete snapshot).

    Returns {"timestamp": ..., "wayback_url": ...} or None if not found.
    """
    offset_url = set_offset(original_root, offset)

    params = {
        "url":    offset_url,
        "output": "json",
        "fl":     "timestamp,statuscode",
        "filter": "statuscode:200",
        "limit":  50,
    }

    session = _make_session()
    try:
        resp = session.get(CDX_URL, params=params, timeout=(10, 30), headers=_headers())
        resp.raise_for_status()
        rows = resp.json()
    except Exception:
        return None
    finally:
        session.close()

    if not rows or len(rows) <= 1:
        return None

    hdrs    = rows[0]
    entries = [dict(zip(hdrs, r)) for r in rows[1:]]

    if not entries:
        return None

    # Pick the middle capture — tends to be more complete than oldest or newest
    # (oldest may be partial, newest may have rot)
    mid  = entries[len(entries) // 2]
    ts   = mid["timestamp"]
    return {
        "timestamp":   ts,
        "date_human":  _ts_human(ts),
        "wayback_url": build_wayback_url(ts, offset_url),
        "original":    offset_url,
    }


# ── All captures for a specific page offset ──────────────────────────────────

def discover_captures_for_offset(original_root: str, offset: int) -> list:
    """
    Return all CDX captures for one specific page offset, collapsed to one per day.
    Used to let the user manually pick a capture for a single page.
    """
    offset_url = set_offset(original_root, offset)

    params = {
        "url":      offset_url,
        "output":   "json",
        "fl":       "timestamp,statuscode",
        "filter":   "statuscode:200",
        "collapse": "timestamp:8",   # one entry per calendar day
        "limit":    500,
    }

    session = _make_session()
    try:
        resp = session.get(CDX_URL, params=params, timeout=(10, 30), headers=_headers())
        resp.raise_for_status()
        rows = resp.json()
    except Exception:
        return []
    finally:
        session.close()

    if not rows or len(rows) <= 1:
        return []

    hdrs    = rows[0]
    entries = [dict(zip(hdrs, r)) for r in rows[1:]]

    result = []
    for e in sorted(entries, key=lambda x: x["timestamp"]):
        ts = e["timestamp"]
        result.append({
            "timestamp":   ts,
            "date_human":  _ts_human(ts),
            "wayback_url": build_wayback_url(ts, offset_url),
        })
    return result


# ── Scrape exactly one page at a specific capture timestamp ───────────────────

def scrape_single_page(timestamp: str, original_root: str, offset: int):
    """
    Fetch one page from an exact Wayback capture timestamp.
    Yields SSE-style dicts: status → done (or error).
    """
    offset_orig = set_offset(original_root, offset)
    page_url    = build_wayback_url(timestamp, offset_orig)
    date_human  = _ts_human(timestamp)

    yield {"type": "status", "msg": f"Fetching offset .{offset} from {date_human}…"}

    html = fetch_html(page_url)
    if not html:
        yield {"type": "error",
               "msg": "Could not fetch this capture — Wayback Machine may be slow. Try a different one."}
        return

    title    = parse_thread_title(html)
    posts    = parse_posts(html, page_url, offset)
    topic_id = extract_topic_id(original_root)
    found_offsets = detect_page_offsets(html, topic_id)

    yield {
        "type":          "done",
        "title":         title,
        "posts":         posts,
        "offset":        offset,
        "timestamp":     timestamp,
        "date_human":    date_human,
        "source_url":    page_url,
        "post_count":    len(posts),
        "found_offsets": found_offsets,
    }


# ── Fetch with retry ──────────────────────────────────────────────────────────

def fetch_html(url: str) -> str | None:
    session = _make_session()
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = session.get(url, headers=_headers(), timeout=TIMEOUT)
            r.raise_for_status()
            session.close()
            return r.text
        except requests.exceptions.Timeout:
            if attempt < MAX_RETRIES:
                time.sleep(3 * attempt)
        except requests.exceptions.HTTPError as e:
            code = e.response.status_code if e.response else 0
            if code == 404:
                break
            if attempt < MAX_RETRIES:
                time.sleep(3 * attempt)
        except Exception:
            if attempt < MAX_RETRIES:
                time.sleep(3 * attempt)
    session.close()
    return None


# ── Parse ─────────────────────────────────────────────────────────────────────

def detect_page_offsets(html: str, topic_id: str) -> list:
    soup    = BeautifulSoup(html, "lxml")
    offsets = {0}
    for a in soup.find_all("a", href=True):
        m = re.search(rf"topic={topic_id}\.(\d+)", a["href"])
        if m:
            offsets.add(int(m.group(1)))
    for a in soup.select("a.navPages"):
        m = re.search(r"\.(\d+)", a.get("href", ""))
        if m:
            offsets.add(int(m.group(1)))
    return sorted(offsets)


def parse_thread_title(html: str) -> str:
    """
    Extract the topic title from an SMF 2.x thread page.

    SMF page <title> is always: "Topic Name - Forum Name"
    We want "Topic Name - Forum Name" as the full identifier,
    but fall back to just the topic part if that's all we can find.

    Priority:
      1. #subject_header  — SMF 2.x topic heading div (most reliable)
      2. .navigate_section li:last-child — breadcrumb last item
      3. <title> tag — kept as "Topic - Site" (NOT stripped)
      4. first <h1> that isn't a Wayback toolbar element
    """
    soup = BeautifulSoup(html, "lxml")

    # 1. SMF subject header div — contains only the topic title
    el = soup.select_one("#subject_header")
    if el:
        t = el.get_text(strip=True)
        if t and t != "Unknown Thread":
            return t

    # 2. Breadcrumb last item — usually the topic name
    el = soup.select_one(".navigate_section li:last-child, #nav_breadcrumbs li:last-child")
    if el:
        t = el.get_text(strip=True).strip("» »").strip()
        if t and len(t) > 3:
            return t

    # 3. <title> — SMF format is "Topic Name - Site Name"
    #    Keep the full "Topic - Site" string so it's identifiable
    el = soup.select_one("title")
    if el:
        t = el.get_text(strip=True)
        # Strip Wayback Machine prefix if present: "Topic - Site"
        # Wayback sometimes prepends timestamp like "20151201 - Topic - Site"
        t = re.sub(r"^\d{8,14}\s*[-–]\s*", "", t)
        if t:
            return t

    # 4. First h1 not inside Wayback toolbar
    for h1 in soup.find_all("h1"):
        if h1.find_parent(id=re.compile(r"wm-|wb-", re.I)):
            continue
        t = h1.get_text(strip=True)
        if t and len(t) > 3:
            return t

    return "Unknown Thread"


def parse_posts(html: str, source_url: str, page_offset: int) -> list:
    soup     = BeautifulSoup(html, "lxml")
    posts    = []
    wrappers = soup.select("div.post_wrapper")

    for i, wrapper in enumerate(wrappers):
        msg_el  = wrapper.find(id=re.compile(r"^msg_\d+$"))
        post_id = msg_el["id"].replace("msg_", "") if msg_el else f"auto_{page_offset}_{i}"

        author_el = (wrapper.select_one(".poster h4 a") or
                     wrapper.select_one(".poster h4"))
        author = author_el.get_text(strip=True) if author_el else "Unknown"

        role_el = (wrapper.select_one(".poster .membergroup") or
                   wrapper.select_one(".poster .title"))
        role = role_el.get_text(strip=True) if role_el else ""

        avatar_el  = wrapper.select_one(".poster img.avatar, .poster img")
        avatar_url = avatar_el.get("src", "") if avatar_el else ""

        date_el  = (wrapper.select_one(".postarea .keyinfo .smalltext") or
                    wrapper.select_one(".postinfo"))
        date_raw = date_el.get_text(strip=True) if date_el else ""
        date_raw = re.sub(r"^.*on:\s*", "", date_raw, flags=re.IGNORECASE)

        pnum_el  = wrapper.select_one(".postarea .postinfo b")
        pnum_txt = pnum_el.get_text(strip=True) if pnum_el else ""
        pm       = re.search(r"#(\d+)", pnum_txt)
        global_num = int(pm.group(1)) if pm else (page_offset + i + 1)

        body_el = (wrapper.select_one(".post .inner") or
                   wrapper.select_one("div.post"))
        if body_el:
            for tag in body_el.select("script,#wm-ipp-base,#wm-ipp,.wm-ipp"):
                tag.decompose()
            content = body_el.get_text(separator="\n", strip=True)
        else:
            content = ""

        posts.append({
            "post_id":         post_id,
            "author":          author,
            "author_role":     role,
            "avatar_url":      avatar_url,
            "date_raw":        date_raw,
            "global_post_num": global_num,
            "page_offset":     page_offset,
            "content":         content,
            "word_count":      len(content.split()) if content else 0,
            "source_url":      source_url,
            "is_real":         True,
        })

    return posts


# ── Detect pages only ─────────────────────────────────────────────────────────

def detect_topic_pages(timestamp: str, original_root: str) -> dict:
    root_wb  = build_wayback_url(timestamp, original_root)
    topic_id = extract_topic_id(original_root)

    html = fetch_html(root_wb)
    if not html:
        return {"error": "Could not fetch the first page from Wayback Machine. Try again — it may be a temporary timeout."}

    title   = parse_thread_title(html)
    offsets = detect_page_offsets(html, topic_id)

    return {
        "title":       title,
        "all_offsets": offsets,
        "total_pages": len(offsets),
    }


# ── Scrape a batch of pages ───────────────────────────────────────────────────

def scrape_capture(timestamp: str, original_root: str,
                   all_offsets: list, from_index: int = 0, count: int = 5):
    """
    Scrape a batch of pages. For each page offset:
      - If offset == 0: use the original capture (timestamp passed in)
      - For all other offsets: find the best independent CDX capture
        for that specific offset URL, then fetch that instead.

    This ensures each page is fetched from the most relevant snapshot
    rather than forcing all pages through a single capture's timestamp.
    """
    batch        = all_offsets[from_index: from_index + count]
    title        = None
    all_posts    = []
    failed_pages = []

    # Fetch page 0 from the original capture if it's in this batch
    first_html = None
    if 0 in batch:
        root_wb = build_wayback_url(timestamp, original_root)
        yield {"type": "status", "msg": "Fetching first page from original capture…"}
        first_html = fetch_html(root_wb)
        if not first_html:
            yield {"type": "error", "msg": "Could not fetch the first page. Wayback Machine may be slow — try again."}
            return
        title = parse_thread_title(first_html)

    yield {"type": "batch_start", "from_index": from_index,
           "count": len(batch), "offsets": batch}

    for idx, offset in enumerate(batch):
        global_idx = from_index + idx

        # ── Page 0: use original capture already fetched ──────────
        if offset == 0 and first_html is not None:
            page_html = first_html
            page_url  = build_wayback_url(timestamp, original_root)

        else:
            # ── All other pages: find their own best CDX capture ──
            yield {"type": "page_progress",
                   "index": idx + 1, "total": len(batch),
                   "global_idx": global_idx + 1, "global_tot": len(all_offsets),
                   "offset": offset,
                   "msg": f"Finding best capture for page {global_idx+1}/{len(all_offsets)} (offset .{offset})…"}

            capture = find_best_capture_for_offset(original_root, offset)

            if not capture:
                # Fall back to original timestamp for this offset
                offset_orig = set_offset(original_root, offset)
                page_url    = build_wayback_url(timestamp, offset_orig)
                yield {"type": "page_progress",
                       "index": idx + 1, "total": len(batch),
                       "global_idx": global_idx + 1, "global_tot": len(all_offsets),
                       "offset": offset,
                       "msg": f"No dedicated capture found — trying original snapshot for page {global_idx+1}…"}
            else:
                page_url = capture["wayback_url"]
                yield {"type": "page_progress",
                       "index": idx + 1, "total": len(batch),
                       "global_idx": global_idx + 1, "global_tot": len(all_offsets),
                       "offset": offset,
                       "msg": f"Fetching page {global_idx+1}/{len(all_offsets)} from {capture['date_human']} capture…"}

            page_html = fetch_html(page_url)
            time.sleep(DELAY)

        if not page_html:
            failed_pages.append(offset)
            yield {"type": "page_progress",
                   "index": idx + 1, "total": len(batch),
                   "global_idx": global_idx + 1, "global_tot": len(all_offsets),
                   "offset": offset, "failed": True,
                   "msg": f"⚠ Timed out on page {global_idx+1} (offset .{offset}) — skipping"}
            continue

        if title is None:
            title = parse_thread_title(page_html)

        # Discover any new pagination offsets from this page and expand all_offsets
        topic_id    = extract_topic_id(original_root)
        found_offs  = detect_page_offsets(page_html, topic_id)
        prev_count  = len(all_offsets)
        merged      = sorted(set(all_offsets) | set(found_offs))
        if len(merged) > prev_count:
            all_offsets[:] = merged   # expand in-place so batch slice stays valid
            yield {"type": "offsets_updated",
                   "all_offsets":  all_offsets,
                   "total_pages":  len(all_offsets),
                   "added":        len(all_offsets) - prev_count,
                   "msg": f"📄 Found {len(all_offsets) - prev_count} new page(s) — total now {len(all_offsets)}"}

        posts = parse_posts(page_html, page_url, offset)
        all_posts.extend(posts)

        yield {"type": "page_progress",
               "index": idx + 1, "total": len(batch),
               "global_idx": global_idx + 1, "global_tot": len(all_offsets),
               "offset": offset, "posts_found": len(posts),
               "msg": f"✓ Page {global_idx+1}/{len(all_offsets)}: {len(posts)} posts"}

    seen, unique = set(), []
    for p in all_posts:
        if p["post_id"] not in seen:
            seen.add(p["post_id"])
            unique.append(p)
    unique.sort(key=lambda p: p["global_post_num"])

    next_index = from_index + len(batch)
    yield {
        "type":            "done",
        "title":           title or "Unknown Thread",
        "posts":           unique,
        "batch_pages":     len(batch),
        "failed_pages":    len(failed_pages),
        "total_posts":     len(unique),
        "unique_authors":  len({p["author"] for p in unique}),
        "from_index":      from_index,
        "next_index":      next_index,
        "has_more":        next_index < len(all_offsets),
        "total_pages":     len(all_offsets),
        "all_offsets":     all_offsets,
        "timestamp":       timestamp,
        "date_human":      _ts_human(timestamp),
    }
