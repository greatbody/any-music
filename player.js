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

function esc(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
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
    const playsLabel = t.plays ? `<span class="track-plays">${t.plays}▶</span>` : '';
    li.innerHTML = `
      <span class="track-num">${i + 1}</span>
      <span class="track-playing-icon">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>
      </span>
      <div class="track-info">
        <div class="track-name">${esc(t.name)}</div>
      </div>
      ${playsLabel}
      <span class="track-dur" data-src="${esc(t.src)}">—</span>
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

audio.addEventListener('ended', async () => {
  // record a completed play (skip repeat — same song plays again)
  if (!repeat && currentIndex >= 0) {
    const played = tracks[currentIndex];
    try {
      const res = await fetch('/api/played', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        // Send the server-side index, not the filename string — the backend
        // resolves the real stem from the index, preventing path traversal.
        // currentIndex is captured here, before the subsequent /api/tracks
        // refresh changes the list order.
        body: JSON.stringify({ index: currentIndex })
      });
      const { plays } = await res.json();
      played.plays = plays;
      // refresh full list so sort order updates
      const data = await fetch('/api/tracks').then(r => r.json());
      const wasName = played.name;
      tracks = data;
      filtered = searchInput.value
        ? tracks.filter(t => t.name.toLowerCase().includes(searchInput.value.toLowerCase()))
        : [...tracks];
      document.getElementById('track-count').textContent = tracks.length + ' tracks';
      currentIndex = tracks.findIndex(t => t.name === wasName);
      renderList();
    } catch(e) {}
  }
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

// ── YouTube Search & Download ──
const ytBackdrop = document.getElementById('yt-modal-backdrop');
const ytSearchInput = document.getElementById('yt-search-input');
const ytResults = document.getElementById('yt-results');
const ytStatusMsg = document.getElementById('yt-status-msg');

document.getElementById('open-yt-btn').addEventListener('click', () => {
  ytBackdrop.classList.add('open');
  ytSearchInput.focus();
});
document.getElementById('yt-modal-close').addEventListener('click', closeYtModal);
ytBackdrop.addEventListener('click', e => { if (e.target === ytBackdrop) closeYtModal(); });

function closeYtModal() { ytBackdrop.classList.remove('open'); }

document.getElementById('yt-search-btn').addEventListener('click', doYtSearch);
ytSearchInput.addEventListener('keydown', e => { if (e.key === 'Enter') doYtSearch(); });

async function doYtSearch() {
  const q = ytSearchInput.value.trim();
  if (!q) return;
  ytResults.innerHTML = '<div id="yt-status-msg">Searching\u2026</div>';
  try {
    const res = await fetch('/api/search?q=' + encodeURIComponent(q));
    const items = await res.json();
    if (items.error) { ytResults.innerHTML = `<div id="yt-status-msg">Error: ${esc(items.error)}</div>`; return; }
    if (!items.length) { ytResults.innerHTML = '<div id="yt-status-msg">No results found.</div>'; return; }
    ytResults.innerHTML = '';
    items.forEach(item => {
      const dur = item.duration ? fmt(item.duration) : '—';
      const div = document.createElement('div');
      div.className = 'yt-item';
      div.innerHTML = `
        <img class="yt-thumb" src="${esc(item.thumbnail)}" alt="" loading="lazy">
        <div class="yt-info">
          <div class="yt-title">${esc(item.title)}</div>
          <div class="yt-meta">${esc(item.channel)} · ${dur}</div>
          <div class="yt-progress-bar" style="display:none"><div class="yt-progress-fill" style="width:0%"></div></div>
        </div>
        <button class="yt-dl-btn">↓ Download</button>
      `;
      const btn = div.querySelector('.yt-dl-btn');
      const bar = div.querySelector('.yt-progress-bar');
      const fill = div.querySelector('.yt-progress-fill');
      btn.addEventListener('click', async () => {
        btn.disabled = true;
        btn.textContent = 'Starting\u2026';
        bar.style.display = 'block';
        try {
          const r = await fetch('/api/download', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: item.url, title: item.title })
          });
          const { id } = await r.json();
          btn.textContent = '0%';
          const poll = setInterval(async () => {
            try {
              const s = await fetch('/api/download/status?id=' + id).then(x => x.json());
              fill.style.width = s.progress + '%';
              btn.textContent = s.status === 'done' ? '✓ Done' :
                                 s.status === 'failed' ? '✗ Failed' :
                                 s.progress + '%';
              if (s.status === 'done') {
                clearInterval(poll);
                // fetch updated list from server
                const data = await fetch('/api/tracks').then(x => x.json());
                // find the newly downloaded track (present in data but not in tracks)
                const existingNames = new Set(tracks.map(t => t.name));
                const newTrack = data.find(t => !existingNames.has(t.name));
                tracks = data;
                if (newTrack) {
                  // pin new track at position 0 regardless of current search
                  const q = searchInput.value.toLowerCase();
                  const rest = tracks.filter(t => t !== newTrack && (!q || t.name.toLowerCase().includes(q)));
                  filtered = [newTrack, ...rest];
                } else {
                  filtered = searchInput.value
                    ? tracks.filter(t => t.name.toLowerCase().includes(searchInput.value.toLowerCase()))
                    : [...tracks];
                }
                document.getElementById('track-count').textContent = tracks.length + ' tracks';
                renderList();
              } else if (s.status === 'failed') {
                clearInterval(poll);
                bar.style.display = 'none';
              }
            } catch(e) { clearInterval(poll); }
          }, 800);
        } catch(e) {
          btn.textContent = '✗ Error';
          btn.disabled = false;
        }
      });
      ytResults.appendChild(div);
    });
  } catch(e) {
    ytResults.innerHTML = '<div id="yt-status-msg">Search failed. Is yt-dlp installed?</div>';
  }
}

// keyboard shortcuts
document.addEventListener('keydown', e => {
  if (e.target.tagName === 'INPUT') return;
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
