"""
DevLoad Launcher - desktop launcher
Author: devenci.cd

Double-click this file (.pyw = no console window) or run:  python dev_launcher.pyw
It installs missing app/tray components (Flask, yt-dlp, ffmpeg, pystray, Pillow),
starts/stops the downloader and gives you a clickable link to open it. Once started,
it hides to the system tray; use the tray menu to reopen the launcher or exit.
Keep it next to devload.py.
"""
import base64, ctypes, importlib, importlib.util, io, json, math, os, queue, random, re, shutil, socket, struct
import subprocess, sys, threading, time, webbrowser, zlib
import tkinter as tk
from tkinter import filedialog
from pathlib import Path

APP = Path(__file__).resolve().parent
SCRIPT = APP / "devload.py"
CONFIG = APP / "config.json"
ASSETS = APP / "assets"
DEFAULT_DIR = APP / "Downloads"
URL = "http://127.0.0.1:5757"
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
W, H = 480, 680
UI_ICON_SIZE = 48
URLRE = re.compile(r"https?://[^\s]+")

THEMES = {
    "light": dict(bg="#f4f2ff", card="#ffffff", field="#f1efff", line="#d9d4f5", text="#1d1b3a", sub="#6a6f92",
                  a="#7d5cff", a2="#6544f0", b="#0a8fc0", ok="#14a67a", err="#e0364a", warn="#d98a00",
                  btn="#ebe8ff", btnh="#ddd8ff", c1="#c4b7ff", c2="#9fdcf0"),
    "dark":  dict(bg="#14112a", card="#1f1c3b", field="#0e0c20", line="#3b3766", text="#e8eafa", sub="#9399bb",
                  a="#7d5cff", a2="#9479ff", b="#00cdff", ok="#2fd39a", err="#ff5a6a", warn="#ffb020",
                  btn="#2a2650", btnh="#38336a", c1="#5b45c4", c2="#0a8fb0"),
}


# ---------- config ----------
def cfg():
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_cfg(**kw):
    c = cfg()
    c.update(kw)
    CONFIG.write_text(json.dumps(c, indent=2), encoding="utf-8")


def save_dir():
    p = Path(cfg().get("save_dir") or DEFAULT_DIR)
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception:
        p = DEFAULT_DIR
        p.mkdir(parents=True, exist_ok=True)
    return p


# ---------- app icon (generated, saved to ./assets as devenci.png / devenci.ico) ----------
def make_png(size=128):
    ss, r = 2, 0.22
    ga, gb = (125, 92, 255), (0, 205, 255)

    def in_round(x, y):
        cx, cy = min(max(x, r), 1 - r), min(max(y, r), 1 - r)
        return (x - cx) ** 2 + (y - cy) ** 2 <= r * r

    def arrow(x, y):
        if 0.43 <= x <= 0.57 and 0.20 <= y <= 0.52:
            return True
        if 0.50 <= y <= 0.72 and abs(x - 0.5) <= (0.72 - y):
            return True
        return 0.26 <= x <= 0.74 and 0.78 <= y <= 0.84

    raw = bytearray()
    for py in range(size):
        raw.append(0)
        for px in range(size):
            cov = arr = 0
            for sy in range(ss):
                for sx in range(ss):
                    x, y = (px + (sx + .5) / ss) / size, (py + (sy + .5) / ss) / size
                    if in_round(x, y):
                        cov += 1
                        if arrow(x, y):
                            arr += 1
            if not cov:
                raw += b"\x00\x00\x00\x00"
                continue
            tt = (px + py) / (2 * size)
            af = arr / cov
            rgb = [int((ga[i] + (gb[i] - ga[i]) * tt) * (1 - af) + 255 * af) for i in range(3)]
            raw += bytes(rgb) + bytes([int(255 * cov / (ss * ss))])

    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xffffffff)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))


