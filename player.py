#!/usr/bin/env python3
"""
Music Player Server
Serves MP3 files in the current directory with a modern web player UI.
Usage: python3 player.py [port]
"""

import re
import sys
import html
import json
import uuid
import secrets
import threading
import subprocess
import urllib.parse
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from pathlib import Path

MAX_BODY = 64 * 1024  # 64 KB — more than enough for any JSON payload
MAX_DOWNLOADS = 200  # prune old jobs beyond this
MAX_CONCURRENT_DOWNLOADS = 5  # cap simultaneous yt-dlp download processes
MAX_CONCURRENT_SEARCHES = 3  # cap simultaneous yt-dlp search processes
MAX_SEARCH_QUERY_LEN = 200  # sane upper bound for a search query

_download_semaphore = threading.Semaphore(MAX_CONCURRENT_DOWNLOADS)
_search_semaphore = threading.Semaphore(MAX_CONCURRENT_SEARCHES)

MUSIC_DIR = Path(__file__).parent / "musics"
MUSIC_DIR.mkdir(exist_ok=True)
HTML_FILE = Path(__file__).parent / "index.html"
CSS_FILE = Path(__file__).parent / "player.css"
JS_FILE = Path(__file__).parent / "player.js"
PLAY_COUNTS_FILE = Path(__file__).parent / "play_counts.json"
COOKIES_FILE = Path(__file__).parent / "cookies.txt"


def _ytdlp_platform_args() -> list[str]:
    """Return yt-dlp platform-specific arguments.

    macOS: use --cookies-from-browser chrome (reads live Chrome cookies).
    Linux/other: use --cookies <file> + --js-runtimes node + mweb client
    (required for PO Token authentication on headless servers).
    """
    if sys.platform == "darwin":
        return ["--cookies-from-browser", "chrome"]
    args: list[str] = []
    if COOKIES_FILE.exists():
        args += ["--cookies", str(COOKIES_FILE)]
    args += ["--js-runtimes", "node", "--extractor-args", "youtube:player_client=mweb"]
    return args


# job_id -> {"status": "downloading|done|failed", "progress": 0-100, "title": str, "error": str}
DOWNLOADS: dict = {}
_counts_lock = threading.Lock()
_downloads_lock = threading.Lock()


