# PRISM

<img src="ui/logo.svg" width="120" alt="PRISM">

**A privacy-first research browser, built and maintained by [Synterra](#about-synterra).**

PRISM blocks ads, trackers, malware and phishing out of the box, keeps your logins apart in containers, sends DNS encrypted, and puts a full developer toolkit one shortcut away.
Its **Privacy Time Machine** lets you rewind any page and watch what it tried to do to you.
Built only with **Python**: the engine, privacy and ad blocking, and **HTML / CSS / JS**: the whole visible UI.
Search runs through **[SearXNG](https://docs.searxng.org)**, open-source metasearch with no ads, tracking or profile.

## Run

```bash
py -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python update_blocklists.py     # recommended: ~260k ad/tracker + ~150k malware/phishing domains
.venv\Scripts\python prism.py
```

To install PRISM like a normal app instead (no Python needed on the machine), see [Installers](#installers).

On Arch Linux, install it as a pacman package (see [Arch Linux package](#installers)), or see [SETUP_ARCH.md](SETUP_ARCH.md) to run it from source (written so Claude Code can do the whole setup for you).

## Editions: full and partner

PRISM comes in two editions, set per install by a `deployment.json` file next to `prism.py` (git-ignored, so each copy has its own):

| Edition | How | What's in it |
|---|---|---|
| **Full** (default) | no `deployment.json` | everything |
| **Partner** | `deployment.json` with `{"edition": "partner"}` (see `deployment.example.json`) | everything except the **terminal** and the **password vault** |

The partner edition is a locked-down copy for machines you hand to someone else: copy `deployment.example.json` to `deployment.json` in their copy.
The left-out features are not just hidden: their code never starts and the panel refuses their actions.
The dashboard footer shows which edition is running.
If `deployment.json` is unreadable or names an unknown edition, PRISM runs as the partner edition rather than the full one.

## Keeping PRISM secure

PRISM's web engine is Qt WebEngine, which bundles its own **Chromium**.
Chromium security fixes only reach PRISM when Qt ships a new WebEngine release *and* PRISM installs it, so:

- **Versions are pinned** in `requirements.txt`, so every install runs the same Chromium.
- **PRISM checks for updates** a few seconds after start and twice a day (`updates.py`): it compares `version.py` with the one on GitHub, and the pip-installed Qt WebEngine with the newest one on PyPI. A newer one shows up as a notice on the dashboard and a toast. The footer shows the Chromium version and its security-patch level. Turn the check off with `"updateCheck": false` in `deployment.json`.
- **Update routine** (whoever maintains PRISM), when the dashboard reports a new Qt WebEngine:
  1. `.venv\Scripts\python -m pip install -U PyQt6 PyQt6-WebEngine`
  2. `.venv\Scripts\python -m pip freeze` and copy the new versions into `requirements.txt`
  3. test PRISM, raise `VERSION` in `version.py`, commit and push
- **Everyone else**, when the dashboard says a new PRISM is out: `git pull`, then `.venv\Scripts\python -m pip install -r requirements.txt`, then restart PRISM.

When Qt WebEngine comes from the system instead of pip (for example Arch's `python-pyqt6-webengine`), the system's package manager updates it and PRISM only checks its own version.

## Installers

PRISM can be built into a standalone app plus an installer, so people can install it without Python or git.
The build bundles Python, Qt WebEngine (Chromium), the UI and fresh blocklists; it is built with PyInstaller as a folder app (`dist/PRISM/`) rather than one big .exe, because a one-file build would unpack ~600 MB to a temp folder on every start.

| | Windows | Linux |
|---|---|---|
| Build on | a Windows PC (PyInstaller can't cross-compile) | a Linux PC of the target architecture |
| Needs | Python 3.14 x64 with the `py` launcher, [Inno Setup 6.7+](https://jrsoftware.org/isdl.php) (`winget install JRSoftware.InnoSetup`) | Python 3.14 |
| Command | `packaging\build_windows.bat` | `packaging/build_linux.sh` |
| Executable | `dist\PRISM\PRISM.exe` | `dist/PRISM/PRISM` |
| Installer | `dist\PRISM-Setup-<version>.exe` | `dist/PRISM-<version>-linux-x86_64-setup.run` |

Both scripts make their own build environment in `build/venv` (pinned in `requirements.txt` and `packaging/requirements-build.txt`) and download fresh blocklists first (`SKIP_BLOCKLISTS=1` skips that).

**Windows installer.** Not the stock wizard: PRISM's own borderless setup window with rounded corners (native on Windows 11), a side rail with the logo and a live step list, typed headlines, pages that slide in, pill buttons and a glowing progress bar. Built on Inno Setup's pages and logic ([Code] in `packaging/windows/prism.iss`; rail artwork drawn at build time by `packaging/make_installer_art.py`), so updates, silent installs and `/TASKS` work as before. Choose "for me only" (no admin rights, `%LOCALAPPDATA%\Programs\PRISM`) or "for all users" (Program Files). Adds a Start menu entry, an "Update blocklists" entry and an optional desktop shortcut, and registers an uninstaller in Settings → Apps.
Tick **Partner edition** to install the partner edition (it writes `deployment.json` next to `PRISM.exe`).
The installer also registers PRISM as a web browser. To make it your default, tick **Make PRISM my default browser** on the last page, or go to Settings → Apps → Default apps → PRISM → **Set default**. Links from other apps then open as tabs in the PRISM window that is already open (`instance.py`), and starting PRISM again only brings that window to the front.
Silent install: `PRISM-Setup-<version>.exe /VERYSILENT /CURRENTUSER /TASKS="partner"`.

**Linux installer.** `sh PRISM-<version>-linux-x86_64-setup.run`. As a normal user it installs to `~/.local/opt/prism` with a `prism` command in `~/.local/bin` and an app menu entry; with `sudo` it installs for everyone in `/opt/prism`. Options: `--partner`, `--employee`, `--prefix DIR`, `--no-menu`, `-y`, `--help`.
Uninstall with `~/.local/opt/prism/uninstall.sh` (`--purge` also deletes your PRISM data).

**Arch Linux package (pacman).** `packaging/arch/PKGBUILD` turns the repository into a normal pacman package that runs on Arch's own Python and Qt WebEngine, so `pacman -Syu` brings Chromium security fixes:

```bash
sudo pacman -S --needed base-devel git
git clone https://github.com/norik-jusufi/Prism.git
cd Prism/packaging/arch
makepkg -si                     # builds what is committed in this clone, installs it with pacman
```

It installs PRISM to `/usr/lib/prism`, the `prism` command, an app menu entry (also offered as a web browser and for .html files) and its icon.
Default browser: `xdg-settings set default-web-browser prism.desktop`. Partner edition: `echo '{"edition": "partner"}' | sudo tee /usr/lib/prism/deployment.json`.
Update: `git pull`, then `makepkg -si` again. Remove: `sudo pacman -R prism` (your data in `~/.local/share/Synterra/PRISM` stays).

**Updating.** Installed copies tell you when a newer PRISM is out, like source copies do. On Windows the dashboard notice has an **Install update** button: PRISM downloads `PRISM-Setup-<version>.exe` from the GitHub release `v<version>`, checks its size and SHA-256 against the release, installs it silently in the same mode (an all-users install asks for admin rights) and restarts. You can also run a newer installer by hand: when PRISM is already installed it offers **Update** (one click, keeps the folder, edition and shortcuts) or **Change options**. Either way browsing data and settings (in the per-user data folder, see [What PRISM saves](#what-prism-saves)) are untouched.

**Blocklists in an installed PRISM.** The ones bundled at build time are used until you update them: Start menu / app menu → *PRISM - Update blocklists*, or `PRISM --update-blocklists`. Updated lists go to the data folder (`blocklists\`), since the install folder may not be writable.

**Releasing.**
1. Raise `VERSION` in `version.py` (e.g. `1.2.0` or `1.2.0-beta`).
2. Build: `packaginguild_windows.bat` (and `packaging/build_linux.sh` on Linux).
3. Commit, tag `v<VERSION>` and push: `git tag v1.2.0 && git push origin main --tags`.
4. Create the GitHub release for that tag (pushing the tag already started the container build, see below) and attach `dist\PRISM-Setup-<VERSION>.exe` under exactly that name: the one-click update looks for it there. Mark `-beta` versions as pre-releases.

Pushing `version.py` is what makes running copies announce the update, so do step 4 right after step 3. Chromium security fixes reach installed copies only through a new build, so rebuild whenever the dashboard reports a newer Qt WebEngine.

### Container image (GitHub Package)

Every version tag also publishes PRISM as a container image to GitHub Packages, `ghcr.io/norik-jusufi/prism` (`.github/workflows/package.yml`, built from the `Dockerfile`): tags `<version>`, plus `latest` for full releases and `beta` for `-beta` ones. The workflow starts PRISM inside the image before publishing and stops if it doesn't come up.

It's a Linux desktop app in a box, drawing on your screen through X11 (XWayland on Wayland desktops):

```bash
xhost +SI:localuser:$(id -un)
docker run --rm -e DISPLAY -v /tmp/.X11-unix:/tmp/.X11-unix \
  --user $(id -u):$(id -g) --shm-size 1g -v prism-data:/data ghcr.io/norik-jusufi/prism:latest
```

Settings, logins and stats stay in the `prism-data` volume; `docker pull` updates. Chromium's own sandbox is off in the container (the container is the sandbox). Native installs above are smoother; the image is for trying PRISM or running it on a Linux machine without installing anything.

## Search

Searches go to **[SearXNG](https://docs.searxng.org)**: open-source metasearch that asks several search engines for you and returns their results without ads, tracking or a profile of you.
SearXNG runs on many independent servers ("instances"). PRISM uses a list of public ones (`SEARXNG_INSTANCES` in `urls.py`, `searx.be` first).
Public instances are shared and sometimes refuse a search ("Too Many Requests"), or can't be reached. PRISM then skips that instance for 10 minutes and runs the same search on the next one. Browser checks some instances show ("Checking your browser…") pass by themselves.

**Your own instance** is the most private option and is never busy: set it in Panel → Network → Search (for example `https://search.example.org`, or `http://localhost:8080` for one running on your PC; see the [SearXNG install guide](https://docs.searxng.org/admin/installation.html)). It goes first; untick **Use public instances when mine is unreachable** to never search anywhere else.
The dashboard footer shows the instance in use and how many are busy.

## Boot intro

When PRISM opens, a terminal boots it in over the window for about four seconds. The screen powers on like a CRT, `./prism --boot --secure` is typed in key by key, the PRISM banner prints, the live boot log follows (version, Chromium, blocklist sizes, DNS, privacy, containers) with `[ OK ]` checks, and `launch --interface` fills a progress bar before the terminal fades into the browser, which has been loading underneath the whole time. Key clicks, data chirps and a "ready" chime play along: they're synthesized by `sounds.py` the first time (no audio files are shipped) and played with Qt Multimedia.

Click or press any key to skip it, or press **M** to mute it (remembered). It doesn't play when PRISM is started to open a link or a file. Turn it off with `"intro": false` in `settings.json`, or `PRISM_NO_INTRO=1`; only the sound with `"introSound": false`. Drawn by `intro.py` with plain Qt painting, so it costs nothing once it's gone.

## Privacy Time Machine

Press **rewind** in the toolbar (or `Ctrl Shift H`) and PRISM replays what the current page did, on a timeline you can play, pause, scrub and speed up (¼× to 25×):

- **When tracking started**: the first tracker contact, tracking cookie, cross-site cookie, tracking parameter or fingerprinting probe, to the millisecond, marked on the timeline.
- **Data collection**: tracker contacts, cookies (tracking or not), cross-site cookies, fingerprinting (canvas, WebGL GPU identity, audio, font probing, battery, device list, client hints, WebRTC), clipboard reads, storage and IndexedDB writes, beacons, third-party scripts watching your keys and mouse, and permission requests, each marked *stopped*, *got through* or *observed*.
- **External servers**: every host the page contacted, in order, first or third party, tracker or not, and how many requests were stopped; drawn live on a network map.
- **Scripts**: which ran and which PRISM stopped, with the fingerprinting APIs each one used, plus the page's inline scripts.
- **Protections**: which protection stopped what (tracker blocklist, malware shield, your block list, script rules, sandbox, cookie wall, link cleaner, permission guard), plus Do Not Track / GPC, encrypted DNS and the shield.
- **Event stream**: the raw tape, line by line.

Every tab records its last 8 pages; pick an earlier one under **tape**. **re-record** reloads the page and records it from the start, **export** saves the recording as JSON.

The recording is **metadata only**: hosts, resource types, timings, block reasons, and cookie and storage *names*. Never page content, form input, cookie or storage values, request bodies or query strings (page addresses are kept as origin only, scripts as host + file name; **record full URLs** keeps whole addresses, off by default). It lives in memory only: closing the tab drops it and Purge wipes it.
Fingerprinting probes are seen by a small watcher in each page (`timemachine.py`): it only reports that an API was used and by which script host, and wrapped functions look exactly like the originals to the page, so it doesn't make you stand out. Switch it off with **watch fingerprinting APIs**.

## Downloads and files

When a download starts, PRISM asks where to save it in its own popup: rename the file, pick a folder (your default folder, Downloads, Desktop, Documents or one you used recently) or **Browse…** for any folder with the usual system picker. A name that's already taken gets `(1)`, `(2)`, ... instead of overwriting. At the bottom of the popup, **Next time** switches to the standard system Save As dialog, or to saving straight into the default folder without asking. The same choice, the default folder and this session's downloads (progress, Open, Show in folder, Cancel) are in the panel's Downloads section (`Ctrl J`). Sandbox tabs can't download.

The **downloads button** in the toolbar shows a progress ring while files download (a badge counts them when there are several) and flashes a check mark when one is done. Click it for the downloads flyout: live progress, size, speed and time left, with Open, Show in folder and Cancel.

PRISM opens PDFs in its built-in viewer, and shows HTML pages (also saved `.mhtml`), images, SVG, text, JSON and XML files. Open them with `Ctrl O`, **Open file…** in the Downloads section, or from Windows: the installer adds PRISM to **Open with** for these files, and in Settings → Apps → Default apps → PRISM you can make it the default for PDFs too.

## Dashboard

The new-tab page doubles as a live dashboard. It updates up to once a second, only while it is on screen and only the parts whose numbers changed, so an idle dashboard costs nothing:

- **Tiles:** threats blocked, total requests, block rate, tracking parameters stripped, third-party cookies refused, permissions denied.
- **Traffic chart:** blocked vs allowed requests over the last 10 minutes, one bar per 15 seconds. Hover a bar for exact numbers.
- **Top blocked domains** of all time.
- **Activity panel:** session uptime, pages loaded, sites visited, searches, HTTPS share, open tabs, shield exceptions and blocklist size.

Statistics are kept across restarts in `stats.json` (saved every 30 seconds and on exit). Only counters are saved, never the sites you visited: "sites visited" is stored as a number. **Purge** resets them and deletes the file.

## Developer tools

| Feature | How to use it |
|---|---|
| **DevTools** | `F12` / `Ctrl Shift I`. Docked inside the window (bottom, right, or its own window via the buttons on its title bar). Elements, styles, console, sources/debugger, network, performance: everything Chromium has. It follows the active tab. |
| **Split workspace** | `Ctrl \` or the split button opens another pane (up to 4). Click a tab to show it in the focused pane, or right-click a tab and pick "Show in split view". Each pane can have its own device size. |
| **Responsive preview** | `Ctrl Shift M`. Desktop, laptop, tablet, mobile and small-phone presets, custom width × height, rotate. The page really gets that viewport (CSS media queries fire), scaled down to fit if needed. |
| **Design inspector** | `Ctrl Shift C`. Hover any element: box model overlay (margin, border, padding), font, size, line height, colors as hex, WCAG contrast ratio, spacing, layout. Click to pin, hold `Alt` to measure the gap to another element, `↑` selects the parent, `C` copies the CSS, `Esc` exits. |
| **AI design review** | `Ctrl Shift D` or Panel → Design. Claude (Anthropic's hosted API, `claude-opus-5-5`) reviews the current tab for front-end imperfections: layout, spacing, alignment, typography, color and contrast, accessibility, responsiveness, consistency, images. It looks at a screenshot of the visible viewport plus measurements PRISM takes from the page (distinct font sizes and spacing values, WCAG contrast failures, tap targets under 24 px, horizontal overflow, clipped text, distorted or blurry images, skipped heading levels, unlabeled controls). Each issue has a severity, a concrete fix (copyable) and, where it applies, a **Show** button that scrolls to and highlights the element. Add a focus ("the pricing cards") to narrow it; combine with the responsive preview to review mobile layouts. See [Design review and privacy](#design-review-and-privacy). |
| **API tester** | `Ctrl Shift A`. GET, POST, PUT, PATCH, DELETE, HEAD, OPTIONS; query params, headers, body, timeout, redirects. Response status, timing, size, headers and syntax-highlighted JSON. Copy as cURL, save as a bookmark. Requests go out from Python, so there are no CORS limits. |
| **Terminal** | Full edition. ``Ctrl ` ``. Runs commands in cmd or PowerShell in the folder shown (`cd` changes it, `cls` clears, `Ctrl C` stops). One-click git / npm / pip / python / node commands. Line-based programs only: no vim, less or htop. |
| **Source explorer** | Panel → Source. Page HTML with highlighting and search, metadata (meta tags, links, forms, iframes, counts), response headers with a security-header checklist and TLS details, and every loaded resource. |
| **Tab memory monitor** | Panel → Memory. Memory per tab and per PRISM process, with "Discard" to free a background tab. |
| **Dev bookmarks** | Panel → Bookmarks. Links, docs, API endpoints (open straight in the API tester), code snippets and notes, with tags and search. |

`Ctrl B` opens the **PRISM panel**, where all of the above live along with the site and security tools below.

## Security

| Feature | What it does |
|---|---|
| **Website trust score** | The number next to the address (click it). Starts at 100 and loses points for observable risks: no HTTPS, mixed content, known trackers, many third parties, refused cross-site cookies, analytics/ad cookies, certificate problems, missing security headers, malware lists. Every deduction is listed. |
| **Tracker map** | Panel → Site → Tracker map. Every third-party domain the page contacted, sized by requests, colored by blocked tracker / tracker that got through / other third party. |
| **Cookie visualizer** | Panel → Site → Cookies. Every cookie the site set, with flags (Secure, HttpOnly, SameSite), expiry, size and its purpose where recognizable (session, security, analytics, advertising, consent…), plus the cross-site cookies PRISM refused. Delete one or all. |
| **Script control** | Panel → Site → Scripts. Turn JavaScript off per site, block all third-party scripts per site, or block single script hosts. Saved per site. |
| **Containers** | Default, Work, Personal, Banking and Development. Each is its own isolated session: cookies, logins, storage and cache never cross. The caret next to `+` (or right-click `+`) opens a tab in any container. Turn on **Remember logins** for a container (Panel → Containers) to stay signed in after closing PRISM. |
| **Temporary sessions** | `Ctrl Shift N`. A fresh container that is destroyed with all its data when its last tab closes. |
| **Website sandbox** | Right-click a link (or use the `+` menu, or Panel → Containers): scripts off until you allow them, every third-party request blocked, no downloads, no permissions, no site storage, its own throwaway profile. |
| **Network protection** | Malware, phishing and cryptominer domains (URLhaus, Phishing Army, NoCoin) get a warning page instead of loading. Third-party scripts served from bare IP addresses are blocked. Add your own hosts to block everywhere. |
| **Encrypted DNS** | Panel → Network. DNS-over-HTTPS via Cloudflare, AdGuard or Google, "with fallback" or "strict" (never plain DNS). PRISM runs a small local proxy that resolves every hostname over HTTPS; TLS to the sites stays end-to-end. PRISM's own requests (security-header checks, API tester, Meta stats, update check) use it too. Applies after a restart. |
| **Permission control center** | Panel → Permissions. Ask / allow / block defaults for camera, microphone, location, clipboard, notifications, screen sharing, pointer lock and local fonts, plus per-site exceptions. Sites that ask get a prompt bar under the toolbar. |
| **Password vault** | Panel → Vault (full edition). AES-256-GCM, key from your master password via scrypt (N=2^17; older vaults are upgraded when next unlocked), stored only on this computer, auto-locks after 5 minutes. Fill logins into the matching HTTPS site, copy (clipboard clears after 20 s), generate strong passwords. |

## Privacy

| Feature | What it does |
|---|---|
| Off-the-record session | No cookies, cache, history or storage written to disk. Everything is gone when you close the window, except in containers where you turned on **Remember logins**. |
| **Remember logins** | Opt-in, per container. That container keeps its cookies and site storage on disk, in its own folder, so you stay signed in. Third-party cookies and trackers are still blocked, the cache stays in memory and history is never saved. Turning it off, or **Forget logins**, erases the folder. |
| **Purge** button | Closes every tab and wipes cookies, cache and history right away. Click it twice to confirm. Saved logins in remembering containers are kept; use **Forget logins** for those. |
| Ad / tracker blocking | Every request is checked against the blocklists and blocked requests never leave the machine. The shield shows the count for the current page. |
| Cosmetic filtering | Hides the empty ad slots left behind after blocking (`blocklists/cosmetic.css`). |
| Shield toggle | Click the shield to turn blocking off for one site that breaks. This lasts for the session only. |
| Tracking-param stripping | Removes `utm_*`, `fbclid`, `gclid`, `msclkid` and similar parameters before the page loads. |
| DNT + GPC | Sends `DNT: 1` and `Sec-GPC: 1` on every request. |
| Third-party cookies | Blocked. |
| Permissions | Nothing is granted without your say: the defaults ask (notifications and local fonts are blocked), sandbox tabs deny everything. |
| WebRTC | Shows only public interfaces, so your LAN IP does not leak. |
| WebGL | Disabled: blocks GPU fingerprinting and avoids a Qt 6.12 crash on WebGL pages (e.g. github.com). |
| Fingerprinting | Sends a generic Chrome user-agent (with the Chromium version PRISM really runs) instead of the unique "QtWebEngine" one. No pop-ups, pings, DNS prefetch or background networking. |
| Local files | An HTML file opened from disk loads its own images, styles, scripts and fonts from its folder (or below it), and nothing else: it can't read other files from script (fetch/XHR blocked for files), can't load files outside its folder, and can't reach the internet. Sandbox tabs never get file access. |

## Shortcuts

| Keys | Action |
|---|---|
| `Ctrl K` | Search (new-tab box or address bar) |
| `Ctrl L` / `F6` | Focus address bar |
| `Ctrl T` / `Ctrl W` / `Ctrl Shift T` | New tab / close tab / reopen closed tab |
| `Ctrl Tab`, `Ctrl 1-9` | Switch tabs |
| `Alt ←/→`, `Ctrl R` | Back / forward / reload |
| `Ctrl F` | Find in page |
| `Ctrl O` | Open a file (PDF, HTML, image, text) |
| `Ctrl J` | Downloads |
| `Ctrl Shift H` | Privacy Time Machine (`Space` play/pause, `←/→` step, `R` rewind and replay, `Esc` back) |
| `Ctrl + / - / 0` | Zoom |
| `F12` / `Ctrl Shift I` | DevTools (docked) |
| `Ctrl B` | PRISM panel |
| ``Ctrl ` `` | Terminal |
| `Ctrl Shift A` | API tester |
| `Ctrl Shift S` | Site report (trust score, cookies, trackers, scripts) |
| `Ctrl \` | Split view |
| `Ctrl Shift M` | Responsive preview |
| `Ctrl Shift D` | AI design review |
| `Ctrl Shift C` | Design inspector |
| `Ctrl Shift N` | Temporary session |
| `F11` | Fullscreen |
| `Ctrl Shift Del` | Purge session |

Typing in the address bar opens a page if the text looks like an address (`github.com/x`, `localhost:8000`).
Anything else becomes a SearXNG search, so `os.path.join` or `main.py` gets searched.

## Layout

```
prism.py               start-up: Chromium flags, encrypted DNS, then the window
paths.py               where PRISM's files are, from source or as a built app
window.py              main window: tabs, panes, search fallback, permissions, dashboard
containers.py          container profiles and their management
tabs.py                one tab: page, view, request log
workspace.py           split-view panes and device presets
devtools.py            docked DevTools, design inspector, responsive preview
bridge.py              what the toolbar (ui/chrome.js) can call
urls.py                local UI pages, search engines, address-bar parsing
theme.py               Qt-native styling, icons, Windows title bar
edition.py             full / partner edition (deployment.json)
updates.py             update and Chromium security check
intro.py               boot intro (terminal animation at start)
sounds.py              intro sound effects, synthesized into WAVs on first use
downloads.py           where downloads go: the save popup, the session's download list, the toolbar flyout
timemachine.py         Privacy Time Machine: per-tab recordings, fingerprinting watcher, its view's backend
version.py             PRISM version (bump for every release)
panel.py               backend for the PRISM panel (all panel actions and data)
designai.py            AI design review: page measurements, screenshot, Claude API call
adblock.py             blocklists, malware lists, script rules, request interceptors
siteintel.py           per-tab request log, tracker map, cookie purposes, headers, trust score
dohproxy.py            encrypted DNS: local proxy resolving hostnames over DNS-over-HTTPS
vault.py               encrypted password vault (AES-256-GCM + scrypt)
apitester.py           HTTP client for the API tester
terminal.py            command runner for the terminal
memory.py              per-process memory (Win32 API via ctypes)
storage.py             settings, per-site rules, dev bookmarks
stats.py               dashboard statistics (counters saved to stats.json)
update_blocklists.py   downloads ad/tracker lists + malware/phishing/cryptominer lists
blocklists/            builtin.txt, cosmetic.css, security/, downloaded/ (git-ignored)
ui/                    chrome.* (toolbar), newtab.* (dashboard), panel.* (PRISM panel),
                       timemachine.* (Privacy Time Machine), inspector.js (design inspector),
                       warning.html, theme.css, logo.svg
assets/                app icon (icon.svg -> icon.png -> icon.ico)
packaging/             installers: prism.spec (PyInstaller), build_windows.bat + windows/prism.iss
                       (Inno Setup), make_installer_art.py, build_linux.sh + linux/ (self-extracting installer), make_icon.py
```

To add your own blocks, drop any `.txt` file into `blocklists/`.
It can use hosts format, `||domain^`, or plain domains. `@@||domain^` allows a domain.

## What PRISM saves

Browsing data (history, cookies, cache, site storage) is never written to disk.
Only what you set up yourself, plus dashboard counters, is saved in `%APPDATA%\Synterra\PRISM` (on Linux `~/.local/share/Synterra/PRISM`, readable only by you):

- `settings.json`: permission defaults and site exceptions, per-site script rules, your block list, encrypted DNS, terminal and download settings (save mode, default and recent folders), and the Time Machine's two switches. Its recordings are never saved.
- `sounds/`: the intro's sound effects, generated on first start.
- `bookmarks.json`: dev bookmarks.
- `vault.prism`: the password vault, encrypted.
- `stats.json`: dashboard counters and top blocked domains (no visited sites).
- `design.json`: the Anthropic API key for the design review, if you pasted one, encrypted with Windows DPAPI. On other systems a pasted key is kept in memory only.
- `logins\`: only for containers with **Remember logins** on: their cookies and site storage, one folder each.

### Design review and privacy

The design review is the one PRISM feature that sends page content to an outside service, so it only runs when you press **Review**.
Then PRISM sends `api.anthropic.com` a screenshot of the visible part of the active tab and the measurement digest, and nothing else: no cookies, storage, history or form values (the measuring script never reads them).
Sandbox tabs are never sent. Anything visible in the screenshot does go to Anthropic, so don't review pages that show confidential data.
The request goes through the encrypted-DNS proxy when that is on.

Credentials: a key pasted in Panel → Design, otherwise `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` or an `ant auth login` profile.
Each review is billed to that Anthropic account (one screenshot plus a few thousand tokens of measurements in, the issue list out).
If Claude declines a request, Anthropic's server-side fallback re-runs it on another model; the panel says which model answered.

For the trust score's header check, PRISM fetches each page's response headers once more, separately and without cookies.

## About Synterra

PRISM is made by **Synterra**, who build, run and maintain it. Follow Synterra on Facebook: [@synterracode](https://www.facebook.com/synterracode).

Found a bug or want a feature? [Open an issue](https://github.com/norik-jusufi/Prism/issues).
