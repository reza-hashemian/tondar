# Tondar (تندر) — Download Manager for Debian

A download manager like IDM, built with Python + GTK4/libadwaita, plus a browser extension for Chrome and Firefox.

## Build and install

```sh
./tools/build-deb.sh
sudo apt install ./build/tondar_1.0.0_all.deb
```

Run it from the app menu (**Tondar Download Manager**) or with `tondar`.
For video downloads: menu → **Install / Update yt-dlp** (installs the latest yt-dlp for your user only), and `sudo apt install ffmpeg`.

Run without installing (for development), side by side with the installed copy:

```sh
cd src && TONDAR_APP_ID=io.github.tondar.TondarDev python3 -m tondar
```

## Playlists

Paste a playlist link (YouTube `playlist?list=…`, or `watch?v=…&list=…`) in the New Download
window: every video is listed with a checkbox. Each selected video becomes its own download,
saved in a folder named after the playlist and numbered in playlist order. Turn off
“Download entire playlist” to fetch only the video in the link.

## Browser extension

The app menu → **Browser Integration** shows the paths.

- **Chrome**: `chrome://extensions` → Developer mode → Load unpacked → `/usr/share/tondar/extension/chrome`
- **Firefox ESR**: `about:config` → `xpinstall.signatures.required = false`, then
  `about:addons` → ⚙ → Install Add-on From File → `/usr/share/tondar/extension/tondar-firefox.xpi`

## Project layout

```
src/tondar/
  core.py        download list, queue, settings, saving to disk
  http_task.py   multi-connection resumable downloader (dynamic segment splitting)
  media.py       video/stream downloads through yt-dlp
  app.py         Adw.Application: single instance, command line, notifications
  window.py      main window (list, categories, search)
  dialogs.py     New Download window, Preferences, Browser Integration
native-host/     bridge between the browser extension and the app (native messaging)
extension/       browser extension (MV3, shared by Chrome and Firefox)
data/            .desktop file and icon
tools/build-deb.sh
```

Your data lives in: `~/.local/share/tondar/downloads.json` and `~/.config/tondar/settings.json`

## Scheduler

Preferences → Scheduler: start time, optional stop time, and days. Add downloads with the
**Schedule** button in the New Download window, or with "Add to Schedule" in a download's menu.
If a stop time is set, unfinished downloads pause then and continue at the next start time.
When they're all done, Tondar can quit or shut the computer down (with a 60-second cancel window).
Tondar must be running at the start time, so turn on "Start on login".

## Proxy

Preferences → Network: system settings (GNOME), no proxy, or manual HTTP / SOCKS5
(with optional username and password). Used for downloads, video lookups and yt-dlp updates.
SOCKS5 is built in (DNS is resolved by the proxy). Settings are stored in
`~/.config/tondar/settings.json`, readable only by you.