def ensure_icon():
    png_path, ico_path = ASSETS / "devenci.png", ASSETS / "devenci.ico"
    try:
        ASSETS.mkdir(exist_ok=True)
        if png_path.exists():
            return png_path.read_bytes()
        png = make_png(128)
        png_path.write_bytes(png)
        ico_path.write_bytes(struct.pack("<HHH", 0, 1, 1) + struct.pack("<BBBBHHII", 128, 128, 0, 0, 1, 32, len(png), 22) + png)
        return png
    except Exception:
        return make_png(128)


# ---------- helpers ----------
def python_exe():
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe" and (exe.parent / "python.exe").exists():
        return str(exe.parent / "python.exe")
    return str(exe)


def have_ffmpeg():
    if shutil.which("ffmpeg"):
        return True
    if any((APP / p).exists() for p in ("ffmpeg.exe", "ffmpeg/bin/ffmpeg.exe", "ffmpeg/ffmpeg.exe")):
        return True
    return importlib.util.find_spec("imageio_ffmpeg") is not None


class Launcher(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("DevLoad Launcher")
        self.geometry(f"{W}x{H}")
        self.resizable(False, False)
        self.icon = tk.PhotoImage(data=base64.b64encode(ensure_icon()))
        self.iconphoto(True, self.icon)
        self.logo = tk.PhotoImage(data=base64.b64encode(make_png(UI_ICON_SIZE)))
        self.theme = cfg().get("theme", "light")
        self.auto = True
        self.proc = None
        self.tray = None
        self.busy = False
        self.stopping = False
        self.n = 0
        self.last = None
        self.q = queue.Queue()
        self.cubes = [[random.uniform(0, W), random.uniform(0, H), random.uniform(10, 26),
                       random.uniform(0, 6.28), random.uniform(10, 26), random.uniform(-.6, .6)] for _ in range(16)]
        self.canvas = tk.Canvas(self, width=W, height=H, highlightthickness=0, bd=0)
        self.canvas.place(x=0, y=0)
        self.log = tk.Text(self, font=("Consolas", 9), bd=0, highlightthickness=0, wrap="word",
                           state="disabled", padx=4, pady=4, cursor="arrow")
        self.log.tag_configure("link", underline=True)
        self.log.tag_bind("link", "<Enter>", lambda e: self.log.config(cursor="hand2"))
        self.log.tag_bind("link", "<Leave>", lambda e: self.log.config(cursor="arrow"))
        self.protocol("WM_DELETE_WINDOW", self.hide_to_tray)
        self.render()
        self.write("Welcome. DevLoad will be available at " + URL)
        self.animate()
        self.poll()
        self.after(400, self.start)

    @property
    def t(self):
        return THEMES[self.theme]

    # ---------- drawing ----------
    def rr(self, x1, y1, x2, y2, r, fill, outline="", tags="ui"):
        pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2,
               x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
        return self.canvas.create_polygon(pts, smooth=True, fill=fill, outline=outline, tags=tags)

    def button(self, key, x, y, w, h, text, cmd, kind="soft", size=10):
        t, c = self.t, self.canvas
        fill, hov, fg = {"primary": (t["a"], t["a2"], "#ffffff"), "danger": (t["err"], "#c42a3c", "#ffffff")}.get(
            kind, (t["btn"], t["btnh"], t["text"]))
        tag = "b_" + key
        shape = self.rr(x, y, x + w, y + h, 12, fill, tags=("ui", tag))
        c.create_text(x + w / 2, y + h / 2, text=text, fill=fg, font=("Segoe UI", size, "bold"), tags=("ui", tag))
        c.tag_bind(tag, "<Enter>", lambda e: (c.itemconfig(shape, fill=hov), c.config(cursor="hand2")))
        c.tag_bind(tag, "<Leave>", lambda e: (c.itemconfig(shape, fill=fill), c.config(cursor="")))
        c.tag_bind(tag, "<Button-1>", lambda e: cmd())

    def render(self):
        t, c = self.t, self.canvas
        c.delete("ui")
        c.configure(bg=t["bg"])
        run = self.proc is not None and self.proc.poll() is None
        folder = str(save_dir())
        shown = folder if len(folder) <= 40 else "..." + folder[-37:]

        c.create_image(28, 22, image=self.logo, anchor="nw", tags="ui")
        c.create_text(88, 24, text="DevLoad", anchor="nw", fill=t["text"], font=("Segoe UI", 17, "bold"), tags="ui")
        c.create_text(88, 54, text="All-in-one downloader", anchor="nw", fill=t["b"], font=("Segoe UI", 10, "bold"), tags="ui")
        self.button("theme", W - 28 - 84, 28, 84, 34, "Dark" if self.theme == "light" else "Light", self.toggle_theme)

        # status card
        self.rr(24, 88, W - 24, 196, 18, t["card"], t["line"])
        col, label = (t["warn"], "Setting up...") if self.busy else (t["ok"], "Server running") if run else (t["err"], "Server stopped")
        c.create_oval(44, 108, 58, 122, fill=col, outline="", tags="ui")
        c.create_text(70, 105, text=label, anchor="nw", fill=t["text"], font=("Segoe UI", 12, "bold"), tags="ui")
        c.create_text(70, 130, text=URL, anchor="nw", fill=t["b"], font=("Segoe UI", 10, "underline"), tags=("ui", "ulink"))
        c.tag_bind("ulink", "<Button-1>", lambda e: webbrowser.open(URL))
        c.tag_bind("ulink", "<Enter>", lambda e: c.config(cursor="hand2"))
        c.tag_bind("ulink", "<Leave>", lambda e: c.config(cursor=""))
        ff = have_ffmpeg()
        c.create_text(44, 160, text="ffmpeg ready (HD + MP3)" if ff else "ffmpeg will be installed on start",
                      anchor="nw", fill=t["ok"] if ff else t["warn"], font=("Segoe UI", 9), tags="ui")

        # actions
        if self.busy:
            self.button("main", 24, 212, W - 48, 52, "Setting up...", lambda: None, "primary", 12)
        elif run:
            self.button("main", 24, 212, W - 48, 52, "Stop server", self.stop, "danger", 12)
        else:
            self.button("main", 24, 212, W - 48, 52, "Start server", self.start, "primary", 12)
        self.button("open", 24, 276, 212, 40, "Open in browser", lambda: webbrowser.open(URL))
        self.button("folder", 244, 276, 212, 40, "Open save folder", self.open_folder)

        # folder card
        self.rr(24, 330, W - 24, 400, 16, t["card"], t["line"])
        c.create_text(44, 342, text="Save folder", anchor="nw", fill=t["sub"], font=("Segoe UI", 9), tags="ui")
        c.create_text(44, 362, text=shown, anchor="nw", fill=t["text"], font=("Segoe UI", 10), tags="ui")
        self.button("change", W - 24 - 20 - 84, 347, 84, 34, "Change", self.change_folder)

        # activity
        c.create_text(28, 416, text="Activity", anchor="nw", fill=t["text"], font=("Segoe UI", 11, "bold"), tags="ui")
        self.button("auto", 120, 410, 104, 28, "Auto-open: " + ("On" if self.auto else "Off"), self.toggle_auto, size=9)
        self.button("upd", 232, 410, 100, 28, "Update yt-dlp", self.update_ytdlp, size=9)
        self.button("restart", 340, 410, 116, 28, "Restart launcher", self.restart, size=9)
        self.rr(24, 446, W - 24, H - 24, 14, t["field"], t["line"])
        c.create_window(34, 454, window=self.log, anchor="nw", width=W - 68, height=H - 24 - 446 - 16, tags="ui")
        self.log.configure(bg=t["field"], fg=t["sub"], insertbackground=t["text"])
        self.log.tag_configure("link", foreground=t["b"])
        c.tag_lower("cube")
        self.last = self.state_key()

    def state_key(self):
        run = self.proc is not None and self.proc.poll() is None
        return (run, self.busy, self.theme, self.auto, str(save_dir()), have_ffmpeg())

    def refresh_logo(self):
        try:
            image_module = importlib.import_module("PIL.Image")
            image_tk = importlib.import_module("PIL.ImageTk")
        except ImportError:
            return
        resampling = getattr(image_module, "Resampling", image_module)
        image = image_module.open(io.BytesIO(ensure_icon())).convert("RGBA")
        image = image.resize((UI_ICON_SIZE, UI_ICON_SIZE), resampling.LANCZOS)
        self.logo = image_tk.PhotoImage(image)
        self.render()

    def animate(self):
        t, c = self.t, self.canvas
        c.delete("cube")
        for cb in self.cubes:
            cb[1] -= cb[4] * 0.03
            cb[3] += cb[5] * 0.03
            if cb[1] < -30:
                cb[1], cb[0] = H + 30, random.uniform(0, W)
            pts = []
            for k in range(4):
                a = cb[3] + k * math.pi / 2 + math.pi / 4
                pts += [cb[0] + math.cos(a) * cb[2], cb[1] + math.sin(a) * cb[2]]
            c.create_polygon(pts, outline=t["c1"] if cb[2] > 18 else t["c2"], fill="", width=1.2, tags="cube")
        c.tag_lower("cube")
        self.after(33, self.animate)

    # ---------- log ----------
    def write(self, text):
        lg = self.log
        lg.configure(state="normal")
        pos = 0
        for m in URLRE.finditer(text):
            lg.insert("end", text[pos:m.start()])
            tag = f"u{self.n}"
            self.n += 1
            lg.insert("end", m.group(0), ("link", tag))
            lg.tag_bind(tag, "<Button-1>", lambda e, u=m.group(0): webbrowser.open(u))
            pos = m.end()
        lg.insert("end", text[pos:].rstrip("\r\n") + "\n")
        lg.see("end")
        lg.configure(state="disabled")

    def poll(self):
        try:
            while True:
                item = self.q.get_nowait()
                item() if callable(item) else self.write(item)
        except queue.Empty:
            pass
        if self.state_key() != self.last:
            self.render()
        self.after(250, self.poll)

    # ---------- actions ----------
    def run_cmd(self, args, done=None):
        def work():
            p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                 cwd=str(APP), creationflags=NOWIN)
            for line in p.stdout:
                self.q.put(line)
            p.wait()
            if done:
                self.q.put(done)
        threading.Thread(target=work, daemon=True).start()

    def missing(self):
        m = []
        if importlib.util.find_spec("flask") is None:
            m.append("flask")
        if importlib.util.find_spec("yt_dlp") is None:
            m.append("yt-dlp")
        if importlib.util.find_spec("pystray") is None:
            m.append("pystray")
        if importlib.util.find_spec("PIL") is None:
            m.append("pillow")
        if not have_ffmpeg():
            m.append("imageio-ffmpeg")
        return m

    def start(self):
        if self.busy or (self.proc and self.proc.poll() is None):
            return
        if not SCRIPT.exists():
            self.write(f"{SCRIPT.name} not found next to the launcher.")
            return
        miss = self.missing()
        if miss:
            self.busy = True
            self.write("First run setup. Installing: " + ", ".join(miss))
            self.run_cmd([python_exe(), "-m", "pip", "install", "-q", "--disable-pip-version-check", "--upgrade", *miss],
                         done=self.after_setup)
        else:
            self.launch()

    def after_setup(self):
        self.busy = False
        importlib.invalidate_caches()
        missing = self.missing()
        if any(m in missing for m in ("flask", "yt-dlp", "pystray", "pillow")):
            self.write("Setup failed. Check your internet connection and try again.")
            return
        self.write("Setup complete.")
        self.launch()

    def start_tray(self):
        if self.tray is not None:
            return True
        try:
            pystray = importlib.import_module("pystray")
            Image = importlib.import_module("PIL.Image")

            menu = pystray.Menu(
                pystray.MenuItem("Show launcher", self.show_from_tray, default=True),
                pystray.MenuItem("Restart launcher", self.restart_from_tray),
                pystray.MenuItem("Exit", self.exit_from_tray),
            )
            image = Image.open(io.BytesIO(ensure_icon())).copy()
            self.tray = pystray.Icon("devload", image, "DevLoad", menu)
            self.tray.run_detached()
            return True
        except (ImportError, OSError, RuntimeError) as exc:
            self.tray = None
            self.write(f"Could not create the system tray icon: {exc}")
            return False

    def show_from_tray(self, *_):
        self.q.put(self.show_window)

    def exit_from_tray(self, *_):
        self.q.put(self.quit_app)

    def restart_from_tray(self, *_):
        self.q.put(self.restart)

    def show_window(self):
        self.deiconify()
        self.state("normal")
        self.lift()

    def hide_to_tray(self):
        self.withdraw()

    def launch(self):
        self.refresh_logo()
        if not self.start_tray():
            return
        self.stopping = False
        self.proc = subprocess.Popen([python_exe(), "-u", str(SCRIPT)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     text=True, cwd=str(APP), creationflags=NOWIN,
                                     env={**os.environ, "DEVLOAD_NO_BROWSER": "1"})
        proc = self.proc

        def reader():
            for line in proc.stdout:
                self.q.put(line)
            if not self.stopping:
                self.q.put("Server exited. See the messages above for the reason.")

        def wait_ready():
            for _ in range(60):
                try:
                    socket.create_connection(("127.0.0.1", 5757), 0.3).close()
                    break
                except OSError:
                    if proc.poll() is not None:
                        return
                    time.sleep(0.25)
            else:
                self.q.put("The server is not responding yet. Click the link above to try opening it.")
                return
            self.q.put(f"Ready. Click to open: {URL}")
            self.q.put(self.hide_to_tray)
            if self.auto:
                webbrowser.open(URL)

        threading.Thread(target=reader, daemon=True).start()
        threading.Thread(target=wait_ready, daemon=True).start()
        self.write(f"Starting server... open it any time at {URL}")

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.stopping = True
            self.proc.terminate()
            self.write("Server stopped.")

    def restart(self):
        if self.busy:
            self.show_window()
            self.write("Please wait for setup to finish before restarting.")
            return
        proc = self.proc
        if proc and proc.poll() is None:
            self.stop()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        try:
            subprocess.Popen([sys.executable, str(Path(__file__).resolve())],
                             cwd=str(APP), creationflags=NOWIN)
        except OSError as exc:
            self.write(f"Could not restart the launcher: {exc}")
            return
        if self.tray:
            self.tray.stop()
            self.tray = None
        self.destroy()

    def toggle_theme(self):
        self.theme = "dark" if self.theme == "light" else "light"
        save_cfg(theme=self.theme)
        self.render()

    def toggle_auto(self):
        self.auto = not self.auto
        self.render()

    def change_folder(self):
        p = filedialog.askdirectory(initialdir=str(save_dir()), title="Choose download folder")
        if p:
            save_cfg(save_dir=str(Path(p).resolve()))
            self.write(f"Save folder changed to {Path(p).resolve()}")
            self.render()

    def open_folder(self):
        p = save_dir()
        if sys.platform.startswith("win"):
            os.startfile(p)
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(p)])

    def update_ytdlp(self):
        self.write("Updating yt-dlp...")
        self.run_cmd([python_exe(), "-m", "pip", "install", "-q", "--disable-pip-version-check", "-U", "yt-dlp"],
                     done=lambda: self.write("Update finished. Stop and start the server to apply it."))

    def quit_app(self):
        self.stop()
        if self.tray:
            self.tray.stop()
            self.tray = None
        self.destroy()


if __name__ == "__main__":
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("devload.launcher")
    except Exception:
        pass
    Launcher().mainloop()