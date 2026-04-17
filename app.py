# app.py
import json
import os
import uuid
from datetime import datetime
from flask import Flask, render_template, request, Response, jsonify, stream_with_context
from wayback import (discover_captures, scrape_capture, detect_topic_pages,
                     discover_captures_for_offset, scrape_single_page)

app = Flask(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)


# ── Page routes ───────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/scrape")
def scrape_page():
    timestamp  = request.args.get("ts", "").strip()
    original   = request.args.get("url", "").strip()
    date_human = request.args.get("date", "").strip()
    if not timestamp or not original:
        return "Missing ts or url parameter.", 400
    return render_template("scrape.html",
                           timestamp=timestamp,
                           original=original,
                           date_human=date_human)


@app.route("/view/<save_id>")
def view_page(save_id):
    path = os.path.join(DATA_DIR, f"{save_id}.json")
    if not os.path.exists(path):
        return "Saved scrape not found.", 404
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return render_template("view.html", save_id=save_id, meta=data["meta"])


# ── API: CDX discovery ────────────────────────────────────────────────────────

@app.route("/api/captures", methods=["POST"])
def api_captures():
    data      = request.get_json()
    url       = (data or {}).get("url", "").strip()
    date_from = (data or {}).get("date_from", "").strip()
    date_to   = (data or {}).get("date_to", "").strip()

    if not url or "topic=" not in url:
        return jsonify({"error": "Provide a valid SMF topic URL containing 'topic='."}), 400

    captures = discover_captures(url, date_from=date_from, date_to=date_to)

    if not captures:
        return jsonify({"error": "No archived captures found for this URL and date range."}), 404
    if len(captures) == 1 and "error" in captures[0]:
        return jsonify({"error": captures[0]["error"]}), 500

    return jsonify({"captures": captures})


# ── API: Detect pages (fetches page 0 only) ───────────────────────────────────

@app.route("/api/detect", methods=["POST"])
def api_detect():
    data      = request.get_json()
    timestamp = (data or {}).get("timestamp", "").strip()
    original  = (data or {}).get("original", "").strip()
    if not timestamp or not original:
        return jsonify({"error": "timestamp and original are required."}), 400
    result = detect_topic_pages(timestamp, original)
    if "error" in result:
        return jsonify(result), 500
    return jsonify(result)


# ── API: All captures for one specific page offset ───────────────────────────

@app.route("/api/captures_for_page", methods=["POST"])
def api_captures_for_page():
    data     = request.get_json()
    original = (data or {}).get("original", "").strip()
    offset   = int((data or {}).get("offset", 0))

    if not original:
        return jsonify({"error": "original is required."}), 400

    captures = discover_captures_for_offset(original, offset)
    if not captures:
        return jsonify({"error": "No captures found for this page."}), 404

    return jsonify({"captures": captures, "total": len(captures)})


# ── API: Scrape one page from an exact capture timestamp (SSE) ────────────────

@app.route("/api/scrape_page", methods=["POST"])
def api_scrape_page():
    data      = request.get_json()
    timestamp = (data or {}).get("timestamp", "").strip()
    original  = (data or {}).get("original", "").strip()
    offset    = int((data or {}).get("offset", 0))

    if not timestamp or not original:
        return jsonify({"error": "timestamp and original are required."}), 400

    def generate():
        for event in scrape_single_page(timestamp, original, offset):
            etype = event.pop("type")
            yield f"event: {etype}\ndata: {json.dumps(event)}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


# ── API: Scrape a batch of pages (SSE) ───────────────────────────────────────

@app.route("/api/scrape", methods=["POST"])
def api_scrape():
    data        = request.get_json()
    timestamp   = (data or {}).get("timestamp", "").strip()
    original    = (data or {}).get("original", "").strip()
    all_offsets = (data or {}).get("all_offsets", [])
    from_index  = int((data or {}).get("from_index", 0))
    count       = int((data or {}).get("count", 5))

    if not timestamp or not original or not all_offsets:
        return jsonify({"error": "timestamp, original, and all_offsets are required."}), 400

    def generate():
        for event in scrape_capture(timestamp, original, all_offsets, from_index, count):
            etype = event.pop("type")
            yield f"event: {etype}\ndata: {json.dumps(event)}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


