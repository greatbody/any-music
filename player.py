#!/usr/bin/env python3
"""
Music Player Server
Serves MP3 files in the current directory with a modern web player UI.
Usage: python3 player.py [port]
"""

import os
import sys
import json
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

MUSIC_DIR = Path(__file__).parent

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
<title>Music Player</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }

  :root {
    --bg: #0f0f13;
    --surface: #1a1a24;
    --surface2: #22223a;
    --accent: #7c6af7;
    --accent2: #a78bfa;
    --text: #f0f0f5;
    --muted: #6b6b8a;
    --border: #2a2a3d;
  }

  body {
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    height: 100vh;
    height: 100dvh;
    overflow: hidden;
    display: flex;
    flex-direction: column;
    padding-bottom: 16px;
  }

  /* ── Header ── */
  header {
    padding: 5px 20px 0;
    text-align: center;
  }
  header h1 {
    font-size: 1.1rem;
    font-weight: 600;
    color: var(--muted);
    letter-spacing: 0.15em;
    text-transform: uppercase;
  }
  #track-count {
    font-size: 0.78rem;
    color: var(--muted);
    margin-top: 4px;
  }

  /* ── Now Playing card ── */
  #now-playing {
    margin: 10px 16px 0;
    background: var(--surface);
    border-radius: 20px;
    padding: 20px;
    border: 1px solid var(--border);
  }

  #album-art {
    width: 80px;
    height: 80px;
    border-radius: 50%;
    background: linear-gradient(135deg, var(--accent), #4f46e5);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 2rem;
    margin: 0 auto 16px;
    box-shadow: 0 8px 32px rgba(124,106,247,0.35);
    transition: transform 0.3s;
  }
  #album-art.playing { animation: spin-slow 8s linear infinite; }
  @keyframes spin-slow { to { transform: rotate(360deg); } }

  #track-title {
    font-size: 1rem;
    font-weight: 600;
    text-align: center;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    margin-bottom: 4px;
  }
  #track-subtitle {
    font-size: 0.78rem;
    color: var(--muted);
    text-align: center;
    margin-bottom: 16px;
  }

  /* Progress */
  #progress-wrap {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 18px;
  }
  #progress-wrap span { font-size: 0.72rem; color: var(--muted); min-width: 34px; }
  #progress-wrap span:last-child { text-align: right; }
  #progress {
    flex: 1;
    -webkit-appearance: none;
    appearance: none;
    height: 4px;
    border-radius: 2px;
    background: var(--border);
    outline: none;
    cursor: pointer;
  }
  #progress::-webkit-slider-thumb {
    -webkit-appearance: none;
    width: 14px; height: 14px;
    border-radius: 50%;
    background: var(--accent2);
    cursor: pointer;
  }

  /* Controls */
  #controls {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 20px;
  }
  .ctrl-btn {
    background: none;
    border: none;
    color: var(--muted);
    cursor: pointer;
    padding: 6px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: color 0.2s;
    font-size: 1.1rem;
  }
  .ctrl-btn:hover { color: var(--text); }
  .ctrl-btn.active { color: var(--accent2); }
  #play-btn {
    width: 54px; height: 54px;
    background: var(--accent);
    color: white;
    font-size: 1.3rem;
    box-shadow: 0 4px 20px rgba(124,106,247,0.45);
    transition: background 0.2s, transform 0.1s;
  }
  #play-btn:hover { background: var(--accent2); transform: scale(1.05); }
  #play-btn:active { transform: scale(0.96); }

  /* Volume */
  #volume-row {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-top: 14px;
  }
  #volume-row svg { color: var(--muted); flex-shrink: 0; }
  #volume {
    flex: 1;
    -webkit-appearance: none;
    appearance: none;
    height: 4px;
    border-radius: 2px;
    background: var(--border);
    outline: none;
    cursor: pointer;
  }
  #volume::-webkit-slider-thumb {
    -webkit-appearance: none;
    width: 13px; height: 13px;
    border-radius: 50%;
    background: var(--muted);
    cursor: pointer;
  }

  /* ── Search ── */
  #search-wrap {
    margin: 16px 16px 0;
    position: relative;
  }
  #search-wrap svg {
    position: absolute;
    left: 14px;
    top: 50%;
    transform: translateY(-50%);
    color: var(--muted);
    pointer-events: none;
  }
  #search {
    width: 100%;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 10px 14px 10px 40px;
    color: var(--text);
    font-size: 0.88rem;
    outline: none;
    transition: border-color 0.2s;
  }
  #search:focus { border-color: var(--accent); }
  #search::placeholder { color: var(--muted); }

  /* ── Track list ── */
  #playlist-wrap {
    flex: 1;
    overflow-y: auto;
    margin: 12px 16px 0;
    margin-bottom: 0;
    border-radius: 16px;
    background: var(--surface);
    border: 1px solid var(--border);
    min-height: 0;
  }
  #playlist { list-style: none; }
  .track-item {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 11px 14px;
    cursor: pointer;
    border-bottom: 1px solid var(--border);
    transition: background 0.15s;
  }
  .track-item:last-child { border-bottom: none; }
  .track-item:hover { background: var(--surface2); }
  .track-item.active {
    background: rgba(124,106,247,0.12);
  }
  .track-num {
    width: 22px;
    text-align: center;
    font-size: 0.75rem;
    color: var(--muted);
    flex-shrink: 0;
  }
  .track-item.active .track-num { display: none; }
  .track-playing-icon {
    display: none;
    width: 22px;
    flex-shrink: 0;
    justify-content: center;
  }
  .track-item.active .track-playing-icon { display: flex; }
  .track-playing-icon svg { color: var(--accent2); }
  .track-info { flex: 1; min-width: 0; }
  .track-name {
    font-size: 0.88rem;
    font-weight: 500;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    color: var(--text);
  }
  .track-item.active .track-name { color: var(--accent2); }
  .track-dur {
    font-size: 0.72rem;
    color: var(--muted);
    flex-shrink: 0;
  }

  /* scrollbar */
  #playlist-wrap::-webkit-scrollbar { width: 4px; }
  #playlist-wrap::-webkit-scrollbar-track { background: transparent; }
  #playlist-wrap::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }

  /* pull-to-refresh indicator */
  #ptr-indicator {
    position: fixed;
    top: 0;
    left: 50%;
    transform: translateX(-50%) translateY(-60px);
    width: 36px;
    height: 36px;
    border-radius: 50%;
    background: var(--surface);
    border: 1px solid var(--border);
    display: flex;
    align-items: center;
    justify-content: center;
    transition: transform 0.2s ease, opacity 0.2s ease;
    opacity: 0;
    z-index: 100;
    box-shadow: 0 2px 12px rgba(0,0,0,0.4);
  }
  #ptr-indicator.visible {
    opacity: 1;
  }
  #ptr-indicator.refreshing svg {
    animation: ptr-spin 0.8s linear infinite;
  }
  @keyframes ptr-spin { to { transform: rotate(360deg); } }
