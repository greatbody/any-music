#!/usr/bin/env python3
"""Live attack test suite. Run while player.py is serving on port 8888."""

import http.client, json, threading, urllib.parse, time

HOST, PORT = "localhost", 8888
CLEAN = "Be%20What%20You%20Wanna%20Be.mp3"  # URL-safe name


def req(method, path, body=None, extra_headers=None):
    conn = http.client.HTTPConnection(HOST, PORT, timeout=5)
    h = {}
    if extra_headers:
        h.update(extra_headers)
    if body is not None:
        if isinstance(body, dict):
            body = json.dumps(body).encode()
        if "Content-Length" not in h:
            h["Content-Length"] = str(len(body))
        h.setdefault("Content-Type", "application/json")
        conn.request(method, path, body=body, headers=h)
    else:
        conn.request(method, path, headers=h)
    r = conn.getresponse()
    data = r.read()
    hdrs = dict(r.getheaders())
    conn.close()
    return r.status, data, hdrs


results = []

# ── 1. Negative Content-Length ──
s, d, _ = req("POST", "/api/played", body=b"", extra_headers={"Content-Length": "-1"})
results.append(
    f"[PASS] [1] Negative Content-Length -> {s}"
    if s == 413
    else f"[FAIL] [1] Negative Content-Length -> {s} (want 413)"
)

# ── 2. Non-integer Content-Length ──
s, d, _ = req("POST", "/api/played", body=b"", extra_headers={"Content-Length": "abc"})
results.append(
    f"[PASS] [2] Non-int Content-Length -> {s}"
    if s == 400
    else f"[FAIL] [2] Non-int Content-Length -> {s} (want 400)"
)

# ── 3. Malformed JSON ──
s, d, _ = req(
    "POST", "/api/played", body=b"not-json", extra_headers={"Content-Length": "8"}
)
results.append(
    f"[PASS] [3] Malformed JSON -> {s}"
    if s == 400
    else f"[FAIL] [3] Malformed JSON -> {s} (want 400)"
)

# ── 4. Oversized body (65 KB) ──
try:
    big = b'{"index":0}' + b"A" * 66000
    s, d, _ = req("POST", "/api/played", body=big)
    results.append(
        f"[PASS] [4] Oversized body -> {s}"
        if s == 413
        else f"[FAIL] [4] Oversized body -> {s} (want 413)"
    )
except Exception as e:
    results.append(
        f"[INFO] [4] Oversized body -> connection reset (server correctly closed early): {e}"
    )

# ── 5a. Range: out-of-bounds (should clamp to file size) ──
s, d, h = req("GET", f"/music/{CLEAN}", extra_headers={"Range": "bytes=0-9999999999"})
cr = h.get("Content-Range", "")
results.append(
    f"[PASS] [5a] Range out-of-bounds clamped -> {s} {cr}"
    if s == 206 and "9999999999" not in cr
    else f"[FAIL] [5a] Range out-of-bounds -> {s} {cr} (want 206 clamped)"
)

# ── 5b. Range: start > end (must return 416) ──
s, d, h = req("GET", f"/music/{CLEAN}", extra_headers={"Range": "bytes=9999999-0"})
results.append(
    f"[PASS] [5b] Inverted range -> {s}"
    if s == 416
    else f"[FAIL] [5b] Inverted range -> {s} (want 416)"
)

# ── 6. Path traversal (single-encode) ──
s, d, _ = req("GET", "/music/..%2Fplayer.py")
results.append(
    f"[PASS] [6] Path traversal single-enc -> {s}"
    if s == 404
    else f"[FAIL] [6] Path traversal single-enc -> {s} (want 404)"
)

# ── 7. Path traversal (double-encode) ──
s, d, _ = req("GET", "/music/%252e%252e%252fplayer.py")
results.append(
    f"[PASS] [7] Path traversal double-enc -> {s}"
    if s == 404
    else f"[FAIL] [7] Path traversal double-enc -> {s} (want 404)"
)

