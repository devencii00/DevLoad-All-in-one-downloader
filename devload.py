#!/usr/bin/env python3
"""
DevLoad - video and audio downloader
Author: devenci.cd

TikTok, YouTube (videos + Shorts), Facebook (videos + Reels), Instagram (Reels + posts)
and anything else yt-dlp can read.
Downloads are queued and processed one at a time; the page shows recent-job progress.

Setup:   pip install flask yt-dlp imageio-ffmpeg     (ffmpeg engine comes with imageio-ffmpeg)
Run:     python devload.py     (or start it from dev_launcher.pyw)
Files:   sent to the browser download manager by default; app-folder mode uses ./Downloads.
Optional: put a cookies.txt (Netscape format) next to this file for logins (Instagram / Facebook).

Only download content you own or have permission to save.
"""
import atexit, json, os, queue, re, shutil, subprocess, sys, tempfile, threading, uuid, webbrowser
from pathlib import Path
from flask import Flask, jsonify, request, send_file, Response
import yt_dlp
from yt_dlp.utils import DownloadCancelled

APP_DIR = Path(__file__).resolve().parent
CONFIG = APP_DIR / "config.json"
DEFAULT_DIR = APP_DIR / "Downloads"
COOKIES = APP_DIR / "cookies.txt"
PORT = 5757
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
ASSETS = APP_DIR / "assets"
ICON_PNG = ASSETS / "devenci.png"
ICON_ICO = ASSETS / "devenci.ico"
BROWSER_DOWNLOAD_DIR = Path(tempfile.gettempdir()) / f"DevLoad-{uuid.uuid4().hex}"

app = Flask(__name__)
jobs = {}
job_order = []
job_cancel_events = {}
jobs_lock = threading.Lock()
download_queue = queue.Queue()
worker_lock = threading.Lock()
worker_started = False


def cfg():
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_cfg(**kw):
    c = cfg()
    c.update(kw)
    CONFIG.write_text(json.dumps(c, indent=2), encoding="utf-8")


def download_mode():
    return "folder" if cfg().get("download_mode") == "folder" else "browser"


def cleanup_browser_download(jid):
    try:
        shutil.rmtree(BROWSER_DOWNLOAD_DIR / jid)
    except FileNotFoundError:
        pass


def cleanup_browser_downloads():
    if BROWSER_DOWNLOAD_DIR.exists():
        try:
            shutil.rmtree(BROWSER_DOWNLOAD_DIR)
        except OSError as e:
            print(f"Could not clean temporary browser downloads: {e}")


atexit.register(cleanup_browser_downloads)


def out_dir():
    p = Path(cfg().get("save_dir") or DEFAULT_DIR)
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception:
        p = DEFAULT_DIR
        p.mkdir(parents=True, exist_ok=True)
    return p


def find_ffmpeg():
    p = shutil.which("ffmpeg")
    if p:
        return p
    for c in ("ffmpeg.exe", "ffmpeg/bin/ffmpeg.exe", "ffmpeg/ffmpeg.exe"):
        if (APP_DIR / c).exists():
            return str(APP_DIR / c)
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


out_dir()
FFMPEG = find_ffmpeg()
NEED_FFMPEG = ("ffmpeg is missing. Start the app from the launcher once to install it "
               "automatically, or run: pip install imageio-ffmpeg")

PLATFORMS = [
    ("TikTok", r"(tiktok\.com|vm\.tiktok|vt\.tiktok)"),
    ("YouTube Shorts", r"youtube\.com/shorts/"),
    ("YouTube", r"(youtube\.com|youtu\.be)"),
    ("Facebook", r"(facebook\.com|fb\.watch|fb\.com)"),
    ("Instagram", r"(instagram\.com|instagr\.am)"),
]


def detect(url):
    for name, rx in PLATFORMS:
        if re.search(rx, url, re.I):
            return name
    return "Other"


def clean(e):
    message = re.sub(r"\x1b\[[0-9;]*m", "", str(e)).replace("ERROR: ", "")
    if re.search(r"\bno video found\b", message, re.I):
        return "Video not found. Please make sure the source is public."
    return message[:300]


