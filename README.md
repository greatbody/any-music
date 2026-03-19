# any-music

`any-music` is a small local web music player written with Python standard library tools and a simple HTML/CSS/JS frontend. It can list local MP3 files, play them in the browser, track play counts, and search/download audio from YouTube through `yt-dlp`.

## Status

This repository is published for technical research and personal experimentation.

- It is not a commercial product.
- It is shared to study implementation details such as a lightweight HTTP server, local media playback, basic frontend interactions, and hardening against common web attacks.
- The repository itself does not contain music assets and is not presented as having standalone commercial value.

## Features

- Serve local MP3 files from `musics/`
- Browser music player with playlist, search, shuffle, repeat, and volume control
- Track play counts in `play_counts.json`
- Search YouTube and download audio with `yt-dlp`
- Basic security hardening for path traversal, XSS, CSP, request size limits, and range handling

## Requirements

- Python 3.10+
- `yt-dlp` installed and available in `PATH`
- Google Chrome installed if you want to use browser-cookie-backed downloads

## Important Privacy Notice

When handling YouTube downloads, this project invokes:

```bash
yt-dlp --cookies-from-browser chrome
```

That means the program will attempt to read cookies from your local Chrome profile through `yt-dlp`.

- This is done so `yt-dlp` can access content that may require browser session data.
- The repository does not store your browser cookies in source control.
- You should still treat this behavior as privacy-sensitive and only run the project on a machine and browser profile you trust.
- If you do not want this behavior, modify `player.py` before running the download feature.

## Copyright and Content Notice

- This repository contains code only; music files are intentionally ignored by git.
- Any audio downloaded or played through this project may be protected by copyright.
- You are responsible for complying with copyright law, platform terms, and local regulations.
- This project is shared for technical research only and should not be understood as granting rights to copy, distribute, or commercialize third-party media.

## Quick Start

1. Put your MP3 files in `musics/`.
2. Start the server:

```bash
python3 player.py
```

3. Open:

```text
http://localhost:8888
```

To use a different port:

```bash
python3 player.py 9999
```

## Files

- `player.py` - backend HTTP server
- `index.html` - page structure
- `player.css` - player styles
- `player.js` - client logic
- `_test_attacks.py` - manual attack-oriented test script

## Security Notes

- The server is intended for local or otherwise trusted environments.
- There is no authentication layer.
- If you expose the service to a LAN or the public internet, other users may be able to trigger downloads or update play counters.

## License

Released under the MIT License. See `LICENSE`.