</style>
</head>
<body>

<div id="ptr-indicator">
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--accent2)" stroke-width="2.5" stroke-linecap="round">
    <path d="M21 12a9 9 0 1 1-6.219-8.56"/>
  </svg>
</div>

<header>
  <h1>♪ Music</h1>
  <div id="track-count">Loading…</div>
</header>

<div id="now-playing">
  <div id="album-art">♪</div>
  <div id="track-title">Select a track</div>
  <div id="track-subtitle">—</div>

  <div id="progress-wrap">
    <span id="cur-time">0:00</span>
    <input type="range" id="progress" min="0" max="100" value="0" step="0.1">
    <span id="dur-time">0:00</span>
  </div>

  <div id="controls">
    <button class="ctrl-btn" id="shuffle-btn" title="Shuffle">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="16 3 21 3 21 8"/><line x1="4" y1="20" x2="21" y2="3"/>
        <polyline points="21 16 21 21 16 21"/><line x1="15" y1="15" x2="21" y2="21"/>
      </svg>
    </button>
    <button class="ctrl-btn" id="prev-btn" title="Previous">
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <polygon points="19 20 9 12 19 4 19 20"/><line x1="5" y1="19" x2="5" y2="5"/>
      </svg>
    </button>
    <button class="ctrl-btn" id="play-btn" title="Play/Pause">
      <svg id="play-icon" width="22" height="22" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>
      <svg id="pause-icon" width="22" height="22" viewBox="0 0 24 24" fill="currentColor" style="display:none"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>
    </button>
    <button class="ctrl-btn" id="next-btn" title="Next">
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <polygon points="5 4 15 12 5 20 5 4"/><line x1="19" y1="5" x2="19" y2="19"/>
      </svg>
    </button>
    <button class="ctrl-btn" id="repeat-btn" title="Repeat">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="17 1 21 5 17 9"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/>
        <polyline points="7 23 3 19 7 15"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/>
      </svg>
    </button>
  </div>

  <div id="volume-row">
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/></svg>
    <input type="range" id="volume" min="0" max="1" step="0.02" value="0.8">
  </div>