def base_opts():
    o = {"quiet": True, "no_warnings": True, "noplaylist": True}
    if COOKIES.exists():
        o["cookiefile"] = str(COOKIES)
    if FFMPEG:
        o["ffmpeg_location"] = FFMPEG
    return o


@app.get("/")
def index():
    return Response(PAGE, mimetype="text/html")


@app.get("/assets/devenci.png")
def web_logo():
    return send_file(ICON_PNG, mimetype="image/png", conditional=True)


@app.get("/favicon.ico")
def web_favicon():
    return send_file(ICON_ICO, mimetype="image/vnd.microsoft.icon", conditional=True)


@app.get("/api/status")
def status():
    return jsonify(ffmpeg=bool(FFMPEG), folder=str(out_dir()), download_mode=download_mode())


@app.post("/api/settings")
def update_settings():
    mode = (request.json or {}).get("download_mode")
    if mode not in ("browser", "folder"):
        return jsonify(error="Choose Browser download or App save folder."), 400
    save_cfg(download_mode=mode)
    return jsonify(download_mode=mode)


@app.post("/api/folder")
def set_folder():
    p = ((request.json or {}).get("path") or "").strip().strip('"')
    if not p:
        return jsonify(error="Enter a folder path."), 400
    try:
        Path(p).expanduser().mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return jsonify(error=f"Can't use that folder: {e}"[:200]), 400
    save_cfg(save_dir=str(Path(p).expanduser().resolve()))
    return jsonify(folder=str(out_dir()))


@app.post("/api/browse")
def browse():
    code = ("import sys,tkinter as tk;from tkinter import filedialog as f;r=tk.Tk();r.withdraw();"
            "r.attributes('-topmost',True);print(f.askdirectory(initialdir=sys.argv[1],title='Choose download folder'))")
    try:
        r = subprocess.run([sys.executable, "-c", code, str(out_dir())], capture_output=True,
                           text=True, creationflags=NOWIN, timeout=300)
        p = r.stdout.strip()
    except Exception:
        p = ""
    if p:
        save_cfg(save_dir=str(Path(p).resolve()))
    return jsonify(folder=str(out_dir()))


@app.post("/api/open")
def open_folder():
    p = out_dir()
    if sys.platform.startswith("win"):
        os.startfile(p)
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(p)])
    return jsonify(ok=True)


@app.post("/api/info")
def info():
    url = (request.json or {}).get("url", "").strip()
    if not url:
        return jsonify(error="Paste a link first."), 400
    try:
        with yt_dlp.YoutubeDL(base_opts()) as y:
            d = y.extract_info(url, download=False)
        best = {}
        for f in d.get("formats", []):
            h, w = f.get("height"), f.get("width")
            if h and f.get("vcodec") not in (None, "none"):
                p = min(h, w) if w else h
                best[p] = max(best.get(p, 0), h)
        options = [{"p": p, "h": best[p]} for p in sorted(best, reverse=True)]
        return jsonify(platform=detect(url), title=d.get("title") or "Untitled",
                       thumb=d.get("thumbnail"), uploader=d.get("uploader") or d.get("channel") or "",
                       duration=d.get("duration") or 0, options=options)
    except Exception as e:
        return jsonify(error=clean(e)), 400


def update_job(jid, **updates):
    with jobs_lock:
        job = jobs.get(jid)
        if job:
            changes = updates.copy()
            if changes.get("state") == "done" and job.get("state") == "cancelling":
                changes.update(state="cancelled", stage="Cancelled", note="", error="Cancelled by user")
            job.update(changes)
            if job.get("state") in ("done", "error", "cancelled"):
                job_cancel_events.pop(jid, None)