# ── 8. SSRF: @ in query string — NOT a real bypass ──
# urlparse("https://www.youtube.com/watch?v=VALID@evil.com/x") parses hostname
# as "www.youtube.com" and username as None — the @ is just a query-string
# character here, not RFC 3986 userinfo. This URL is harmless and correctly
# accepted (200). A real userinfo trick (https://evil@www.youtube.com/) would
# set parsed.username and be rejected by the username-is-not-None check.
evil_url = "https://www.youtube.com/watch?v=VALID@evil.com/x"
s, d, _ = req("POST", "/api/download", body={"url": evil_url, "title": "t"})
results.append(
    f"[PASS] [8] @ in query string accepted (harmless) -> {s}"
    if s == 200
    else f"[FAIL] [8] unexpected status -> {s}"
)

# ── 8c. SSRF: real RFC 3986 userinfo bypass (evil@www.youtube.com) ──
# urlparse sets parsed.username = "evil", which triggers the username-is-not-None
# guard and must be rejected.
s, d, _ = req(
    "POST",
    "/api/download",
    body={"url": "https://evil@www.youtube.com/watch?v=x", "title": "t"},
)
results.append(
    f"[PASS] [8c] SSRF userinfo bypass rejected -> {s}"
    if s == 400
    else f"[FAIL] [8c] SSRF userinfo bypass accepted -> {s}"
)

# ── 8b. SSRF: subdomain trick ──
s, d, _ = req(
    "POST",
    "/api/download",
    body={"url": "https://www.youtube.com.evil.com/watch?v=x", "title": "t"},
)
results.append(
    f"[PASS] [8b] SSRF subdomain trick -> {s}"
    if s == 400
    else f"[FAIL] [8b] SSRF subdomain -> {s}"
)

# ── 9. Security headers ──
s, d, h = req("GET", "/")
for hdr in (
    "x-content-type-options",
    "x-frame-options",
    "content-security-policy",
    "referrer-policy",
):
    val = h.get(hdr, h.get(hdr.title()))
    results.append(f"[PASS] [9] {hdr}: {val}" if val else f"[FAIL] [9] {hdr}: MISSING")

# ── 10. Download semaphore: 8 simultaneous downloads, only 5 should proceed ──
yt = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
statuses10 = []


def dl10(i):
    s2, d2, _ = req("POST", "/api/download", body={"url": yt, "title": f"t{i}"})
    statuses10.append((i, json.loads(d2).get("id", "?")))


threads10 = [threading.Thread(target=dl10, args=(i,)) for i in range(8)]
for t in threads10:
    t.start()
for t in threads10:
    t.join()
time.sleep(0.3)
rejected = 0
for i, jid in statuses10:
    s2, d2, _ = req("GET", f"/api/download/status?id={jid}")
    job = json.loads(d2)
    if job.get("status") == "failed" and "concurrent" in job.get("error", ""):
        rejected += 1
results.append(
    f"[PASS] [10] Semaphore: {rejected}/8 rejected (expected 3)"
    if rejected >= 3
    else f"[FAIL] [10] Semaphore: only {rejected}/8 rejected"
)

# ── 11. /api/played: index out of range ──
s, d, _ = req("POST", "/api/played", body={"index": 99999})
results.append(
    f"[PASS] [11] played index OOB -> {s}"
    if s == 404
    else f"[FAIL] [11] played index OOB -> {s} (want 404)"
)

# ── 12. /api/played: non-integer index (path traversal attempt) ──
s, d, _ = req("POST", "/api/played", body={"index": "../../etc/passwd"})
results.append(
    f"[PASS] [12] played index non-int -> {s}"
    if s == 400
    else f"[FAIL] [12] played index non-int -> {s} (want 400)"
)

# ── 13. /api/played: negative index ──
s, d, _ = req("POST", "/api/played", body={"index": -1})
results.append(
    f"[PASS] [13] played index negative -> {s}"
    if s == 404
    else f"[FAIL] [13] played index negative -> {s} (want 404)"
)

# ── 14. title field truncation ──
_body_14 = json.dumps(
    {"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "title": "B" * 5000}
).encode()
s14, d14, _ = req(
    "POST",
    "/api/download",
    body=_body_14,
    extra_headers={"Content-Length": str(len(_body_14))},
)
_job_id_14 = json.loads(d14).get("id", "")
time.sleep(0.3)
s_st, d_st, _ = req("GET", f"/api/download/status?id={_job_id_14}")
_title_len = len(json.loads(d_st).get("title", ""))
results.append(
    f"[PASS] [14] title truncated to {_title_len} chars"
    if _title_len <= 300
    else f"[FAIL] [14] title too long: {_title_len}"
)

print("\n".join(results))
