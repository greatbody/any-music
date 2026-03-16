#!/usr/bin/env python3
"""
Music Player Server
Serves MP3 files in the current directory with a modern web player UI.
Usage: python3 player.py [port]
"""

import sys
import json
import uuid
import threading
import subprocess
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from pathlib import Path

MAX_BODY = 64 * 1024  # 64 KB — more than enough for any JSON payload
MAX_DOWNLOADS = 200   # prune old jobs beyond this

MUSIC_DIR = Path(__file__).parent / "musics"
MUSIC_DIR.mkdir(exist_ok=True)
HTML_FILE = Path(__file__).parent / "index.html"
PLAY_COUNTS_FILE = Path(__file__).parent / "play_counts.json"

# job_id -> {"status": "downloading|done|failed", "progress": 0-100, "title": str, "error": str}
DOWNLOADS: dict = {}
_counts_lock = threading.Lock()


def _load_counts() -> dict:
    if PLAY_COUNTS_FILE.exists():
        try:
            return json.loads(PLAY_COUNTS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_counts(counts: dict) -> None:
    PLAY_COUNTS_FILE.write_text(json.dumps(counts, ensure_ascii=False, indent=2), encoding="utf-8")


def _increment_play(stem: str) -> int:
    with _counts_lock:
        counts = _load_counts()
        counts[stem] = counts.get(stem, 0) + 1
        _save_counts(counts)
        return counts[stem]


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # silence access logs

    def do_GET(self):
        path = urllib.parse.unquote(self.path.split("?")[0])
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)

        if path == "/" or path == "/index.html":
            html = HTML_FILE.read_text(encoding="utf-8")
            self._serve_bytes(html.encode(), "text/html; charset=utf-8")

        elif path == "/api/tracks":
            counts = _load_counts()
            mp3_files = sorted(
                [f for f in MUSIC_DIR.iterdir() if f.suffix.lower() == ".mp3"],
                key=lambda f: (-counts.get(f.stem, 0), f.name.lower()),
            )
            tracks = [
                {
                    "name": f.stem,
                    "src": "/music/" + urllib.parse.quote(f.name),
                    "plays": counts.get(f.stem, 0),
                }
                for f in mp3_files
            ]
            body = json.dumps(tracks).encode()
            self._serve_bytes(body, "application/json")

        elif path == "/api/search":
            query = qs.get("q", [""])[0].strip()
            if not query:
                self._serve_bytes(b"[]", "application/json")
                return
            try:
                result = subprocess.run(
                    [
                        "yt-dlp",
                        "--dump-json",
                        "--flat-playlist",
                        "--no-warnings",
                        f"ytsearch8:{query}",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=20,
                )
                items = []
                for line in result.stdout.strip().splitlines():
                    try:
                        d = json.loads(line)
                        vid_id = d.get("id", "")
                        items.append(
                            {
                                "id": vid_id,
                                "title": d.get("title", ""),
                                "url": f"https://www.youtube.com/watch?v={vid_id}",
                                "duration": d.get("duration"),
                                "channel": d.get("channel") or d.get("uploader", ""),
                                "thumbnail": f"https://i.ytimg.com/vi/{vid_id}/mqdefault.jpg",
                            }
                        )
                    except Exception:
                        pass
                self._serve_bytes(json.dumps(items).encode(), "application/json")
            except subprocess.TimeoutExpired:
                self._serve_bytes(b"[]", "application/json")
            except FileNotFoundError:
                self._serve_bytes(
                    json.dumps({"error": "yt-dlp not found"}).encode(),
                    "application/json",
                )

        elif path == "/api/download/status":
            job_id = qs.get("id", [""])[0]
            job = DOWNLOADS.get(job_id)
            if job is None:
                self.send_response(404)
                self.end_headers()
                return
            self._serve_bytes(json.dumps(job).encode(), "application/json")

        elif path.startswith("/music/"):
            filename = urllib.parse.unquote(path[7:])
            filepath = (MUSIC_DIR / filename).resolve()
            if (
                filepath.is_relative_to(MUSIC_DIR.resolve())
                and filepath.exists()
                and filepath.suffix.lower() == ".mp3"
            ):
                self._serve_file(filepath, "audio/mpeg")
            else:
                self._404()
        else:
            self._404()

    def do_POST(self):
        path = urllib.parse.unquote(self.path.split("?")[0])

        if path == "/api/played":
            length = int(self.headers.get("Content-Length", 0))
            if length > MAX_BODY:
                self.send_response(413)
                self.end_headers()
                return
            body = json.loads(self.rfile.read(length))
            stem = body.get("name", "").strip()
            # Validate the name corresponds to an actual file on disk
            if not stem or not (MUSIC_DIR / (stem + ".mp3")).exists():
                self.send_response(404)
                self.end_headers()
                return
            new_count = _increment_play(stem)
            self._serve_bytes(json.dumps({"plays": new_count}).encode(), "application/json")
            return

        if path != "/api/download":
            self._404()
            return

        length = int(self.headers.get("Content-Length", 0))
        if length > MAX_BODY:
            self.send_response(413)
            self.end_headers()
            return
        body = json.loads(self.rfile.read(length))
        url = body.get("url", "")
        title = body.get("title", "track")

        # Validate: only YouTube URLs allowed (prevent SSRF)
        allowed = ("https://www.youtube.com/watch?v=", "https://youtu.be/")
        if not any(url.startswith(p) for p in allowed):
            self.send_response(400)
            self.end_headers()
            return

        job_id = str(uuid.uuid4())
        DOWNLOADS[job_id] = {"status": "downloading", "progress": 0, "title": title, "error": ""}

        def run():
            try:
                proc = subprocess.Popen(
                    [
                        "yt-dlp",
                        "--cookies-from-browser", "chrome",
                        "-x", "--audio-format", "mp3",
                        "--no-playlist",
                        "--newline",
                        "-o", str(MUSIC_DIR / "%(title)s.%(ext)s"),
                        url,
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                for line in proc.stdout:
                    line = line.strip()
                    if "[download]" in line and "%" in line:
                        try:
                            pct = float(line.split("%")[0].split()[-1])
                            DOWNLOADS[job_id]["progress"] = round(pct, 1)
                        except Exception:
                            pass
                proc.wait()
                if proc.returncode == 0:
                    DOWNLOADS[job_id]["status"] = "done"
                    DOWNLOADS[job_id]["progress"] = 100
                else:
                    DOWNLOADS[job_id]["status"] = "failed"
                    DOWNLOADS[job_id]["error"] = "yt-dlp exited with error"
            except Exception as exc:
                DOWNLOADS[job_id]["status"] = "failed"
                DOWNLOADS[job_id]["error"] = str(exc)

        threading.Thread(target=run, daemon=True).start()

        # Prune jobs to stay within MAX_DOWNLOADS: prefer evicting done/failed first,
        # then oldest downloading jobs if still over the cap.
        with _counts_lock:
            if len(DOWNLOADS) > MAX_DOWNLOADS:
                overflow = len(DOWNLOADS) - MAX_DOWNLOADS
                # evict finished jobs first (safe to drop)
                evict = [k for k, v in DOWNLOADS.items() if v["status"] in ("done", "failed")]
                # if still not enough, evict oldest in-progress too
                if len(evict) < overflow:
                    in_progress = [k for k in DOWNLOADS if k not in set(evict)]
                    evict += in_progress[:overflow - len(evict)]
                for k in evict[:overflow]:
                    del DOWNLOADS[k]

        self._serve_bytes(json.dumps({"id": job_id}).encode(), "application/json")

    def _serve_bytes(self, data, content_type):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", len(data))
        self.end_headers()
        self.wfile.write(data)

    def _serve_file(self, path, content_type):
        size = path.stat().st_size
        # Support range requests for audio seeking
        range_header = self.headers.get("Range")
        if range_header:
            start, end = 0, size - 1
            try:
                r = range_header.replace("bytes=", "").split("-")
                if r[0]:
                    start = int(r[0])
                if r[1]:
                    end = int(r[1])
            except Exception:
                pass
            length = end - start + 1
            self.send_response(206)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Content-Length", length)
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            with open(path, "rb") as f:
                f.seek(start)
                self.wfile.write(f.read(length))
        else:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", size)
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            with open(path, "rb") as f:
                self.wfile.write(f.read())

    def _404(self):
        self.send_response(404)
        self.end_headers()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8888
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"Music Player running at http://localhost:{port}")
    print(f"Serving MP3s from: {MUSIC_DIR}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