# ── API: Save a new scrape ────────────────────────────────────────────────────

@app.route("/api/save", methods=["POST"])
def api_save():
    body = request.get_json()
    if not body or not body.get("posts"):
        return jsonify({"error": "No posts to save."}), 400

    save_id = uuid.uuid4().hex[:12]
    meta = {
        "id":             save_id,
        "title":          body.get("title", "Unknown Thread"),
        "timestamp":      body.get("timestamp", ""),
        "date_human":     body.get("date_human", ""),
        "original":       body.get("original", ""),
        "total_posts":    len(body["posts"]),
        "pages_scraped":  body.get("pages_scraped", 0),
        "total_pages":    body.get("total_pages", 0),
        "all_offsets":    body.get("all_offsets", []),
        "unique_authors": body.get("unique_authors", 0),
        "saved_at":       datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    payload = {"meta": meta, "posts": body["posts"]}

    path = os.path.join(DATA_DIR, f"{save_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)

    return jsonify({"id": save_id, "url": f"/view/{save_id}"})


# ── API: Append posts to an existing save ────────────────────────────────────

@app.route("/api/saved/<save_id>", methods=["PATCH"])
def api_append(save_id):
    path = os.path.join(DATA_DIR, f"{save_id}.json")
    if not os.path.exists(path):
        return jsonify({"error": "Save not found."}), 404

    body      = request.get_json()
    new_posts = body.get("posts", [])
    if not new_posts:
        return jsonify({"error": "No posts provided."}), 400

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # replace_offset: remove all posts for that page offset, then add fresh ones
    if "replace_offset" in body:
        replace_offset = int(body["replace_offset"])
        data["posts"] = [p for p in data["posts"] if p.get("page_offset") != replace_offset]
        added = new_posts
    else:
        existing_ids = {p["post_id"] for p in data["posts"]}
        added = [p for p in new_posts if p["post_id"] not in existing_ids]
    data["posts"].extend(added)
    data["posts"].sort(key=lambda p: p.get("global_post_num", 0))

    data["meta"]["total_posts"]    = len(data["posts"])
    data["meta"]["pages_scraped"]  = body.get("pages_scraped",  data["meta"].get("pages_scraped", 0))
    data["meta"]["total_pages"]    = body.get("total_pages",    data["meta"].get("total_pages", 0))
    data["meta"]["unique_authors"] = len({p["author"] for p in data["posts"]})
    data["meta"]["saved_at"]       = datetime.now().strftime("%Y-%m-%d %H:%M")
    if body.get("all_offsets"):
        data["meta"]["all_offsets"] = body["all_offsets"]

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)

    return jsonify({"ok": True, "total_posts": data["meta"]["total_posts"], "added": len(added)})


# ── API: List all saved scrapes ───────────────────────────────────────────────

@app.route("/api/saved", methods=["GET"])
def api_saved():
    saves = []
    for fname in sorted(os.listdir(DATA_DIR), reverse=True):
        if not fname.endswith(".json"):
            continue
        try:
            with open(os.path.join(DATA_DIR, fname), "r", encoding="utf-8") as f:
                saves.append(json.load(f)["meta"])
        except Exception:
            pass
    return jsonify({"saves": saves})


# ── API: Load one saved scrape's posts ────────────────────────────────────────

@app.route("/api/saved/<save_id>", methods=["GET"])
def api_saved_detail(save_id):
    path = os.path.join(DATA_DIR, f"{save_id}.json")
    if not os.path.exists(path):
        return jsonify({"error": "Not found."}), 404
    with open(path, "r", encoding="utf-8") as f:
        return jsonify(json.load(f))


# ── API: Delete a saved scrape ────────────────────────────────────────────────

@app.route("/api/saved/<save_id>", methods=["DELETE"])
def api_delete(save_id):
    path = os.path.join(DATA_DIR, f"{save_id}.json")
    if os.path.exists(path):
        os.remove(path)
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(debug=True, threaded=True, host="0.0.0.0", port=5110)