def run_job(jid, url, kind, height, label, bitrate, cancel_event, destination):

    def hook(h):
        if cancel_event.is_set():
            raise DownloadCancelled("Cancelled by user")
        if h["status"] == "downloading":
            tot = h.get("total_bytes") or h.get("total_bytes_estimate") or 0
            if tot:
                update_job(jid, pct=round(h["downloaded_bytes"] / tot * 100, 1))
            update_job(jid, note=f"{(h.get('speed') or 0) / 1048576:.1f} MB/s")
        elif h["status"] == "finished":
            update_job(jid, pct=100, note="", stage="Converting")

    # file name: "Title [1080p].mp4"  /  "Title [192kbps].mp3"
    tag = f" [{int(bitrate)}kbps]" if kind == "mp3" else (f" [{int(label)}p]" if label else "")
    temp_dir = BROWSER_DOWNLOAD_DIR / jid if destination == "browser" else None
    o = base_opts()
    try:
        if temp_dir:
            temp_dir.mkdir(parents=True, exist_ok=True)
        folder = str(temp_dir or out_dir()).replace("%", "%%")
        o.update(outtmpl=os.path.join(folder, f"%(title).80s{tag}.%(ext)s"),
                 progress_hooks=[hook], windowsfilenames=True)
        if kind == "mp3":
            o["format"] = "bestaudio/best"
            o["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3",
                                    "preferredquality": str(int(bitrate))}]
        else:
            cap = f"[height<={int(height)}]" if height else ""
            if FFMPEG:
                o["format"] = f"bv*{cap}[ext=mp4]+ba[ext=m4a]/bv*{cap}+ba/b{cap}/b"
                o["merge_output_format"] = "mp4"
            else:
                o["format"] = f"b{cap}[ext=mp4]/b{cap}/b"
    except Exception as e:
        if temp_dir:
            try:
                cleanup_browser_download(jid)
            except OSError as cleanup_error:
                print(f"Could not clean temporary browser download: {cleanup_error}")
        update_job(jid, state="error", error=clean(e))
        return
    try:
        with yt_dlp.YoutubeDL(o) as y:
            if cancel_event.is_set():
                raise DownloadCancelled("Cancelled by user")
            d = y.extract_info(url, download=True)
            if cancel_event.is_set():
                update_job(jid, state="cancelled", stage="Cancelled", note="", error="Cancelled by user")
                if temp_dir:
                    try:
                        cleanup_browser_download(jid)
                    except OSError as e:
                        print(f"Could not clean cancelled browser download: {e}")
                return
            path = (d.get("requested_downloads") or [{}])[0].get("filepath") or y.prepare_filename(d)
        if kind == "mp3":
            path = str(Path(path).with_suffix(".mp3"))
        update_job(jid, state="done", pct=100, file=path, name=Path(path).name)
        if temp_dir and cancel_event.is_set():
            try:
                cleanup_browser_download(jid)
                update_job(jid, file=None)
            except OSError as e:
                print(f"Could not clean cancelled browser download: {e}")
    except Exception as e:
        if cancel_event.is_set():
            update_job(jid, state="cancelled", stage="Cancelled", note="", error="Cancelled by user")
        else:
            update_job(jid, state="error", error=clean(e))
        if temp_dir:
            try:
                cleanup_browser_download(jid)
            except OSError as cleanup_error:
                print(f"Could not clean temporary browser download: {cleanup_error}")


def download_worker():
    while True:
        jid, args = download_queue.get()
        try:
            with jobs_lock:
                job = jobs.get(jid)
                if not job or job.get("state") != "queued":
                    continue
                job.update(state="running", stage="Downloading")
                cancel_event = job_cancel_events.get(jid)
            if cancel_event is None:
                update_job(jid, state="error", error="Could not track this download for cancellation.")
            else:
                url, kind, height, label, bitrate = args
                run_job(jid, url, kind, height, label, bitrate, cancel_event,
                        job.get("destination", "folder"))
        except Exception as e:
            cancel_event = job_cancel_events.get(jid)
            if cancel_event and cancel_event.is_set():
                update_job(jid, state="cancelled", stage="Cancelled", note="", error="Cancelled by user")
            else:
                update_job(jid, state="error", error=clean(e))
        finally:
            download_queue.task_done()


def ensure_download_worker():
    global worker_started
    with worker_lock:
        if not worker_started:
            threading.Thread(target=download_worker, daemon=True).start()
            worker_started = True