</div>

<div id="search-wrap">
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
  <input type="text" id="search" placeholder="Search tracks…">
</div>

<div id="playlist-wrap">
  <ul id="playlist"></ul>
</div>

<audio id="audio"></audio>

<script>
const audio = document.getElementById('audio');
const playBtn = document.getElementById('play-btn');
const playIcon = document.getElementById('play-icon');
const pauseIcon = document.getElementById('pause-icon');
const progress = document.getElementById('progress');
const curTime = document.getElementById('cur-time');
const durTime = document.getElementById('dur-time');
const volumeSlider = document.getElementById('volume');
const trackTitle = document.getElementById('track-title');
const trackSubtitle = document.getElementById('track-subtitle');
const albumArt = document.getElementById('album-art');
const playlist = document.getElementById('playlist');
const searchInput = document.getElementById('search');
const shuffleBtn = document.getElementById('shuffle-btn');
const repeatBtn = document.getElementById('repeat-btn');

let tracks = [];
let filtered = [];
let currentIndex = -1;
let shuffle = false;
let repeat = false;

function fmt(s) {
  if (!s || isNaN(s)) return '0:00';
  const m = Math.floor(s / 60), sec = Math.floor(s % 60);
  return m + ':' + String(sec).padStart(2, '0');
}

// Load track list
fetch('/api/tracks').then(r => r.json()).then(data => {
  tracks = data;
  filtered = [...tracks];
  document.getElementById('track-count').textContent = tracks.length + ' tracks';
  renderList();
});

function renderList() {
  playlist.innerHTML = '';
  filtered.forEach((t, i) => {
    const li = document.createElement('li');
    li.className = 'track-item' + (t === tracks[currentIndex] ? ' active' : '');
    li.innerHTML = `
      <span class="track-num">${i + 1}</span>
      <span class="track-playing-icon">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>
      </span>
      <div class="track-info">
        <div class="track-name">${t.name}</div>
      </div>
      <span class="track-dur" data-src="${t.src}">—</span>
    `;
    li.addEventListener('click', () => {
      currentIndex = tracks.indexOf(t);
      loadTrack(currentIndex, true);
    });
    playlist.appendChild(li);
  });
}

function loadTrack(idx, autoplay) {
  if (idx < 0 || idx >= tracks.length) return;
  currentIndex = idx;
  const t = tracks[idx];
  audio.src = t.src;
  trackTitle.textContent = t.name;
  trackSubtitle.textContent = t.name;
  progress.value = 0;
  curTime.textContent = '0:00';
  durTime.textContent = '0:00';
  // re-render active state
  document.querySelectorAll('.track-item').forEach((el, i) => {
    el.classList.toggle('active', filtered[i] === t);
  });
  // scroll active into view
  const activeEl = playlist.querySelector('.active');
  if (activeEl) activeEl.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  if (autoplay) { audio.play(); setPlaying(true); }
}

function setPlaying(playing) {
  playIcon.style.display = playing ? 'none' : 'block';
  pauseIcon.style.display = playing ? 'block' : 'none';
  if (playing) albumArt.classList.add('playing');
  else albumArt.classList.remove('playing');
}

playBtn.addEventListener('click', () => {
  if (currentIndex < 0) { loadTrack(0, true); return; }
  if (audio.paused) { audio.play(); setPlaying(true); }
  else { audio.pause(); setPlaying(false); }
});

audio.addEventListener('timeupdate', () => {
  if (!audio.duration) return;
  progress.value = (audio.currentTime / audio.duration) * 100;
  curTime.textContent = fmt(audio.currentTime);
  durTime.textContent = fmt(audio.duration);
});

progress.addEventListener('input', () => {
  if (audio.duration) audio.currentTime = (progress.value / 100) * audio.duration;
});

volumeSlider.addEventListener('input', () => { audio.volume = volumeSlider.value; });
audio.volume = volumeSlider.value;

audio.addEventListener('ended', () => {
  if (repeat) { audio.play(); return; }
  if (shuffle) {
    let next;
    do { next = Math.floor(Math.random() * tracks.length); } while (next === currentIndex && tracks.length > 1);
    loadTrack(next, true);
  } else {
    if (currentIndex < tracks.length - 1) loadTrack(currentIndex + 1, true);
    else setPlaying(false);
  }
});

document.getElementById('prev-btn').addEventListener('click', () => {
  if (audio.currentTime > 3) { audio.currentTime = 0; return; }
  loadTrack(currentIndex > 0 ? currentIndex - 1 : tracks.length - 1, !audio.paused);
});

