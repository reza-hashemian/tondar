# Tondar (تندر) — Download Manager

A download manager like IDM, for **Windows** and **Linux (Debian/Ubuntu)**:
multi-connection resumable downloads, YouTube and other video/playlist downloads,
a scheduler, proxy support, and a browser extension that adds a **Download** button to videos.

[**⬇ Download the latest version**](https://github.com/reza-hashemian/tondar/releases/latest)

- [Windows guide](#windows) · [راهنمای فارسی ویندوز](#راهنمای-ویندوز)
- [Linux guide](#linux)
- [Features](#features) · [Troubleshooting](#troubleshooting) · [For developers](#for-developers)

---

## Windows

### 1. Install

1. Open the [latest release](https://github.com/reza-hashemian/tondar/releases/latest) and download
   **`Tondar-Setup-x.y.z.exe`**.
2. Run it. Windows may show **“Windows protected your PC”**, because the installer isn't
   digitally signed. Click **More info** → **Run anyway**.
3. Follow the installer. No administrator rights are needed. Tick
   **“Start Tondar when I log in”** if you want the scheduler and the browser button to always work.

Tondar is installed to `%LOCALAPPDATA%\Programs\Tondar` and appears in the Start menu.
yt-dlp and ffmpeg are included, so videos work right away.

### 2. Add the browser extension

The extension takes over downloads from your browser and adds a **Download** button on videos.

**Google Chrome / Microsoft Edge**

1. Open `chrome://extensions` (Edge: `edge://extensions`).
2. Turn on **Developer mode** (Chrome: top right, Edge: left side).
3. Click **Load unpacked** and choose this folder:
   ```
   %LOCALAPPDATA%\Programs\Tondar\extension\chrome
   ```
   (Paste the line into the folder box of the dialog, Windows expands it.)
4. Pin the Tondar icon in the toolbar. Its popup should say **Connected**.

Don't move or delete that folder; Chrome loads the extension from it.

**Firefox**

Regular Firefox only accepts extensions signed by Mozilla, so use
[Firefox ESR](https://www.mozilla.org/firefox/enterprise/) or
[Firefox Developer Edition](https://www.mozilla.org/firefox/developer/):

1. Open `about:config`, search `xpinstall.signatures.required` and set it to **false**.
2. Open `about:addons` → ⚙ → **Install Add-on From File…**
3. Choose `%LOCALAPPDATA%\Programs\Tondar\extension\tondar-firefox.xpi`.

### 3. Use it

- **Add a link:** press **+** (or Ctrl+N). A copied link is filled in automatically.
- **Videos:** hover a video on any site and click the orange **Download** button, or paste a
  YouTube / Aparat / Instagram link and choose the quality.
- **Playlists:** paste a playlist link; tick the videos you want.
- **Scheduler:** ☰ → **Scheduler** — start time, stop time, days, and optionally shut the PC down when done.
  Add downloads with the **Schedule** button.
- **Proxy:** ☰ → **Proxy** — HTTP or SOCKS5, e.g. `127.0.0.1:10808` for v2rayN on the same PC,
  or another computer's IP on your network. Press **Test** to check it.
- Closing the window keeps Tondar running in the background. Open it again from the Start menu;
  quit it with ☰ → **Quit**.

### Update / uninstall

- **Update:** download the new `Tondar-Setup` from Releases and run it; your downloads list is kept.
- **Uninstall:** Windows Settings → Apps → **Tondar Download Manager** → Uninstall.
  Your settings stay in `%APPDATA%\Tondar` and the list in `%LOCALAPPDATA%\Tondar`; delete those
  folders to remove everything.

---

<div dir="rtl">

## راهنمای ویندوز

### ۱. نصب

۱. وارد [صفحه‌ی آخرین نسخه](https://github.com/reza-hashemian/tondar/releases/latest) شو و فایل
**`Tondar-Setup-x.y.z.exe`** رو دانلود کن.

۲. اجراش کن. ممکنه ویندوز پیام **Windows protected your PC** نشون بده، چون نصب‌کننده امضای دیجیتال نداره.
روی **More info** و بعد **Run anyway** بزن.

۳. مراحل نصب رو برو جلو. دسترسی ادمین لازم نیست. اگه می‌خوای زمان‌بندی و دکمه‌ی دانلود مرورگر همیشه کار کنن،
تیک **Start Tondar when I log in** رو بزن.

yt-dlp و ffmpeg همراه برنامه نصب می‌شن، پس دانلود ویدیو از همون اول کار می‌کنه.

### ۲. نصب افزونه‌ی مرورگر

**کروم یا اج:**

۱. آدرس `chrome://extensions` رو باز کن. توی Edge آدرسش `edge://extensions` هست.

۲. گزینه‌ی **Developer mode** رو روشن کن.

۳. روی **Load unpacked** بزن و این پوشه رو انتخاب کن. می‌تونی همین متن رو توی کادر آدرس پنجره paste کنی:

</div>

```
%LOCALAPPDATA%\Programs\Tondar\extension\chrome
```

<div dir="rtl">

۴. آیکون تندر رو به نوار ابزار pin کن. وقتی روش بزنی باید **Connected** نشون بده.

این پوشه رو جابه‌جا یا پاک نکن، چون کروم افزونه رو از همون‌جا می‌خونه.

**فایرفاکس:** نسخه‌ی معمولی فایرفاکس فقط افزونه‌های امضاشده رو قبول می‌کنه. برای همین باید
**Firefox ESR** یا **Developer Edition** نصب کنی. بعد:

۱. توی `about:config` مقدار `xpinstall.signatures.required` رو **false** کن.

۲. برو `about:addons`، روی ⚙ بزن و **Install Add-on From File** رو انتخاب کن.

۳. فایل `tondar-firefox.xpi` رو از پوشه‌ی `%LOCALAPPDATA%\Programs\Tondar\extension` انتخاب کن.

### ۳. استفاده

- **لینک:** دکمه‌ی **+** یا Ctrl+N رو بزن. اگه لینکی کپی کرده باشی، خودش پر می‌شه.
- **ویدیو:** موس رو روی ویدیوی هر سایتی ببر و دکمه‌ی نارنجی **Download** رو بزن. یا لینک یوتیوب، آپارات یا اینستاگرام رو بده و کیفیت رو انتخاب کن.
- **پلی‌لیست:** لینک پلی‌لیست رو بده و ویدیوهایی که می‌خوای رو تیک بزن.
- **زمان‌بندی:** از ☰ گزینه‌ی **Scheduler** رو باز کن. ساعت شروع، ساعت توقف و روزهای هفته رو تنظیم کن. اگه بخوای، آخر کار کامپیوتر رو هم خاموش می‌کنه.
- **پروکسی:** از ☰ گزینه‌ی **Proxy** رو باز کن. مثلاً برای v2rayN روی همین سیستم، آدرس `127.0.0.1` و پورت `10808` رو با نوع SOCKS5 بده. بعد دکمه‌ی **Test** رو بزن.
- بستن پنجره برنامه رو نمی‌بنده و دانلودها ادامه پیدا می‌کنن. برای بستن کامل از ☰ گزینه‌ی **Quit** رو بزن.

### به‌روزرسانی و حذف

- **به‌روزرسانی:** نصب‌کننده‌ی نسخه‌ی جدید رو اجرا کن. لیست دانلودها سر جاش می‌مونه.
- **حذف:** از Settings ویندوز برو به Apps و **Tondar Download Manager** رو Uninstall کن.

</div>

---

## Linux

Debian 13 / Ubuntu 24.10 or newer (needs GTK 4 and libadwaita 1.6+).

1. Download **`tondar_x.y.z_all.deb`** from the [latest release](https://github.com/reza-hashemian/tondar/releases/latest).
2. Install it:
   ```sh
   sudo apt install ./tondar_*_all.deb
   sudo apt install ffmpeg   # for HD YouTube
   ```
3. Open **Tondar Download Manager** from the app menu, then ☰ → **Install / Update yt-dlp**.

**Browser extension**
- Chrome / Chromium / Edge: `chrome://extensions` → Developer mode → Load unpacked →
  `/usr/share/tondar/extension/chrome`
- Firefox ESR: `about:config` → `xpinstall.signatures.required = false`, then `about:addons` → ⚙ →
  Install Add-on From File → `/usr/share/tondar/extension/tondar-firefox.xpi`

Data: `~/.local/share/tondar/downloads.json`, settings: `~/.config/tondar/settings.json`.

---

## Features

- Up to 32 connections per download, with dynamic splitting of the remaining parts
- Pause / resume, even after a restart; “Refresh download address” for expired links
- Categories (Video, Music, Compressed, Documents, Programs), search, queue, speed limit
- Videos and playlists from YouTube and 1000+ sites (yt-dlp), with quality choice
- Browser extension: takes over downloads, **Download** button on videos, right-click menu,
  list of videos found on the page, sends cookies for sites that need a login
- Scheduler with start/stop time and days; can quit or shut down when finished
- Proxy: system settings, or manual HTTP / SOCKS5 with username and password

## Troubleshooting

| Problem | Fix |
|---|---|
| Extension popup says **App not found** | Make sure Tondar is installed, then restart the browser. On Windows, reinstall Tondar to re-register the browser bridge. |
| YouTube says “Sign in to confirm you're not a bot” or similar | ☰ → **Install / Update yt-dlp** (sites change often), or set a proxy. |
| Video downloads have no sound or won't merge | ffmpeg is missing (Linux: `sudo apt install ffmpeg`). |
| Scheduled downloads didn't start | Tondar must be running at that time: turn on **Start on login**. |
| **Test** proxy fails with a LAN proxy | In the proxy app on the other computer, enable “Allow connections from LAN”. |

---

## For developers

```sh
./tools/build-deb.sh                 # build/tondar_<version>_all.deb
cd src && TONDAR_APP_ID=io.github.tondar.TondarDev python3 -m tondar   # run next to the installed copy
```

The Windows installer is built by GitHub Actions (`.github/workflows/build.yml`) with MSYS2,
PyInstaller and Inno Setup. Every push builds both packages (see the **Actions** tab); pushing a
tag like `v1.3.0` publishes them as a release.

```
src/tondar/
  core.py        download list, queue, scheduler, settings
  http_task.py   multi-connection resumable downloader
  media.py       video/stream/playlist downloads through yt-dlp
  net.py         proxy support (HTTP, built-in SOCKS5)
  ipc.py         single-instance support on Windows
  app.py         application, command line, notifications
  window.py      main window
  dialogs.py     New Download, Preferences, Browser Integration
native-host/     bridge between the browser extension and the app (native messaging)
extension/       browser extension (Manifest V3, Chrome and Firefox)
windows/         PyInstaller spec, Inno Setup script, native messaging manifests
tools/           build scripts
```