@app.post("/api/download")
def download():
    b = request.json or {}
    kind = b.get("kind", "mp4")
    if kind == "mp3" and not FFMPEG:
        return jsonify(error=NEED_FFMPEG), 400
    ensure_download_worker()
    jid = uuid.uuid4().hex[:8]
    url = b.get("url", "")
    thumb = b.get("thumb") or ""
    if not isinstance(thumb, str) or not re.match(r"^https?://", thumb, re.I):
        thumb = ""
    cancel_event = threading.Event()
    destination = download_mode()
    with jobs_lock:
        jobs[jid] = {"id": jid, "title": b.get("title") or url, "format": kind.upper(),
                     "thumb": thumb,
                     "destination": destination, "browser_download_requested": False,
                     "state": "queued", "pct": 0, "note": "", "stage": "Waiting in queue"}
        job_order.append(jid)
        job_cancel_events[jid] = cancel_event
    download_queue.put((jid, (url, kind, b.get("height"), b.get("label"), b.get("bitrate", 192))))
    return jsonify(id=jid)


@app.post("/api/jobs/<jid>/cancel")
def cancel_download(jid):
    with jobs_lock:
        job = jobs.get(jid)
        if not job:
            return jsonify(error="Unknown download."), 404
        if job.get("state") == "cancelling":
            return jsonify(id=jid, state="cancelling")
        if job.get("state") not in ("queued", "running"):
            return jsonify(error="This download is no longer active."), 409
        cancel_event = job_cancel_events.get(jid)
        if cancel_event is None:
            return jsonify(error="Could not track this download for cancellation."), 500
        cancel_event.set()
        if job["state"] == "queued":
            job.update(state="cancelled", stage="Cancelled", note="", error="Cancelled by user")
            job_cancel_events.pop(jid, None)
        else:
            job.update(state="cancelling", stage="Cancelling")
        return jsonify(id=jid, state=job["state"])


@app.get("/api/jobs")
def recent_jobs():
    with jobs_lock:
        recent = [jobs[jid].copy() for jid in reversed(job_order[-20:]) if jid in jobs]
    return jsonify(jobs=[{k: v for k, v in job.items() if k != "file"} for job in recent])


@app.post("/api/jobs/clear-recent")
def clear_recent_jobs():
    terminal_states = ("done", "error", "cancelled")
    with jobs_lock:
        cleared = [jid for jid in job_order
                   if jid in jobs and jobs[jid].get("state") in terminal_states]
        for jid in cleared:
            jobs.pop(jid, None)
            job_cancel_events.pop(jid, None)
        if cleared:
            job_order[:] = [jid for jid in job_order if jid in jobs]
    return jsonify(cleared=len(cleared))


@app.get("/api/progress/<jid>")
def progress(jid):
    with jobs_lock:
        job = jobs.get(jid)
        snapshot = job.copy() if job else None
    return jsonify({k: v for k, v in snapshot.items() if k != "file"}) if snapshot else (jsonify(error="Unknown job"), 404)


@app.get("/api/file/<jid>")
def get_file(jid):
    with jobs_lock:
        job = jobs.get(jid)
        path = job.get("file") if job and job.get("state") == "done" else None
    if not path:
        return "Not ready", 404
    return send_file(path, as_attachment=True)


@app.post("/api/jobs/<jid>/browser-download-requested")
def browser_download_requested(jid):
    with jobs_lock:
        job = jobs.get(jid)
        if not job:
            return jsonify(error="Unknown download."), 404
        if job.get("destination") != "browser" or job.get("state") != "done":
            return jsonify(error="This download is not ready for the browser."), 409
        job["browser_download_requested"] = True
    return jsonify(ok=True)

PAGE = (APP_DIR / "ui.html").read_text(encoding="utf-8")

if __name__ == "__main__":
    print(f"\n  DevLoad  |  by devenci.cd\n  Open http://127.0.0.1:{PORT}")
    print(f"  Saving to: {out_dir()}")
    print("  ffmpeg: " + (FFMPEG if FFMPEG else "NOT FOUND (MP3 / HD merge disabled)"))
    if not os.environ.get("DEVLOAD_NO_BROWSER"):
        threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{PORT}")).start()
    app.run(host="127.0.0.1", port=PORT, debug=False)