document.getElementById('next-btn').addEventListener('click', () => {
  loadTrack(currentIndex < tracks.length - 1 ? currentIndex + 1 : 0, !audio.paused);
});

shuffleBtn.addEventListener('click', () => {
  shuffle = !shuffle;
  shuffleBtn.classList.toggle('active', shuffle);
});

repeatBtn.addEventListener('click', () => {
  repeat = !repeat;
  repeatBtn.classList.toggle('active', repeat);
});

searchInput.addEventListener('input', () => {
  const q = searchInput.value.toLowerCase();
  filtered = q ? tracks.filter(t => t.name.toLowerCase().includes(q)) : [...tracks];
  renderList();
});

// keyboard shortcuts
document.addEventListener('keydown', e => {
  if (e.target === searchInput) return;
  if (e.code === 'Space') { e.preventDefault(); playBtn.click(); }
  if (e.code === 'ArrowRight') document.getElementById('next-btn').click();
  if (e.code === 'ArrowLeft') document.getElementById('prev-btn').click();
});

// ── Pull-to-refresh ──
const ptrIndicator = document.getElementById('ptr-indicator');
const THRESHOLD = 60;
let ptrStartY = 0;
let ptrDelta = 0;
let ptrActive = false;
let ptrRefreshing = false;

function ptrSetPos(dy) {
  const clamped = Math.min(dy, THRESHOLD * 1.5);
  const damped = clamped > THRESHOLD ? THRESHOLD + (clamped - THRESHOLD) * 0.3 : clamped;
  ptrIndicator.style.transform = `translateX(-50%) translateY(${damped - 36}px)`;
  ptrIndicator.classList.toggle('visible', damped > 10);
}

document.addEventListener('touchstart', e => {
  if (ptrRefreshing) return;
  const playlistWrap = document.getElementById('playlist-wrap');
  if (playlistWrap.contains(e.target)) return;
  ptrStartY = e.touches[0].clientY;
  ptrDelta = 0;
  ptrActive = true;
}, { passive: true });

document.addEventListener('touchmove', e => {
  if (!ptrActive || ptrRefreshing) return;
  ptrDelta = e.touches[0].clientY - ptrStartY;
  if (ptrDelta > 0) ptrSetPos(ptrDelta);
}, { passive: true });

document.addEventListener('touchend', async () => {
  if (!ptrActive || ptrRefreshing) return;
  ptrActive = false;
  if (ptrDelta >= THRESHOLD) {
    ptrRefreshing = true;
    ptrIndicator.classList.add('refreshing');
    ptrSetPos(THRESHOLD);
    try {
      const data = await fetch('/api/tracks').then(r => r.json());
      tracks = data;
      filtered = searchInput.value
        ? tracks.filter(t => t.name.toLowerCase().includes(searchInput.value.toLowerCase()))
        : [...tracks];
      document.getElementById('track-count').textContent = tracks.length + ' tracks';
      renderList();
    } catch(e) {}
    await new Promise(r => setTimeout(r, 600));
    ptrIndicator.classList.remove('refreshing');
    ptrIndicator.classList.remove('visible');
    ptrIndicator.style.transform = 'translateX(-50%) translateY(-60px)';
    ptrRefreshing = false;
  } else {
    ptrIndicator.classList.remove('visible');
    ptrIndicator.style.transform = 'translateX(-50%) translateY(-60px)';
  }
  ptrDelta = 0;
});
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # silence access logs

    def do_GET(self):
        path = urllib.parse.unquote(self.path.split("?")[0])

        if path == "/" or path == "/index.html":
            self._serve_bytes(HTML.encode(), "text/html; charset=utf-8")

        elif path == "/api/tracks":
            mp3_files = sorted(
                [f for f in MUSIC_DIR.iterdir() if f.suffix.lower() == ".mp3"],
                key=lambda f: f.name.lower(),
            )
            tracks = [
                {"name": f.stem, "src": "/music/" + urllib.parse.quote(f.name)}
                for f in mp3_files
            ]
            body = json.dumps(tracks).encode()
            self._serve_bytes(body, "application/json")

        elif path.startswith("/music/"):
            filename = urllib.parse.unquote(path[7:])
            filepath = MUSIC_DIR / filename
            if filepath.exists() and filepath.suffix.lower() == ".mp3":
                self._serve_file(filepath, "audio/mpeg")
            else:
                self._404()
        else:
            self._404()

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
    server = HTTPServer(("0.0.0.0", port), Handler)
    print(f"Music Player running at http://localhost:{port}")
    print(f"Serving MP3s from: {MUSIC_DIR}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
