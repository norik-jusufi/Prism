# PRISM setup on Arch Linux: instructions for Claude Code

You are Claude Code on the user's Arch Linux machine. The user has cloned this repository and wants PRISM fully set up and runnable. Do everything below without asking, except where a step says to ask. Report what you did at the end.

PRISM is a PyQt6 + Qt WebEngine browser. It was developed on Windows; on Linux every Windows-only feature already checks `sys.platform` and falls back, so **no code changes should be needed**. Only touch code if a step fails and the fix is clearly a Linux portability bug, and tell the user what you changed.

## 0. Ground rules

- Work in the repository root (the folder containing `prism.py`).
- Never run `pip install` outside a virtual environment, and never `sudo pip`. Arch marks its Python as externally managed (PEP 668).
- Use `sudo pacman` for system packages. If `sudo` needs a password you can't enter, give the user the exact command to run and wait.
- Don't commit, push, or edit files outside the repo, except the desktop launcher in step 5.
- Don't set `QTWEBENGINE_DISABLE_SANDBOX=1` unless step 4 shows a sandbox error, and say so if you do. It turns off a security layer.

## 1. Check the machine

```bash
uname -m                                   # expect x86_64
python --version                           # Arch ships a current Python 3
echo "XDG_SESSION_TYPE=$XDG_SESSION_TYPE WAYLAND_DISPLAY=$WAYLAND_DISPLAY DISPLAY=$DISPLAY"
```

- If the architecture is not `x86_64` (for example `aarch64`), use **route A** only. pip wheels for PyQt6-WebEngine may not exist on ARM.
- If neither `WAYLAND_DISPLAY` nor `DISPLAY` is set, you're not in a graphical session. Do the install steps, skip the launch test in step 4, and tell the user to run `python prism.py` from a terminal on their desktop.

## 2. Install dependencies (pick one route)

### Route A: Arch packages (preferred)

```bash
pacman -Si python-pyqt6 python-pyqt6-webengine python-cryptography qt6-wayland >/dev/null && echo "all packages exist"
sudo pacman -Syu --needed python python-pyqt6 python-pyqt6-webengine python-cryptography qt6-wayland
python -c "from PyQt6.QtWebEngineWidgets import QWebEngineView; import cryptography; print('deps ok')"
```

Use `-Syu`, never plain `-S`: if the package database is newer than the installed system, `-S` installs a PyQt6 built for a newer Qt than the one installed (a partial upgrade) and the import check fails with `version 'Qt_6.x' not found`. `-Syu` upgrades the whole system, so tell the user before running it.

With route A, the command to run PRISM is `python prism.py`. If any package doesn't exist or the import check fails, use route B.

### Route B: virtual environment with pip (same packages as on Windows)

```bash
sudo pacman -S --needed python xcb-util-cursor
python -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -c "from PyQt6.QtWebEngineWidgets import QWebEngineView; import cryptography; print('deps ok')"
```

`requirements.txt` pins exact versions, so this installs the same Chromium every other PRISM install runs. With route B, the command to run PRISM is `.venv/bin/python prism.py`. `.venv/` is git-ignored. It was never meant to come from the repo; this step creates it.

Below, `$PY` means `python` (route A) or `.venv/bin/python` (route B).

## 3. Download the block lists

```bash
$PY update_blocklists.py
ls -la blocklists/downloaded blocklists/downloaded/security
```

This fetches about 260k ad/tracker domains and 150k malware/phishing domains (a few MB, git-ignored). If a single source fails, the others still work. Mention the failure, but it isn't fatal.

## 4. Launch test

```bash
timeout 20 $PY -u prism.py 2>&1 | grep -vE "^\[[0-9:/.]+(ERROR|WARNING)" | tail -20
```

Run Python unbuffered (`-u`, as above): `timeout` kills PRISM, and buffered output would be lost. Success is a line like `[prism] 262,591 blocked domains, 148,759 malicious domains` and no Python traceback. `[prism] update check failed: PRISM: HTTP Error 404` only means the GitHub repo doesn't have `version.py` yet, or can't be reached. A PRISM window opens briefly; `timeout` closes it. Chromium lines tagged `ERROR:` about caches or the GPU are usually harmless noise.

If it fails:

| Symptom | Fix |
|---|---|
| `Could not load the Qt platform plugin "xcb"` / `libxcb-cursor` | `sudo pacman -S xcb-util-cursor` |
| Wayland errors, broken decorations or scaling | Retry with `QT_QPA_PLATFORM=xcb` (XWayland). If that works, use it in the launcher too. |
| `No usable sandbox` / namespace errors | Check `sysctl kernel.unprivileged_userns_clone` (should be 1 or absent). Last resort: `QTWEBENGINE_DISABLE_SANDBOX=1`. Tell the user. |
| Black or blank web views | Retry with `QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu-compositing`. If that fixes it, report the GPU or driver. |
| `ImportError` for a PyQt6 module | Route A package missing or wrong version. Switch to route B. |

## 5. Desktop launcher (so the user can start PRISM from their app menu)

Create `~/.local/share/applications/prism.desktop`. Use **absolute paths**: replace `REPO` with the repo's full path, and use `REPO/.venv/bin/python` for route B or `/usr/bin/python` for route A. If step 4 needed environment variables (such as `QT_QPA_PLATFORM=xcb`), put them after `env` in `Exec`.

```ini
[Desktop Entry]
Type=Application
Name=PRISM
Comment=Privacy-first research browser by Synterra
Exec=env PYTHON_PLACEHOLDER REPO/prism.py
Path=REPO
Icon=REPO/assets/icon.png
Terminal=false
Categories=Network;WebBrowser;
StartupWMClass=PRISM
```

`PYTHON_PLACEHOLDER` stands for the interpreter path (optionally preceded by `VAR=value` pairs). The final `Exec` line should look like `Exec=env /usr/bin/python /home/USER/Prism/prism.py`.

Then run:

```bash
update-desktop-database ~/.local/share/applications 2>/dev/null || true
```

## 6. Tell the user these Linux differences

- **Edition:** without a `deployment.json` this is the full edition. For a partner's machine, copy `deployment.example.json` to `deployment.json` (it leaves out the terminal and the vault). Ask the user which one this machine is if it isn't clear.
- **Terminal panel** runs commands with `/bin/sh`; the cmd/PowerShell choice is ignored.
- **Saved data** (settings, vault, stats, logins) lives in `~/.local/share/Synterra/PRISM`. Nothing comes over from the Windows PC. The password vault starts empty.
- **Screen tearing:** PRISM turns off vsync for smooth scrolling (see `main()` in `prism.py`). On X11 without a compositor this can tear. Fix it by launching with `PRISM_VSYNC=1`, and add that to the launcher if needed.
- **Updates:** `git pull` in the repo, then restart PRISM. Re-run `update_blocklists.py` now and then to refresh the block lists.

## 7. Final report

Tell the user, briefly:
- which route you used and the exact command to start PRISM
- whether the launch test passed (quote the `[prism] …` line)
- the launcher location, if you created one
- anything that failed, any workaround you applied (environment variables, sandbox), and any code you changed