def _load_counts() -> dict:
    if PLAY_COUNTS_FILE.exists():
        try:
            return json.loads(PLAY_COUNTS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_counts(counts: dict) -> None:
    PLAY_COUNTS_FILE.write_text(
        json.dumps(counts, ensure_ascii=False, indent=2), encoding="utf-8"
    )


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

    def version_string(self):
        # Suppress Python version disclosure from the Server response header.
        return "unknown"

    def do_GET(self):
        path = urllib.parse.unquote(self.path.split("?")[0])
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)

        if path == "/" or path == "/index.html":
            nonce = secrets.token_urlsafe(16)
            page = HTML_FILE.read_text(encoding="utf-8").replace("{{NONCE}}", nonce)
            self._serve_bytes(page.encode(), "text/html; charset=utf-8", nonce=nonce)

        elif path == "/player.css":
            self._serve_bytes(CSS_FILE.read_bytes(), "text/css; charset=utf-8")

        elif path == "/player.js":
            self._serve_bytes(
                JS_FILE.read_bytes(), "application/javascript; charset=utf-8"
            )

        elif path == "/favicon.svg":
            svg = (
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
                '<rect width="64" height="64" rx="14" fill="#7c6af7"/>'
                '<text x="32" y="47" font-size="38" text-anchor="middle" fill="#ffffff">♪</text>'
                "</svg>"
            )
            self._serve_bytes(svg.encode(), "image/svg+xml")

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
            if len(query) > MAX_SEARCH_QUERY_LEN:
                self.send_response(400)
                self.end_headers()
                return
            if not _search_semaphore.acquire(blocking=False):
                self.send_response(429)  # Too Many Requests
                self.send_header("Retry-After", "5")
                self.end_headers()
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
                                "thumbnail": f"/api/img-proxy?v={vid_id}",
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
            finally:
                _search_semaphore.release()

        elif path == "/api/img-proxy":
            # Proxy YouTube thumbnail images to bypass network restrictions.
            # Only allows fetching images from i.ytimg.com to prevent SSRF.
            vid_id = qs.get("v", [""])[0]
            if not vid_id or not re.fullmatch(r"[A-Za-z0-9_-]{11}", vid_id):
                self.send_response(400)
                self.end_headers()
                return
            img_url = f"https://i.ytimg.com/vi/{vid_id}/mqdefault.jpg"
            try:
                result = subprocess.run(
                    ["curl", "-s", "-o", "-", "-w", "", img_url],
                    capture_output=True,
                    timeout=10,
                )
                if result.returncode == 0 and result.stdout:
                    self._serve_bytes(result.stdout, "image/jpeg")
                else:
                    self.send_response(502)
                    self.end_headers()
            except Exception:
                self.send_response(502)
                self.end_headers()

        elif path == "/api/download/status":
            job_id = qs.get("id", [""])[0]
            with _downloads_lock:
                job = DOWNLOADS.get(job_id)
                snapshot = dict(job) if job is not None else None
            if snapshot is None:
                self.send_response(404)
                self.end_headers()
                return
            self._serve_bytes(json.dumps(snapshot).encode(), "application/json")

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
            try:
                length = int(self.headers.get("Content-Length", 0))
            except ValueError:
                self.send_response(400)
                self.end_headers()
                return
            if length < 0 or length > MAX_BODY:
                self.send_response(413)
                self.end_headers()
                return
            try:
                body = json.loads(self.rfile.read(length))
            except (json.JSONDecodeError, ValueError):
                self.send_response(400)
                self.end_headers()
                return

            # Accept integer index into the server-side track list — never a raw
            # filename from the client, which would allow path traversal attacks.
            # Strict type check: reject floats, booleans, and strings even though
            # Python's int() would silently coerce them (int(1.5)→1, int(True)→1,
            # int("0")→0). JSON booleans map to Python bool which is a subclass of
            # int, so we must explicitly exclude bool first.
            idx = body.get("index")
            if not isinstance(idx, int) or isinstance(idx, bool):
                self.send_response(400)
                self.end_headers()
                return

            # Rebuild track list with the same sort key used by /api/tracks so
            # that the index the frontend holds matches what we resolve here.
            # NOTE: capture index before any subsequent /api/tracks refresh on
            # the frontend — the index must refer to the pre-refresh list.
            counts = _load_counts()
            mp3_files = sorted(
                [f for f in MUSIC_DIR.iterdir() if f.suffix.lower() == ".mp3"],
                key=lambda f: (-counts.get(f.stem, 0), f.name.lower()),
            )
            if idx < 0 or idx >= len(mp3_files):
                self.send_response(404)
                self.end_headers()
                return

            stem = mp3_files[idx].stem
            new_count = _increment_play(stem)
            self._serve_bytes(
                json.dumps({"plays": new_count}).encode(), "application/json"
            )
            return

        if path != "/api/download":
            self._404()
            return

        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            self.send_response(400)
            self.end_headers()
            return
        if length < 0 or length > MAX_BODY:
            self.send_response(413)
            self.end_headers()
            return
        try:
            body = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, ValueError):
            self.send_response(400)
            self.end_headers()
            return
        url = body.get("url", "")
        title = str(body.get("title", "track") or "track")
        # Sanitise: strip C0/C1 control characters, cap length to prevent
        # unbounded memory growth, then HTML-escape so the value is safe if
        # it is ever rendered via innerHTML on the frontend.
        title = "".join(c for c in title if c >= " " or c == "\t")[:300] or "track"
        title = html.escape(title, quote=True)

        # Validate: only YouTube URLs allowed (prevent SSRF).
        # Use proper URL parsing instead of startswith() — a raw string prefix
        # check is bypassed by the RFC 3986 userinfo trick:
        #   https://www.youtube.com/watch?v=ID@evil.com/  → host is evil.com
        try:
            parsed = urllib.parse.urlparse(url)
        except Exception:
            parsed = None
        if (
            not parsed
            or parsed.scheme != "https"
            or parsed.hostname not in ("www.youtube.com", "youtu.be")
            or parsed.username is not None  # reject any userinfo / @ component
            or parsed.password is not None
        ):
            self.send_response(400)
            self.end_headers()
            return

        job_id = str(uuid.uuid4())
        with _downloads_lock:
            DOWNLOADS[job_id] = {
                "status": "downloading",
                "progress": 0,
                "title": title,
                "error": "",
            }

        def run():
            if not _download_semaphore.acquire(blocking=False):
                # Individual field updates in the worker thread rely on the GIL
                # for atomicity; compound read-modify operations use _downloads_lock.
                DOWNLOADS[job_id]["status"] = "failed"
                DOWNLOADS[job_id]["error"] = (
                    "Too many concurrent downloads; try again later."
                )
                return
            try:
                proc = subprocess.Popen(
                    [
                        "yt-dlp",
                        *_ytdlp_platform_args(),
                        "-x",
                        "--audio-format",
                        "mp3",
                        "--no-playlist",
                        "--newline",
                        "-o",
                        str(MUSIC_DIR / "%(title)s.%(ext)s"),
                        url,
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                last_lines: list[str] = []
                for line in proc.stdout:
                    line = line.strip()
                    if not line:
                        continue
                    last_lines = (last_lines + [line])[-10:]
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
                    err_detail = next(
                        (l for l in reversed(last_lines) if "ERROR:" in l),
                        last_lines[-1] if last_lines else "yt-dlp exited with error",
                    )
                    DOWNLOADS[job_id]["status"] = "failed"
                    DOWNLOADS[job_id]["error"] = err_detail
            except Exception as exc:
                DOWNLOADS[job_id]["status"] = "failed"
                DOWNLOADS[job_id]["error"] = str(exc)
            finally:
                _download_semaphore.release()

        threading.Thread(target=run, daemon=True).start()

        # Prune jobs to stay within MAX_DOWNLOADS: prefer evicting done/failed first,
        # then oldest downloading jobs if still over the cap.
        with _downloads_lock:
            if len(DOWNLOADS) > MAX_DOWNLOADS:
                overflow = len(DOWNLOADS) - MAX_DOWNLOADS
                # evict finished jobs first (safe to drop)
                evict = [
                    k for k, v in DOWNLOADS.items() if v["status"] in ("done", "failed")
                ]
                # if still not enough, evict oldest in-progress too
                if len(evict) < overflow:
                    in_progress = [k for k in DOWNLOADS if k not in set(evict)]
                    evict += in_progress[: overflow - len(evict)]
                for k in evict[:overflow]:
                    del DOWNLOADS[k]

        self._serve_bytes(json.dumps({"id": job_id}).encode(), "application/json")

    def _security_headers(self, nonce: str | None = None):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        # Nonce-based CSP: JS and CSS are served as external files, so no
        # 'unsafe-inline' is needed.  The per-request nonce must match the
        # nonce attribute on the <link> and <script> elements in index.html.
        if nonce:
            nonce_src = f"'nonce-{nonce}'"
            csp = (
                f"default-src 'self'; "
                f"img-src 'self' data:; "
                f"media-src 'self'; "
                f"script-src 'self' {nonce_src}; "
                f"style-src 'self' {nonce_src}; "
                f"connect-src 'self';"
            )
        else:
            csp = (
                "default-src 'self'; "
                "img-src 'self' data:; "
                "media-src 'self'; "
                "script-src 'self'; "
                "style-src 'self'; "
                "connect-src 'self';"
            )
        self.send_header("Content-Security-Policy", csp)

    def _serve_bytes(self, data: bytes, content_type: str, nonce: str | None = None):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self._security_headers(nonce=nonce)
        self.end_headers()
        self.wfile.write(data)

    def _serve_file(self, path, content_type):
        size = path.stat().st_size
        # Support range requests for audio seeking
        range_header = self.headers.get("Range")
        if range_header:
            start, end = 0, size - 1
            # Reject multi-range (we only support a single range)
            range_spec = range_header.replace("bytes=", "").strip()
            if "," in range_spec:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            try:
                parts = range_spec.split("-", 1)
                if parts[0]:
                    # Normal range: bytes=START-[END]
                    start = int(parts[0])
                    if parts[1]:
                        end = int(parts[1])
                else:
                    # Suffix range: bytes=-N  →  last N bytes
                    suffix = int(parts[1])
                    start = max(0, size - suffix)
                    end = size - 1
            except (ValueError, IndexError):
                # Malformed Range header — not satisfiable
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            # Clamp to valid byte positions and reject unsatisfiable ranges
            start = max(0, start)
            end = min(size - 1, end)
            if start > end:
                self.send_response(416)  # Range Not Satisfiable
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            length = end - start + 1
            self.send_response(206)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Content-Length", str(length))
            self.send_header("Accept-Ranges", "bytes")
            self._security_headers()
            self.end_headers()
            with open(path, "rb") as f:
                f.seek(start)
                self.wfile.write(f.read(length))
        else:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(size))
            self.send_header("Accept-Ranges", "bytes")
            self._security_headers()
            self.end_headers()
            with open(path, "rb") as f:
                self.wfile.write(f.read())

    def _404(self):
        self.send_response(404)
        self.end_headers()


def _register_service(port: int):
    """Fire-and-forget service registration. All errors are silently ignored."""
    try:
        payload = json.dumps(
            {
                "name": "any-music",
                "url": f"http://localhost:{port}",
                "description": "Local music player and YouTube downloader",
            }
        ).encode()
        req = urllib.request.Request(
            "http://localhost:1234/services",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5):
            pass
    except Exception:
        pass  # registration is best-effort; never disturb startup


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8888
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    threading.Thread(target=_register_service, args=(port,), daemon=True).start()
    print(f"Music Player running at http://localhost:{port}")
    print(f"Serving MP3s from: {MUSIC_DIR}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
