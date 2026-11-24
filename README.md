# DevLoad

DevLoad is a local video and audio downloader with a Windows launcher, a browser-based interface, and a sequential download queue.

## Features

- Fetch video details and choose MP4 resolution or MP3 quality.
- Add several downloads to the queue; DevLoad processes them one at a time.
- Check queued, active, completed, and failed jobs in the sidebar, including progress and speed.
- Change the download folder from the **Save folder** sidebar tab.
- Keep the launcher in the Windows system tray while DevLoad runs.
- Restart the launcher and its local server from either the launcher window or tray menu.
- Use yt-dlp-supported sources, including Twitch clips, TikTok, YouTube, Facebook, and Instagram.

## Quick start on Windows

1. Install Python with Tkinter available.
2. Keep `dev_launcher.pyw` next to `devload.py`.
3. Double-click `dev_launcher.pyw`.

The launcher installs missing Python packages on first run, starts the local server, and opens the browser. Closing the launcher window hides it in the system tray; use the tray menu to reopen, restart, or exit. The launcher window also has a **Restart launcher** control.

Open the web interface at [http://127.0.0.1:5757](http://127.0.0.1:5757).

## Run from a terminal

Install the server dependencies and start DevLoad:

```powershell
python -m pip install flask yt-dlp imageio-ffmpeg
python devload.py
```

Then open [http://127.0.0.1:5757](http://127.0.0.1:5757). The launcher additionally uses `pystray` and Pillow for its system-tray icon.

## Downloading

1. Paste a media URL and select **Fetch**.
2. Choose a format and quality.
3. Select **Add to queue**. You can fetch and queue another item while earlier downloads are running.
4. Follow progress and results in the sidebar's **Queue** tab. **Clear history** removes completed, failed, and cancelled entries without deleting downloaded files or interrupting active downloads. Completed items can also be saved from the browser.

New installs default to **Browser download**. In the sidebar's **Save folder** tab, choose either **Browser download** or **App save folder**. Browser mode sends completed files to the browser's native download manager, where download progress and save-location settings are handled. Enable **Ask where to save each file** in browser settings to choose a destination. Use **Save a copy via browser** in Recent downloads to retry or save another copy. **App save folder** mode saves directly to the selected folder, which defaults to `Downloads/` next to the app.

## Runtime files

DevLoad creates or uses these local files and folders:

- `Downloads/` — default destination when **App save folder** mode is selected.
- `config.json` — saved download destination, folder, and launcher preferences.
- Browser-mode files are staged in a temporary system folder and removed when DevLoad exits.
- `assets/` — launcher icons; a default icon is generated if one is not supplied.
- `cookies.txt` — optional yt-dlp cookies file for sites where you are authorized to use it.

The `Downloads/`, `config.json`, `cookies.txt`, and incidental generated assets are excluded by `.gitignore`. The supplied `assets/devenci.png` is used in the launcher and browser UI; `assets/devenci.ico` is used as the browser favicon. The launcher scales the UI logo to 48×48.

## Privacy and usage

The web server binds to `127.0.0.1` and is intended for local use. Download only content you own or have permission to save, and follow the source site's terms.

© 2026 devenci.cd. All rights reserved.
