# Tondar (تندر) — Download Manager

A download manager like IDM, for **Windows**, **macOS** and **Linux (Debian/Ubuntu)**:
multi-connection resumable downloads, YouTube and other video/playlist downloads,
a scheduler, proxy support, and a browser extension that adds a **Download** button to videos.

[**⬇ Download the latest version**](https://github.com/reza-hashemian/tondar/releases/latest)

**English:** [Install on Windows](#install-on-windows) · [Install on macOS](#install-on-macos) · [Install on Linux](#install-on-linux) ·
[Browser extension](#browser-extension) · [Using Tondar](#using-tondar) · [Troubleshooting](#troubleshooting)

**فارسی:** [راهنمای فارسی](#راهنمای-فارسی)

**Developers:** [For developers](#for-developers)

---

## Install on Windows

1. Open the [latest release](https://github.com/reza-hashemian/tondar/releases/latest) and download
   **`Tondar-Setup-x.y.z.exe`**.
2. Run it. Windows may show **“Windows protected your PC”**, because the installer isn't
   digitally signed. Click **More info** → **Run anyway**.
3. Follow the installer. No administrator rights are needed. Tick
   **“Start Tondar when I log in”** if you want the scheduler and the browser button to always work.

Tondar is installed to `%LOCALAPPDATA%\Programs\Tondar` and appears in the Start menu.
yt-dlp and ffmpeg are included, so videos work right away.

**Update:** download the new `Tondar-Setup` and run it; your downloads list is kept.
**Uninstall:** Windows Settings → Apps → **Tondar Download Manager** → Uninstall.
Settings stay in `%APPDATA%\Tondar` and the list in `%LOCALAPPDATA%\Tondar`; delete those folders
to remove everything.

## Install on macOS

macOS 12 or newer.

1. Download from the [latest release](https://github.com/reza-hashemian/tondar/releases/latest):
   **`Tondar-x.y.z-macos-arm64.dmg`** for Apple Silicon (M1, M2, …) or
   **`Tondar-x.y.z-macos-x86_64.dmg`** for Intel Macs ( → About This Mac shows which one you have).
2. Open the `.dmg` and drag **Tondar** onto **Applications**.
3. The app isn't signed with an Apple developer ID, so the first time macOS says it
   *can't be opened*. Click **Done**, then open **System Settings → Privacy & Security**, scroll down and
   click **Open Anyway** next to Tondar. (Or run `xattr -cr /Applications/Tondar.app` in Terminal.)

yt-dlp and ffmpeg are included. Tondar registers the browser bridge for Chrome, Edge, Brave, Chromium
and Firefox each time it starts, so open it once before installing the extension.

**Update:** drag the new version onto Applications and replace the old one.
**Uninstall:** move Tondar from Applications to the Trash. Data is in `~/.local/share/tondar` and
`~/.config/tondar`.

## Install on Linux

Debian 13 / Ubuntu 24.10 or newer (needs GTK 4 and libadwaita 1.6+).

1. Download **`tondar_x.y.z_all.deb`** from the [latest release](https://github.com/reza-hashemian/tondar/releases/latest).
2. Install it, plus ffmpeg (needed for HD YouTube):
   ```sh
   sudo apt install ./tondar_*_all.deb ffmpeg
   ```
3. Open **Tondar Download Manager** from the app menu, then ☰ → **Install / Update yt-dlp**.
4. For the scheduler and the browser button to always work: ☰ → **Preferences** → turn on **Start on login**.

**Update:** install the new `.deb` the same way, then ☰ → **Quit** and open Tondar again.
**Uninstall:** `sudo apt remove tondar`. Your data stays in `~/.local/share/tondar` (downloads list,
yt-dlp) and `~/.config/tondar` (settings); delete them to remove everything.

## Browser extension

The extension sends your browser's downloads to Tondar and adds a **Download** button on videos.
Install Tondar first.

**Google Chrome / Microsoft Edge / Chromium**

1. Open `chrome://extensions` (Edge: `edge://extensions`).
2. Turn on **Developer mode** (Chrome: top right, Edge: left side).
3. Click **Load unpacked** and choose the extension folder:
   - Windows: `%LOCALAPPDATA%\Programs\Tondar\extension\chrome`
     (paste this into the folder box of the dialog; Windows expands it)
   - macOS: `/Applications/Tondar.app/Contents/Resources/extension/chrome`
     (in the dialog press ⌘⇧G and paste this path)
   - Linux: `/usr/share/tondar/extension/chrome`
4. Pin the Tondar icon in the toolbar. Its popup should say **Connected**.

Don't move or delete that folder; the browser loads the extension from it.

**Firefox** (version 140 or newer)

1. Download **`tondar-firefox-x.y.z.xpi`** from the
   [latest release](https://github.com/reza-hashemian/tondar/releases/latest).
2. Open `about:addons` → ⚙ → **Install Add-on From File…** and choose the file
   (or drag the file onto a Firefox window). Click **Add**.

The Firefox add-on is signed by Mozilla, so it installs in regular Firefox.

## Using Tondar

**Adding downloads**
- Press **+** (or Ctrl+N) and paste a link. A link you've copied is filled in automatically.
  You can also drag a link onto the window.
- **Download Later** adds it paused; **Schedule** adds it to the scheduler; **Start Download** starts now.
- With the extension, clicking a download link in the browser opens Tondar's **New Download**
  window instead of the browser's download.
- **Right-click** any link (or a video, audio or picture) → **Download with Tondar**. On a download
  button that isn't a real link, the page entry turns into **Download with Tondar** too.
- To let the browser download normally again, click the Tondar toolbar icon and untick
  **Take over browser downloads**.
- Several links sent from the browser at once open one after another: the **New Download** window
  shows “N more links from the browser” and **Add All Now** adds the rest straight away.

**Videos and playlists**
- Hover a video on any website and click the orange **Download** button. It lists the video
  files and streams found on the page, plus **Best quality (yt-dlp)**.
  The **×** next to it hides the button on that page; reload the page to get it back.
- **No login needed:** when a site wants you to log in before a video can be looked up, Tondar
  reads the page like a visitor (yt-dlp's generic extractor) and lists the video links the page
  shows anyway (marked **no login needed** in the browser, and offered under **Quality** in the
  New Download window).
- Or paste a YouTube / Aparat / Instagram / … link, set **Type** to **Video / stream**, and choose the quality
  (**Audio only** is at the bottom of the list).
- For a playlist link, every video is listed with a checkbox. The videos are saved in a folder named
  after the playlist, numbered in order. Turn off **Download entire playlist** to get only one video.
- **Format:** the **Format** row lists the containers the site offers (MP4, WebM, …, shown under
  **Formats on this site**) and MKV/MP4 repackaging at the same quality. On the page, the orange
  button's menu has the same choice under **Format** (Auto / MP4 / MKV / WebM / Audio only).
- **Only a part of a video:** turn on **Download only a part** (✂ in the orange button's menu) and fill in **From** and **To**
  (`1:20`, `90`, `1:02:03`; leave **To** empty for "until the end"). On the page, the **Now** buttons
  take the player's current time. The clip gets its own name, e.g. `Video (clip 1m20s-2m05s).mp4`.
  The cut starts at the nearest key frame, so it can begin a second or two early.
- Sites change often: if videos stop working, use ☰ → **Install / Update yt-dlp**.
- **YouTube “Sign in to confirm you're not a bot”:** YouTube asks this on some networks (VPN, proxy,
  shared connections). Tondar first tries without an account, then with the YouTube sign-in your
  browser sent with the link (send the video with **Download with Tondar** while you're signed in to
  youtube.com). You can also choose your browser in Preferences → **Sign-in from browser**; yt-dlp then
  reads the YouTube sign-in from that browser (close Chrome / Edge first, they lock it). Press
  **Try Again** next to **Details** after changing something. Nothing is stored by Tondar.

**Progress and "Download Complete" windows**
- Every download you start gets a small window of its own: percent, speed, time left, size,
  folder, and **Pause / Resume**, **Cancel** and **Hide**. ⋮ → **Progress Window** opens it again.
- When it finishes, **Download Complete** offers **Open**, **Open Folder** and **Close**.
- Both can be turned off in Preferences (**Show a progress window**,
  **Show a window when a download finishes**).

**Clone a website** (the 🌐 button at the top, ☰ → **Clone Website…**, Ctrl+Shift+N, or right-click a
page → **Clone this website with Tondar**)
- Enter the address and choose how far to go: **The whole website**, or turn it off and set
  **Link depth** (0 = only this page, 1 = this page and the pages it links to, 5 = pages up to 5 links
  away). **Only this website** keeps the clone on that site; **Include subdomains** also follows
  `blog.example.com`, `shop.example.com`…; turned off, links to other websites are followed too (use a
  link depth then). Also: **At most** N pages, pictures/styles/fonts from other servers (CDNs), the
  files the pages link to (PDF, ZIP…), a size limit per file, and **Respect robots.txt**.
- Every address is downloaded once: `#parts`, tracking parameters (`utm_…`, `fbclid`…), the order of
  parameters, `dir/` vs `dir/index.html` and redirects are recognized, and identical files under
  different addresses are saved once.
- **Updating a copy:** clone the same address into the same folder again (the window offers
  **Update the copy in this folder**), or ⋮ → **Download Again**: Tondar asks the server what changed
  since last time (ETag / Last-Modified) and downloads only the pages and files that changed.
- Pick the folder and name; links are rewritten so the copy opens offline in a browser
  (**Open Website** opens its first page). Pause / resume works like for files; files that could not be
  saved are listed in `_tondar-failed.txt`.
- Sites that build their pages with JavaScript (web apps) can only be copied as far as their HTML goes.

**Managing downloads**
- ▶ / ⏸ on each row resumes or pauses; the buttons at the top resume or pause everything.
  Downloads continue where they stopped, even after a restart.
- ⋮ on a row (or right-click): open the file or folder, copy the address,
  **Refresh Download Address…** (paste a fresh link when the old one has expired; the download
  continues), download again, add to / remove from schedule, remove, delete the file.
- The left sidebar filters by status (Downloading, Unfinished, Completed, Scheduled) and type
  (Video, Music, Compressed, …). Use the search box to find a download.
- Closing the window keeps Tondar running in the background, with its icon in the notification area
  (Windows: click **^** next to the clock if it's hidden; drag it onto the taskbar to keep it visible) or the
  system tray (Linux). Click the icon to open Tondar; right-click it for **New Download**, **Clone Website**,
  **Resume All**, **Pause All**, **Preferences** and **Quit Tondar**. On GNOME the tray needs the
  “AppIndicator and KStatusNotifierItem Support” extension (Ubuntu has it already). Quit with ☰ → **Quit** too.

**Scheduler** (☰ → **Scheduler**)
- Turn on **Enable scheduler**, choose the **start** time, an optional **stop** time, and the **days**.
- Add downloads with the **Schedule** button, or ⋮ → **Add to Schedule**. Optionally, **Also start all
  other unfinished downloads**.
- With a stop time, unfinished downloads pause then and continue at the next start.
- **When scheduled downloads finish**: do nothing, quit Tondar, or **shut down the computer**
  (you get 60 seconds to cancel).
- Tondar must be running at the start time: turn on **Start on login**.

**Proxy** (☰ → **Proxy**)
- **System settings** uses your system proxy, **No proxy** connects directly, **Manual** lets you enter one.
- Manual: choose **HTTP** or **SOCKS5**, then the address and port, and a username/password if needed.
  Examples: v2rayN on the same computer → SOCKS5, `127.0.0.1`, `10808`.
  A proxy on another computer in your network → that computer's IP (e.g. `192.168.1.10`), and turn on
  “Allow connections from LAN” in the proxy app there.
- Press **Test** to check it. The proxy is used for all downloads, video lookups and yt-dlp updates.

**Preferences** (☰ → **Preferences**)
- Download folder, and **Sort into sub-folders** (Video, Music, Compressed, …)
- **Remember the folder I choose**: once you pick a folder in the New Download window, the next
  downloads go there too (the ↶ button next to it, or **Forget**, goes back to the download folder)
- **Simultaneous downloads**, **Connections per download** (more is usually faster), **Speed limit**
- **Keep running when window is closed**, **Start on login**,
  **Ask before downloading from the browser**, notifications
- **Show a progress window**, **Show a window when a download finishes**
- **Sign-in from browser** (under Video downloads): the browser yt-dlp may read your YouTube sign-in
  from when YouTube asks to confirm you're not a bot (**Don't use** by default)

## Troubleshooting

| Problem | Fix |
|---|---|
| Extension popup says **App not found** | Make sure Tondar is installed, then restart the browser. On Windows, run the installer again to re-register the browser bridge. |
| No **Download** button on a video | If you pressed its **×**, reload the page. Otherwise reload the page after installing the extension. Very small videos (under 200×110) don't get a button. Use the toolbar icon instead. |
| YouTube: “Sign in to confirm you're not a bot” | Send the video from the browser while signed in to youtube.com, or pick your browser in Preferences → **Sign-in from browser** (close Chrome / Edge first) and press **Try Again**. Turning a VPN/proxy off or using another network also helps. ☰ → **Install / Update yt-dlp** for other YouTube errors. |
| Download Complete → **Open** / **Open Folder** froze or closed Tondar | Fixed in 1.4.0 (they no longer use GTK's file launcher). |
| No Tondar icon next to the clock (Windows) | Click **^** (hidden icons); drag the icon onto the taskbar to keep it there. |
| A download fails with **HTTP 403** or “link expired” | ⋮ → **Refresh Download Address…** and paste a new link to the same file. |
| Video downloads have no sound or don't merge | ffmpeg is missing (Linux: `sudo apt install ffmpeg`; on Windows and macOS it's included). |
| Scheduled downloads didn't start | Tondar must be running at that time: turn on **Start on login**, and check **Enable scheduler** and the days. |
| Proxy **Test** fails with a proxy on another computer | Turn on “Allow connections from LAN” in the proxy app, and check the IP, port and type (HTTP vs SOCKS5). |
| Windows: “Windows protected your PC” | The installer isn't signed. Click **More info** → **Run anyway**. |

---

<div dir="rtl">

## راهنمای فارسی

[نصب روی ویندوز](#نصب-روی-ویندوز) · [نصب روی مک](#نصب-روی-مک) · [نصب روی لینوکس](#نصب-روی-لینوکس) · [افزونه‌ی مرورگر](#افزونه-برای-مرورگر) · [استفاده](#استفاده-از-تندر) · [رفع مشکل](#رفع-مشکل)

### نصب روی ویندوز

۱. وارد [صفحه‌ی آخرین نسخه](https://github.com/reza-hashemian/tondar/releases/latest) شو و فایل
**`Tondar-Setup-x.y.z.exe`** رو دانلود کن.

۲. اجراش کن. ممکنه ویندوز پیام **Windows protected your PC** نشون بده، چون نصب‌کننده امضای دیجیتال نداره.
روی **More info** و بعد **Run anyway** بزن.

۳. مراحل نصب رو برو جلو. دسترسی ادمین لازم نیست. اگه می‌خوای زمان‌بندی و دکمه‌ی دانلود مرورگر همیشه کار کنن،
تیک **Start Tondar when I log in** رو بزن.

yt-dlp و ffmpeg همراه برنامه نصب می‌شن، پس دانلود ویدیو از همون اول کار می‌کنه.

- **به‌روزرسانی:** نصب‌کننده‌ی نسخه‌ی جدید رو اجرا کن. لیست دانلودها سر جاش می‌مونه.
- **حذف:** از Settings ویندوز برو به Apps و **Tondar Download Manager** رو Uninstall کن.

### نصب روی مک

مک‌اواس ۱۲ به بالا.

۱. از [صفحه‌ی آخرین نسخه](https://github.com/reza-hashemian/tondar/releases/latest) فایل مناسب مکت رو دانلود کن:
**`Tondar-x.y.z-macos-arm64.dmg`** برای مک‌های Apple Silicon (M1، M2 و…) یا
**`Tondar-x.y.z-macos-x86_64.dmg`** برای مک‌های اینتلی. (از منوی  → About This Mac می‌تونی ببینی مکت کدومه.)

۲. فایل `.dmg` رو باز کن و **Tondar** رو بکش روی پوشه‌ی **Applications**.

۳. برنامه امضای اپل نداره، پس بار اول مک می‌گه نمی‌تونه بازش کنه. روی **Done** بزن، بعد برو
**System Settings → Privacy & Security**، برو پایین و کنار Tondar روی **Open Anyway** بزن.
(یا توی Terminal دستور `xattr -cr /Applications/Tondar.app` رو بزن.)

yt-dlp و ffmpeg همراه برنامه هستن. قبل از نصب افزونه، یه بار تندر رو باز کن تا مرورگرها بتونن پیداش کنن.

- **به‌روزرسانی:** نسخه‌ی جدید رو بکش روی Applications و جایگزین قبلی کن.
- **حذف:** تندر رو از Applications بنداز توی سطل زباله.

### نصب روی لینوکس

دبیان ۱۳ یا اوبونتو ۲۴.۱۰ به بالا.

۱. فایل **`tondar_x.y.z_all.deb`** رو از [صفحه‌ی آخرین نسخه](https://github.com/reza-hashemian/tondar/releases/latest) دانلود کن.

۲. توی ترمینال، توی همون پوشه‌ای که فایل رو دانلود کردی، این دستور رو بزن:

</div>

```sh
sudo apt install ./tondar_*_all.deb ffmpeg
```

<div dir="rtl">

۳. برنامه‌ی **Tondar Download Manager** رو از منوی برنامه‌ها باز کن. از منوی ☰ گزینه‌ی **Install / Update yt-dlp** رو بزن.

۴. برای اینکه زمان‌بندی و دکمه‌ی مرورگر همیشه کار کنن: از ☰ برو **Preferences** و **Start on login** رو روشن کن.

- **به‌روزرسانی:** فایل `.deb` جدید رو همین‌طوری نصب کن. بعد از ☰ گزینه‌ی **Quit** رو بزن و برنامه رو دوباره باز کن.
- **حذف:** دستور `sudo apt remove tondar` رو بزن.

### افزونه برای مرورگر

اول خود برنامه رو نصب کن.

**کروم، اج یا کرومیوم:**

۱. آدرس `chrome://extensions` رو باز کن. توی Edge آدرسش `edge://extensions` هست.

۲. گزینه‌ی **Developer mode** رو روشن کن.

۳. روی **Load unpacked** بزن و پوشه‌ی افزونه رو انتخاب کن:
- ویندوز: `%LOCALAPPDATA%\Programs\Tondar\extension\chrome` (این متن رو توی کادر آدرس پنجره paste کن)
- مک: `/Applications/Tondar.app/Contents/Resources/extension/chrome` (توی پنجره ⌘⇧G رو بزن و این مسیر رو paste کن)
- لینوکس: `/usr/share/tondar/extension/chrome`

۴. آیکون تندر رو به نوار ابزار pin کن. وقتی روش بزنی باید **Connected** نشون بده.

این پوشه رو جابه‌جا یا پاک نکن، چون مرورگر افزونه رو از همون‌جا می‌خونه.

**فایرفاکس** (نسخه‌ی ۱۴۰ به بالا):

۱. فایل **`tondar-firefox-x.y.z.xpi`** رو از [صفحه‌ی آخرین نسخه](https://github.com/reza-hashemian/tondar/releases/latest) دانلود کن.

۲. برو `about:addons`، روی ⚙ بزن، **Install Add-on From File** رو انتخاب کن و فایل رو بده. یا فایل رو بکش و روی پنجره‌ی فایرفاکس رها کن. بعد روی **Add** بزن.

افزونه توسط Mozilla امضا شده، پس روی فایرفاکس معمولی نصب می‌شه.

### استفاده از تندر

**اضافه کردن دانلود**
- دکمه‌ی **+** یا Ctrl+N رو بزن و لینک رو بده. اگه لینکی کپی کرده باشی، خودش پر می‌شه. می‌تونی لینک رو بکشی و روی پنجره رها کنی.
- **Download Later** دانلود رو متوقف اضافه می‌کنه، **Schedule** اون رو به زمان‌بندی اضافه می‌کنه و **Start Download** همون موقع شروعش می‌کنه.
- وقتی افزونه نصب باشه، کلیک روی لینک دانلود توی مرورگر به‌جای دانلود مرورگر، پنجره‌ی **New Download** تندر رو باز می‌کنه. 
- با **راست‌کلیک** روی هر لینک (یا ویدیو، صدا و عکس) گزینه‌ی **Download with Tondar** میاد. روی دکمه‌های دانلودی که لینک واقعی نیستن هم همین گزینه نشون داده می‌شه.
- اگه می‌خوای مرورگر دوباره خودش دانلود کنه، روی آیکون تندر توی نوار ابزار بزن و تیک **Take over browser downloads** رو بردار.
- اگه چند تا لینک رو پشت سر هم از مرورگر بفرستی، یکی‌یکی باز می‌شن: پنجره‌ی **New Download** می‌نویسه «N more links from the browser» و دکمه‌ی **Add All Now** بقیه رو یه‌جا اضافه می‌کنه.

**ویدیو و پلی‌لیست**
- با دکمه‌ی **×** کنار دکمه‌ی Download، اون دکمه توی همون صفحه بسته می‌شه. با رفرش صفحه دوباره برمی‌گرده.
- **بدون لاگین:** اگه سایتی برای پیدا کردن ویدیو لاگین بخواد، تندر صفحه رو مثل یه بازدیدکننده‌ی عادی می‌خونه و لینک‌های ویدیویی که صفحه نشون می‌ده رو لیست می‌کنه (توی مرورگر با برچسب **no login needed** و توی پنجره‌ی New Download زیر **Quality**).
- موس رو روی ویدیوی هر سایتی ببر و دکمه‌ی نارنجی **Download** رو بزن. لیست فایل‌ها و استریم‌های ویدیوی اون صفحه رو نشون می‌ده، به‌علاوه‌ی گزینه‌ی **Best quality (yt-dlp)**.
- یا لینک یوتیوب، آپارات، اینستاگرام و… رو بده، **Type** رو روی **Video / stream** بذار و کیفیت رو انتخاب کن. گزینه‌ی **Audio only** (فقط صدا) آخر لیسته.
- برای لینک پلی‌لیست، همه‌ی ویدیوها با تیک نشون داده می‌شن. ویدیوها توی پوشه‌ای به اسم پلی‌لیست و به ترتیب شماره‌گذاری ذخیره می‌شن. اگه فقط یه ویدیو می‌خوای، **Download entire playlist** رو خاموش کن.
- **فرمت:** ردیف **Format** فرمت‌هایی که سایت داره (MP4، WebM و…، زیر **Formats on this site**) و تبدیل بدون افت کیفیت به MKV/MP4 رو نشون می‌ده. توی صفحه هم پایین منوی دکمه‌ی نارنجی، زیر **Format** همین انتخاب هست (Auto / MP4 / MKV / WebM / Audio only).
- **دانلود فقط یه تیکه از ویدیو:** **Download only a part** (توی منوی دکمه‌ی نارنجی با علامت ✂) رو روشن کن و **From** و **To** رو بنویس (مثلاً `1:20`، `90` یا `1:02:03`؛ اگه **To** خالی باشه تا آخر ویدیو). توی صفحه دکمه‌ی **Now** زمان فعلی پخش‌کننده رو برمی‌داره. اسم فایل جدا می‌شه، مثل `Video (clip 1m20s-2m05s).mp4`. برش از نزدیک‌ترین کی‌فریم شروع می‌شه، پس ممکنه یکی دو ثانیه زودتر شروع بشه.
- سایت‌ها زیاد تغییر می‌کنن. اگه دانلود ویدیو کار نکرد، از ☰ گزینه‌ی **Install / Update yt-dlp** رو بزن.
- **خطای یوتیوب «Sign in to confirm you're not a bot»:** یوتیوب این رو روی بعضی شبکه‌ها (VPN، پروکسی، اینترنت‌های اشتراکی) می‌پرسه و ربطی به لینک نداره. تندر اول بدون حساب امتحان می‌کنه، بعد با ورود یوتیوبی که مرورگر همراه لینک فرستاده (پس وقتی توی youtube.com وارد حسابت هستی، ویدیو رو با **Download with Tondar** بفرست). یا توی Preferences گزینه‌ی **Sign-in from browser** رو روی مرورگرت بذار تا yt-dlp ورود یوتیوب رو از همون مرورگر بخونه (کروم و اج رو قبلش کامل ببند). بعد از هر تغییر، دکمه‌ی **Try Again** کنار **Details** رو بزن. تندر چیزی ذخیره نمی‌کنه.

**پنجره‌ی پیشرفت و «Download Complete»**
- هر دانلودی که شروع کنی یه پنجره‌ی کوچیک جدا داره: درصد، سرعت، زمان باقی‌مونده، حجم، پوشه و دکمه‌های **Pause / Resume**، **Cancel** و **Hide**. از ⋮ و **Progress Window** دوباره باز می‌شه.
- وقتی تموم شد، پنجره‌ی **Download Complete** سه گزینه داره: **Open** (باز کردن فایل)، **Open Folder** (باز کردن پوشه) و **Close**.
- هر دو رو می‌تونی توی Preferences خاموش کنی (**Show a progress window** و **Show a window when a download finishes**).

**کپی کامل سایت (Clone Website)** — دکمه‌ی 🌐 بالای پنجره، یا ☰ و **Clone Website…**، یا Ctrl+Shift+N، یا راست‌کلیک روی صفحه و **Clone this website with Tondar**
- آدرس رو بده و انتخاب کن تا کجا بره: **The whole website** (کل سایت)، یا خاموشش کن و **Link depth** رو عدد بده (۰ یعنی فقط همین صفحه، ۱ یعنی این صفحه و صفحه‌هایی که بهشون لینک داده، ۵ یعنی صفحه‌ها تا ۵ لینک فاصله). **Only this website** کپی رو توی همون سایت نگه می‌داره؛ **Include subdomains** زیردامنه‌ها مثل `blog.example.com` و `shop.example.com` رو هم می‌گیره؛ اگه خاموشش کنی لینک سایت‌های دیگه هم دنبال می‌شن (اون موقع حتماً عمق بذار). بقیه: **At most** (حداکثر تعداد صفحه)، عکس/استایل/فونت از سرورهای دیگه (CDN)، فایل‌هایی که صفحه‌ها بهشون لینک دادن (PDF، ZIP و…)، محدودیت حجم هر فایل، و **Respect robots.txt**.
- هر آدرس فقط یه بار دانلود می‌شه: `#بخش‌ها`، پارامترهای ردیابی (`utm_…`، `fbclid` و…)، ترتیب پارامترها، `dir/` و `dir/index.html` و ریدایرکت‌ها شناخته می‌شن و فایل‌های یکسان با آدرس‌های مختلف فقط یه بار ذخیره می‌شن.
- **به‌روز کردن کپی:** همون آدرس رو دوباره توی همون پوشه کپی کن (پنجره گزینه‌ی **Update the copy in this folder** رو نشون می‌ده)، یا از ⋮ گزینه‌ی **Download Again** رو بزن: تندر از سرور می‌پرسه از دفعه‌ی قبل چی عوض شده (ETag / Last-Modified) و فقط صفحه‌ها و فایل‌های تغییرکرده رو دانلود می‌کنه.
- پوشه و اسم رو انتخاب کن. لینک‌ها طوری بازنویسی می‌شن که نسخه‌ی کپی بدون اینترنت توی مرورگر باز بشه (**Open Website** صفحه‌ی اولش رو باز می‌کنه). توقف و ادامه مثل فایل‌ها کار می‌کنه و فایل‌هایی که ذخیره نشدن توی `_tondar-failed.txt` لیست می‌شن.
- سایت‌هایی که صفحه‌هاشون رو با جاوااسکریپت می‌سازن (وب‌اپ‌ها) فقط تا جایی که HTML دارن کپی می‌شن.

**مدیریت دانلودها**
- دکمه‌ی ▶ یا ⏸ هر ردیف دانلود رو ادامه می‌ده یا متوقف می‌کنه. دکمه‌های بالای پنجره همه رو با هم. دانلودها از همون‌جایی که موندن ادامه پیدا می‌کنن، حتی بعد از ری‌استارت.
- دکمه‌ی ⋮ هر ردیف (یا راست‌کلیک) این گزینه‌ها رو داره:
  - باز کردن فایل یا پوشه
  - کپی آدرس
  - **Refresh Download Address**: وقتی لینک منقضی شده، لینک جدید رو بده تا دانلود از همون‌جا ادامه پیدا کنه
  - دانلود دوباره
  - اضافه یا حذف از زمان‌بندی
  - حذف از لیست، یا پاک کردن خود فایل
- نوار کنار صفحه دانلودها رو بر اساس وضعیت (Downloading، Unfinished، Completed، Scheduled) و نوع (Video، Music، Compressed و…) جدا می‌کنه. با کادر جستجو هم می‌تونی دانلود رو پیدا کنی.
- بستن پنجره برنامه رو نمی‌بنده و دانلودها ادامه پیدا می‌کنن. آیکون تندر کنار ساعت (Notification area ویندوز؛ اگه نمی‌بینیش روی **^** بزن و برای همیشه‌ای دیده شدن بکشش روی تسک‌بار) یا توی System tray لینوکس می‌مونه. با کلیک روش تندر باز می‌شه و با راست‌کلیک منوی **Show Tondar**، **New Download**، **Clone Website**، **Resume All**، **Pause All**، **Preferences** و **Quit Tondar** میاد. روی GNOME برای دیدن آیکون، افزونه‌ی «AppIndicator and KStatusNotifierItem Support» لازمه (اوبونتو خودش داره). برای بستن کامل از ☰ هم می‌شه **Quit** رو زد.

**زمان‌بندی** (از ☰ گزینه‌ی **Scheduler**)
- **Enable scheduler** رو روشن کن. ساعت **شروع**، اگه خواستی ساعت **توقف**، و **روزهای** هفته رو انتخاب کن.
- دانلودها رو با دکمه‌ی **Schedule** یا با ⋮ و بعد **Add to Schedule** اضافه کن. اگه بخوای، با گزینه‌ی **Also start all other unfinished downloads** بقیه‌ی دانلودهای نیمه‌تموم هم شروع می‌شن.
- اگه ساعت توقف گذاشته باشی، دانلودهای نیمه‌تموم اون موقع متوقف می‌شن و سر ساعت شروع بعدی ادامه پیدا می‌کنن.
- **وقتی تموم شد**: کاری نکنه، برنامه بسته بشه، یا **کامپیوتر خاموش بشه**. برای خاموش شدن ۶۰ ثانیه فرصت لغو داری.
- سر ساعت شروع، تندر باید در حال اجرا باشه. پس **Start on login** رو روشن کن.

**پروکسی** (از ☰ گزینه‌ی **Proxy**)
- **System settings** از پروکسی سیستم استفاده می‌کنه، **No proxy** مستقیم وصل می‌شه، و **Manual** برای وارد کردن پروکسی دستیه.
- حالت Manual: نوع **HTTP** یا **SOCKS5** رو انتخاب کن، بعد آدرس و پورت، و اگه لازمه نام کاربری و رمز. مثال‌ها:
  - v2rayN روی همین سیستم: نوع SOCKS5، آدرس `127.0.0.1`، پورت `10808`
  - پروکسی روی یه کامپیوتر دیگه‌ی شبکه: IP همون سیستم (مثلاً `192.168.1.10`). توی برنامه‌ی پروکسی اون سیستم هم گزینه‌ی Allow connections from LAN رو روشن کن.
- دکمه‌ی **Test** رو بزن تا اتصال بررسی بشه. پروکسی روی همه‌ی دانلودها، گرفتن اطلاعات ویدیو و آپدیت yt-dlp اعمال می‌شه.

**تنظیمات** (از ☰ گزینه‌ی **Preferences**)
- پوشه‌ی دانلود، و **Sort into sub-folders**: مرتب کردن فایل‌ها توی پوشه‌های Video، Music، Compressed و…
- **Remember the folder I choose**: وقتی توی پنجره‌ی New Download پوشه‌ای رو دستی انتخاب کنی، دانلودهای بعدی هم همون‌جا ذخیره می‌شن. با دکمه‌ی ↶ کنارش یا **Forget** به پوشه‌ی پیش‌فرض برمی‌گرده.
- **Simultaneous downloads**: تعداد دانلود هم‌زمان. **Connections per download**: تعداد اتصال هر دانلود، که بیشترش معمولاً سریع‌تره. **Speed limit**: محدودیت سرعت.
- **Keep running when window is closed**: کار کردن در پس‌زمینه. **Start on login**: اجرا موقع روشن شدن سیستم. **Ask before downloading from the browser**: پرسیدن قبل از دانلودهایی که از مرورگر میان. و نوتیفیکیشن‌ها.
- **Show a progress window**: پنجره‌ی پیشرفت جدا برای هر دانلود. **Show a window when a download finishes**: پنجره‌ی Download Complete.
- **Sign-in from browser** (زیر Video downloads): وقتی یوتیوب بپرسه ربات نیستی، yt-dlp ورود یوتیوب رو از این مرورگر بخونه (پیش‌فرض **Don't use**).

### رفع مشکل

- **آیکون افزونه App not found نشون می‌ده:** مطمئن شو تندر نصبه و مرورگر رو ری‌استارت کن. روی ویندوز، نصب‌کننده رو یه بار دیگه اجرا کن.
- **دکمه‌ی Download روی ویدیو نمیاد:** بعد از نصب افزونه صفحه رو رفرش کن. ویدیوهای خیلی کوچیک دکمه نمی‌گیرن. در این صورت از آیکون افزونه توی نوار ابزار استفاده کن.
- **یوتیوب می‌گه «Sign in to confirm you're not a bot»:** ویدیو رو وقتی توی youtube.com وارد حسابت هستی از مرورگر بفرست، یا توی Preferences گزینه‌ی **Sign-in from browser** رو روی مرورگرت بذار (کروم/اج رو قبلش ببند) و **Try Again** رو بزن. خاموش کردن VPN/پروکسی یا عوض کردن شبکه هم کمک می‌کنه. برای بقیه‌ی خطاهای یوتیوب از ☰ گزینه‌ی **Install / Update yt-dlp** رو بزن.
- **آیکون تندر کنار ساعت ویندوز نیست:** روی **^** (آیکون‌های مخفی) بزن؛ برای همیشه دیده شدن، آیکون رو بکش روی تسک‌بار.
- **دانلود با خطای HTTP 403 یا "link expired" متوقف شد:** از ⋮ گزینه‌ی **Refresh Download Address** رو بزن و لینک جدید همون فایل رو بده.
- **ویدیو صدا نداره یا صدا و تصویرش جدا مونده:** ffmpeg نصب نیست. روی لینوکس دستور `sudo apt install ffmpeg` رو بزن. روی ویندوز ffmpeg همراه برنامه هست.
- **دانلودهای زمان‌بندی‌شده شروع نشدن:** تندر باید سر اون ساعت در حال اجرا باشه. **Start on login** رو روشن کن و **Enable scheduler** و روزهای هفته رو هم چک کن.
- **تست پروکسی شبکه خطا می‌ده:** توی برنامه‌ی پروکسی گزینه‌ی Allow connections from LAN رو روشن کن. IP، پورت و نوع پروکسی (HTTP یا SOCKS5) رو هم چک کن.

</div>

---

## For developers

```sh
./tools/build-deb.sh                 # build/tondar_<version>_all.deb
cd src && TONDAR_APP_ID=io.github.tondar.TondarDev python3 -m tondar   # run next to the installed copy
```

**Releases.** The Windows installer is built by GitHub Actions (`.github/workflows/build.yml`) with MSYS2,
PyInstaller and Inno Setup; the macOS `.dmg` files (Apple Silicon and Intel) with Homebrew's GTK and
PyInstaller (`tools/build-macos.sh`). Both bundle a small ffmpeg built by `tools/build-ffmpeg.sh` that can
only merge and remux, which is all yt-dlp needs from it. Every push builds all packages (see the **Actions** tab). To publish a release:

1. Raise `VERSION` in `src/tondar/__init__.py` (Mozilla signs each version only once).
2. Commit, then `git tag vX.Y.Z && git push origin main vX.Y.Z`.

The release then gets the `.deb`, `Tondar-Setup-X.Y.Z.exe`, the two macOS `.dmg` files and the signed `tondar-firefox-X.Y.Z.xpi`.
Firefox signing uses Mozilla's unlisted channel (not listed in the add-ons store) and needs two repository
secrets, **AMO_JWT_ISSUER** and **AMO_JWT_SECRET**, from <https://addons.mozilla.org/developers/addon/api/key/>.

```
src/tondar/
  core.py        download list, queue, scheduler, settings
  http_task.py   multi-connection resumable downloader
  media.py       video/stream/playlist downloads through yt-dlp
  net.py         proxy support (HTTP, built-in SOCKS5)
  ipc.py         single-instance support on Windows and macOS
  macos.py       macOS: browser bridge registration, login item
  app.py         application, command line, notifications
  window.py      main window
  dialogs.py     New Download, Preferences, Browser Integration
native-host/     bridge between the browser extension and the app (native messaging)
extension/       browser extension (Manifest V3, Chrome and Firefox)
windows/         PyInstaller spec, Inno Setup script, native messaging manifests
macos/           PyInstaller spec for Tondar.app
tools/           build scripts
```
