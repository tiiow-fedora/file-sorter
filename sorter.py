"""File Sorter: click through a folder one item at a time and delete (to the
Recycle Bin), move/organize, rename or skip each one, with a preview.

Runs a tiny web server on 127.0.0.1 only and opens the UI in the browser.
Every request needs the random per-run token that is put in the opened URL.
"""
import ctypes
import csv
import json
import mimetypes
import os
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
import zipfile
from ctypes import wintypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG = HERE / "config.json"
LOG = HERE / "actions.csv"
HOME = Path(os.environ["USERPROFILE"])
TOKEN = secrets.token_urlsafe(24)
PORT = 8765
START = None
RANGE_CHUNK = 4 * 1024 * 1024

# ---------------------------------------------------------------- file kinds

KINDS = {
    "image": ".png .jpg .jpeg .jfif .gif .webp .bmp .svg .ico .avif",
    "video": ".mp4 .webm .mov .m4v .ogv",
    "video_np": ".mkv .avi .wmv .flv .ts .mts .3gp",
    "audio": ".mp3 .wav .ogg .flac .m4a .aac .opus",
    "pdf": ".pdf",
    "text": ".txt .md .log .json .csv .tsv .xml .yml .yaml .ini .cfg .conf .toml .py .js .ts .html .htm "
            ".css .bat .cmd .ps1 .sh .lua .luau .java .c .cpp .h .cs .rs .go .snbt .properties .reg .srt "
            ".gitignore .env.example .nfo .rbxlx",
    "disk": ".iso .img .vhd .vhdx",
    "archive": ".zip .rar .7z .tar .gz .xz .bz2 .tgz .unitypackage",
    "installer": ".exe .msi .msix .appx .appxbundle .msixbundle",
    "document": ".doc .docx .xls .xlsx .ppt .pptx .odt .ods .rtf .epub",
    "mod": ".jar .mrpack .mcpack .mcworld .mcaddon .vpk .rbxm .rbxl",
    "model": ".blend .fbx .obj .stl .3mf .gltf .glb .dae",
    "font": ".ttf .otf .woff .woff2",
    "link": ".lnk .url",
}
EXT_KIND = {e: k for k, exts in KINDS.items() for e in exts.split()}
PREVIEW = {"image": "image", "video": "video", "audio": "audio", "pdf": "pdf", "text": "text"}
MIME = {".mp4": "video/mp4", ".m4v": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime",
        ".ogv": "video/ogg", ".mp3": "audio/mpeg", ".wav": "audio/wav", ".ogg": "audio/ogg",
        ".flac": "audio/flac", ".m4a": "audio/mp4", ".aac": "audio/aac", ".opus": "audio/ogg",
        ".pdf": "application/pdf", ".svg": "image/svg+xml", ".webp": "image/webp", ".avif": "image/avif",
        ".jfif": "image/jpeg", ".ico": "image/x-icon"}
# Never handed to the browser as anything it could execute in our origin.
AS_PLAIN_TEXT = {".html", ".htm", ".xhtml", ".xml", ".js", ".mjs"}
# "Open file" refuses these: opening them would run them.
NO_LAUNCH = {".exe", ".msi", ".msix", ".appx", ".appxbundle", ".msixbundle", ".bat", ".cmd", ".ps1",
             ".vbs", ".vbe", ".js", ".jse", ".wsf", ".wsh", ".scr", ".com", ".pif", ".lnk", ".url",
             ".reg", ".jar", ".hta", ".cpl", ".msc", ".py", ".pyw"}


def kind_of(name):
    return EXT_KIND.get(os.path.splitext(name)[1].lower(), "other")


# ---------------------------------------------------------------- path safety

def norm(p):
    return os.path.normcase(os.path.abspath(p))


def inside(path, base):
    p, b = norm(path), norm(base).rstrip("\\")
    return p == b or p.startswith(b + "\\")


PROTECTED = [norm(x) for x in (os.environ.get("SystemRoot", r"C:\Windows"), os.environ.get("ProgramFiles"),
                               os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramData")) if x]
NEVER_ROOT = {norm(HOME), norm(HOME / "AppData"), norm(HOME / "AppData" / "Local"),
              norm(HOME / "AppData" / "Roaming"), norm(HOME / "AppData" / "LocalLow")}
DEFAULT_ROOTS = [str(HOME / n) for n in ("Downloads", "Documents", "Desktop", "Pictures", "Videos", "Music")
                 if (HOME / n).is_dir()]
roots = [norm(r) for r in DEFAULT_ROOTS]


def protected(p):
    return any(inside(p, x) for x in PROTECTED)


def check_read(p):
    if not p or not any(inside(p, r) for r in roots):
        raise PermissionError("That path is outside the folders opened in File Sorter.")
    return os.path.abspath(p)


def check_modify(p):
    p = check_read(p)
    if norm(p) in roots or protected(p):
        raise PermissionError("Refusing to change that path.")
    if not os.path.lexists(p):
        raise FileNotFoundError("It's already gone.")
    return p


def add_root(p):
    p = os.path.abspath(os.path.expandvars(p.strip().strip('"')))
    if not os.path.isdir(p):
        raise ValueError("Not a folder: " + p)
    n = norm(p)
    if n in NEVER_ROOT or protected(p) or os.path.dirname(n) == n:
        raise PermissionError("Pick a more specific folder than that.")
    if n not in roots:
        roots.append(n)
    if not any(norm(r) == n for r in DEFAULT_ROOTS):
        DEFAULT_ROOTS.append(p)
    return p


# ---------------------------------------------------------------- recycle bin

class SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", ctypes.c_void_p),
                ("pTo", ctypes.c_void_p), ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]


FO_DELETE = 3
# ALLOWUNDO = Recycle Bin; WANTNUKEWARNING = ask before permanently deleting
# something too big for the bin, instead of silently destroying it.
FOF_FLAGS = 0x0040 | 0x0010 | 0x0004 | 0x4000


def recycle(p):
    buf = ctypes.create_unicode_buffer(p + "\0")  # pFrom must be double-null terminated
    op = SHFILEOPSTRUCTW(wFunc=FO_DELETE, pFrom=ctypes.addressof(buf), fFlags=FOF_FLAGS)
    rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if rc != 0:
        raise OSError(f"Windows refused to recycle it (code {rc:#x}). Is it open in another program?")
    if op.fAnyOperationsAborted or os.path.lexists(p):
        raise OSError("Delete was cancelled.")


# ---------------------------------------------------------------- folder sizes

_size_cache = {}


def dir_size(p):
    key = norm(p)
    if key in _size_cache:
        return _size_cache[key]
    total, count, stack = 0, 0, [p]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            if not e.is_junction():
                                stack.append(e.path)
                        else:
                            total += e.stat(follow_symlinks=False).st_size
                            count += 1
                    except OSError:
                        pass
        except OSError:
            pass
    _size_cache[key] = (total, count)
    return total, count


def forget_sizes(*paths):
    for p in paths:
        for key in list(_size_cache):
            if inside(p, key) or inside(key, p):
                _size_cache.pop(key, None)


# ---------------------------------------------------------------- config / log

def load_config():
    try:
        return json.loads(CONFIG.read_text("utf-8-sig"))
    except (OSError, ValueError):
        return {"dests": [r"D:\_cleanup_holding"]}


def save_config(cfg):
    CONFIG.write_text(json.dumps(cfg, indent=2), "utf-8")


def log(action, path, dest="", size=""):
    new = not LOG.exists()
    with LOG.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["time", "action", "path", "dest", "bytes"])
        w.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), action, path, dest, size])


undo_stack = []
lock = threading.Lock()


_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateFileW.restype = wintypes.HANDLE
_kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                  wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]


def open_shared(p):
    """Open for reading with FILE_SHARE_DELETE, so a preview being streamed
    never stops the file from being moved, renamed or recycled."""
    import msvcrt
    h = _kernel32.CreateFileW(p, 0x80000000, 0x1 | 0x2 | 0x4, None, 3, 0x80, None)  # GENERIC_READ, share R|W|D, OPEN_EXISTING
    if h == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    return os.fdopen(msvcrt.open_osfhandle(h, os.O_RDONLY | os.O_BINARY), "rb")


def retry_locked(fn, *args):
    """Run fn, retrying for a few seconds while Windows says the file is in use
    (e.g. a preview stream that hasn't finished closing yet)."""
    for _ in range(15):
        try:
            return fn(*args)
        except OSError as e:
            if getattr(e, "winerror", None) not in (32, 33) and "code 0x20" not in str(e):
                raise
            time.sleep(0.3)
    try:
        return fn(*args)
    except OSError as e:
        if getattr(e, "winerror", None) in (32, 33) or "code 0x20" in str(e):
            raise OSError("It's open in another program. Close it there and try again.") from e
        raise


# ---------------------------------------------------------------- operations

def list_dir(d):
    d = check_read(d)
    out = []
    with os.scandir(d) as it:
        for e in it:
            try:
                st = e.stat(follow_symlinks=False)
                isdir = e.is_dir(follow_symlinks=False)
                out.append({"name": e.name, "path": e.path, "dir": isdir,
                            "size": None if isdir else st.st_size, "mtime": st.st_mtime,
                            "kind": "folder" if isdir else kind_of(e.name)})
            except OSError:
                pass
    return {"path": d, "items": out}


def read_text(p, limit=100_000):
    with open_shared(p) as f:
        raw = f.read(limit)
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16", "replace")
    if b"\0" in raw[:8000]:
        return None
    return raw.decode("utf-8-sig", "replace")


def info(p):
    p = check_read(p)
    st = os.stat(p)
    res = {"path": p, "mtime": st.st_mtime}
    if os.path.isdir(p):
        size, count = dir_size(p)
        children = []
        try:
            with os.scandir(p) as it:
                for e in it:
                    try:
                        isdir = e.is_dir(follow_symlinks=False)
                        children.append({"name": e.name, "path": e.path, "dir": isdir,
                                         "size": None if isdir else e.stat(follow_symlinks=False).st_size,
                                         "kind": "folder" if isdir else kind_of(e.name)})
                    except OSError:
                        pass
        except OSError:
            pass
        children.sort(key=lambda c: (not c["dir"], c["name"].lower()))
        res.update(preview="folder", size=size, files=count, children=children[:300],
                   more=max(0, len(children) - 300))
        return res
    kind = kind_of(p)
    res.update(size=st.st_size, preview=PREVIEW.get(kind, "none"))
    ext = os.path.splitext(p)[1].lower()
    if kind == "text" or (kind == "other" and st.st_size < 2_000_000):
        txt = read_text(p)
        if txt is not None:
            res.update(preview="text", text=txt, truncated=st.st_size > 100_000)
        elif kind == "text":
            res["preview"] = "none"
    elif kind in ("archive", "mod", "document") and ext not in (".docx", ".xlsx", ".pptx"):
        try:
            if zipfile.is_zipfile(p):
                with zipfile.ZipFile(p) as z:
                    names = z.infolist()
                    res.update(preview="zip", entries=[{"name": i.filename, "size": i.file_size} for i in names[:300]],
                               more=max(0, len(names) - 300), unpacked=sum(i.file_size for i in names))
        except (OSError, zipfile.BadZipFile):
            pass
    return res


def unique_target(dest_dir, name):
    target = os.path.join(dest_dir, name)
    if not os.path.lexists(target):
        return target
    stem, ext = os.path.splitext(name)
    if os.path.isdir(os.path.join(dest_dir, name)):
        stem, ext = name, ""
    i = 2
    while os.path.lexists(os.path.join(dest_dir, f"{stem} ({i}){ext}")):
        i += 1
    return os.path.join(dest_dir, f"{stem} ({i}){ext}")


def move(src, dest, cwd):
    src = check_modify(src)
    dest = os.path.expandvars(dest.strip().strip('"'))
    if not dest:
        raise ValueError("Type where to move it.")
    if not os.path.isabs(dest):
        dest = os.path.join(check_read(cwd), dest)
    dest = os.path.abspath(dest)
    if protected(dest):
        raise PermissionError("Won't move things into Windows or Program Files.")
    if inside(dest, src):
        raise ValueError("Can't move a folder into itself.")
    created = not os.path.isdir(dest)
    os.makedirs(dest, exist_ok=True)
    target = unique_target(dest, os.path.basename(src))
    size = dir_size(src)[0] if os.path.isdir(src) else os.path.getsize(src)
    retry_locked(shutil.move, src, target)
    forget_sizes(src, dest)
    undo_stack.append({"type": "move", "from": src, "to": target, "createdDir": dest if created else None})
    log("move", src, target, size)
    return {"to": target, "destDir": dest, "created": created,
            "offDrive": os.path.splitdrive(norm(src))[0] != os.path.splitdrive(norm(target))[0]}


def rename(src, new_name):
    src = check_modify(src)
    new_name = new_name.strip()
    if not new_name or new_name in (".", "..") or any(c in new_name for c in '\\/:*?"<>|'):
        raise ValueError("That name isn't allowed.")
    ext = os.path.splitext(src)[1] if os.path.isfile(src) else ""
    if ext and not new_name.lower().endswith(ext.lower()):
        new_name += ext  # people type just the name; never drop the extension
    target = os.path.join(os.path.dirname(src), new_name)
    if os.path.lexists(target) and norm(target) != norm(src):
        raise FileExistsError("Something with that name already exists.")
    retry_locked(os.rename, src, target)
    forget_sizes(src)
    undo_stack.append({"type": "rename", "from": src, "to": target})
    log("rename", src, target)
    return {"to": target}


def delete(p):
    p = check_modify(p)
    size = dir_size(p)[0] if os.path.isdir(p) else os.path.getsize(p)
    retry_locked(recycle, p)
    forget_sizes(p)
    log("recycle", p, "", size)
    return {"freed": size}


def undo():
    if not undo_stack:
        raise ValueError("Nothing to undo. (Deletes are undone from the Recycle Bin.)")
    op = undo_stack[-1]
    if os.path.lexists(op["from"]):
        raise FileExistsError("Something is already back at the original spot.")
    if not os.path.lexists(op["to"]):
        raise FileNotFoundError("It's no longer where it was moved to.")
    retry_locked(shutil.move, op["to"], op["from"])
    undo_stack.pop()
    forget_sizes(op["to"], op["from"])
    if op.get("createdDir"):
        try:
            os.rmdir(op["createdDir"])  # only succeeds if it's empty again
        except OSError:
            pass
    log("undo-" + op["type"], op["to"], op["from"])
    return op


TRUENAS = r"\\TRUENAS\hlucas"
STAGING = r"D:\To TrueNAS"  # always-available drop folder; dragged to TrueNAS by hand


def places():
    cfg = load_config()
    user = [{"name": n, "path": str(HOME / n), "icon": i} for n, i in
            (("Desktop", "🖥️"), ("Documents", "📄"), ("Downloads", "⬇️"), ("Music", "🎵"), ("Pictures", "🖼️"),
             ("Videos", "🎬"), ("3D Objects", "🧊")) if (HOME / n).is_dir()]
    drives = [{"name": f"{d}:", "path": f"{d}:\\", "icon": "💽"} for d in "CDEFGH" if os.path.isdir(f"{d}:\\")]
    nas = [{"name": "To TrueNAS (on D:)", "path": STAGING, "icon": "📤"}]
    if os.path.isdir(cfg.get("truenas", TRUENAS)):
        nas.append({"name": "TrueNAS (hlucas)", "path": cfg.get("truenas", TRUENAS), "icon": "🗄️"})
    return {"user": user, "drives": drives, "nas": nas, "recent": cfg.get("recent", [])}


def browse(p):
    """Folder names only (no files), for the Move-to picker. Any folder may be
    looked at; nothing here changes anything."""
    p = os.path.abspath(p) if not p.startswith("\\\\") else p
    try:
        with os.scandir(p) as it:
            dirs = sorted((e.name for e in it if e.is_dir(follow_symlinks=False)
                           and not e.name.startswith(("$", ".")) and e.name.lower() != "system volume information"),
                          key=str.lower)
    except FileNotFoundError:
        raise FileNotFoundError(("Can't reach TrueNAS from here. Open it once in Explorer, then try again."
                                 if p.startswith("\\\\") else "That folder doesn't exist."))
    except PermissionError:
        raise PermissionError("Windows won't let File Sorter look in that folder.")
    up = os.path.dirname(p.rstrip("\\"))
    if p.startswith("\\\\") and up.count("\\") < 3:
        up = None  # \\server is not browsable
    if up and os.path.splitdrive(p)[1] in ("\\", ""):
        up = None
    return {"path": p, "dirs": dirs, "up": up, "blocked": protected(p)}


def make_dir(parent, name):
    name = name.strip()
    if not name or name in (".", "..") or any(c in name for c in '\\/:*?"<>|'):
        raise ValueError("That folder name isn't allowed.")
    target = os.path.join(parent, name)
    if protected(target):
        raise PermissionError("Won't create folders in Windows or Program Files.")
    os.makedirs(target, exist_ok=True)
    return {"path": target}


def remember_recent(dest):
    cfg = load_config()
    rec = [d for d in cfg.get("recent", []) if d.lower() != dest.lower()]
    cfg["recent"] = ([dest] + rec)[:8]
    save_config(cfg)


def reveal(p):
    p = check_read(p)
    subprocess.Popen(f'explorer /select,"{p}"')
    return {}


def launch(p):
    p = check_read(p)
    if os.path.isdir(p) or os.path.splitext(p)[1].lower() in NO_LAUNCH:
        raise PermissionError("Won't open programs or shortcuts from here. Use 'Show in Explorer'.")
    os.startfile(p)
    return {}


# ---------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _split(self):
        u = urllib.parse.urlsplit(self.path)
        return u.path, dict(urllib.parse.parse_qsl(u.query))

    def _host_ok(self):
        return self.headers.get("Host", "") in (f"127.0.0.1:{PORT}", f"localhost:{PORT}")

    def _send(self, code, body, ctype, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj).encode(), "application/json")

    def do_GET(self):
        path, q = self._split()
        if not self._host_ok():
            return self._send(403, b"Bad host", "text/plain")
        if not secrets.compare_digest(q.get("t", ""), TOKEN):
            return self._send(403, "Open File Sorter from its shortcut.".encode(), "text/plain; charset=utf-8")
        try:
            if path == "/":
                html = (HERE / "ui.html").read_bytes()
                return self._send(200, html, "text/html; charset=utf-8",
                                  {"Content-Security-Policy": "default-src 'self'; script-src 'unsafe-inline'; "
                                   "style-src 'unsafe-inline'; img-src 'self' data:; media-src 'self'; "
                                   "frame-src 'self'; connect-src 'self'"})
            if path == "/api/state":
                cfg = load_config()
                return self._json({"roots": roots, "defaultRoots": DEFAULT_ROOTS, "dests": cfg.get("dests", []),
                                   "home": str(HOME), "start": START or DEFAULT_ROOTS[0]})
            if path == "/api/list":
                return self._json(list_dir(q.get("path", "")))
            if path == "/api/dirsize":
                size, count = dir_size(check_read(q.get("path", "")))
                return self._json({"size": size, "files": count})
            if path == "/api/info":
                return self._json(info(q.get("path", "")))
            if path == "/api/places":
                return self._json(places())
            if path == "/api/browse":
                return self._json(browse(q.get("path", "")))
            if path == "/file":
                return self._file(q.get("path", ""))
            self._json({"error": "not found"}, 404)
        except (OSError, ValueError) as e:
            self._json({"error": str(e)}, 400)

    def do_POST(self):
        path, _ = self._split()
        if not self._host_ok() or not secrets.compare_digest(self.headers.get("X-Token", ""), TOKEN):
            return self._send(403, b"Forbidden", "text/plain")
        if not self.headers.get("Content-Type", "").startswith("application/json"):
            return self._send(415, b"JSON only", "text/plain")
        n = int(self.headers.get("Content-Length", 0))
        if n > 1_000_000:
            return self._send(413, b"Too big", "text/plain")
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
            with lock:
                if path == "/api/delete":
                    return self._json(delete(body["path"]))
                if path == "/api/move":
                    res = move(body["path"], body["dest"], body["cwd"])
                    remember_recent(res["destDir"])
                    return self._json(res)
                if path == "/api/mkdir":
                    return self._json(make_dir(body["parent"], body["name"]))
                if path == "/api/rename":
                    return self._json(rename(body["path"], body["name"]))
                if path == "/api/undo":
                    return self._json(undo())
                if path == "/api/reveal":
                    return self._json(reveal(body["path"]))
                if path == "/api/launch":
                    return self._json(launch(body["path"]))
                if path == "/api/addroot":
                    return self._json({"root": add_root(body["path"])})
                if path == "/api/dests":
                    cfg = load_config()
                    cfg["dests"] = [str(d) for d in body["dests"]][:9]
                    save_config(cfg)
                    return self._json({"dests": cfg["dests"]})
                if path == "/api/quit":
                    self._json({})
                    threading.Thread(target=server.shutdown, daemon=True).start()
                    return
            self._json({"error": "not found"}, 404)
        except (OSError, ValueError, KeyError) as e:
            self._json({"error": str(e) or type(e).__name__}, 400)

    def _file(self, p):
        p = check_read(p)
        if not os.path.isfile(p):
            return self._json({"error": "not a file"}, 404)
        ext = os.path.splitext(p)[1].lower()
        ctype = MIME.get(ext) or mimetypes.guess_type(p)[0] or "application/octet-stream"
        if ext in AS_PLAIN_TEXT:
            ctype = "text/plain; charset=utf-8"
        size = os.path.getsize(p)
        start, end, code = 0, size - 1, 200
        rng = self.headers.get("Range", "")
        if rng.startswith("bytes=") and size:
            s, _, e = rng[6:].split(",")[0].strip().partition("-")
            try:
                if s:
                    start, end = int(s), (int(e) if e else size - 1)
                else:
                    start = max(0, size - int(e))
            except ValueError:
                start, end = 0, size - 1
            # Browsers ask for "bytes=0-" on a video and then stop reading, which would
            # pin the file open (and block moving it) until the tab lets go. Answering
            # in small pieces keeps every file handle short-lived.
            end = min(end, size - 1, start + RANGE_CHUNK - 1)
            if start > end:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            code = 206
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(max(0, end - start + 1)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if ext != ".pdf":  # the browser's PDF viewer won't run inside a sandbox
            self.send_header("Content-Security-Policy", "sandbox")
        if code == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        try:
            with open_shared(p) as f:
                f.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = f.read(min(262144, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
        except (ConnectionError, OSError):
            pass  # browser stopped a video mid-stream


class Server(ThreadingHTTPServer):
    # On Windows SO_REUSEADDR lets a second copy bind a port that's already in
    # use, so two File Sorters would silently share one; claim it exclusively.
    allow_reuse_address = False

    def server_bind(self):
        import socket
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def main():
    global PORT, server, START
    args = [a for a in sys.argv[1:] if a != "--no-browser"]
    if args:
        START = add_root(args[0])
    for port in range(8765, 8790):
        try:
            server = Server(("127.0.0.1", port), Handler)
            PORT = port
            break
        except OSError:
            continue
    else:
        raise SystemExit("No free port")
    server.daemon_threads = True
    try:
        os.makedirs(STAGING, exist_ok=True)
    except OSError:
        pass  # no D: drive; the picker just won't have it
    url = f"http://127.0.0.1:{PORT}/?t={TOKEN}"
    if "--no-browser" in sys.argv:
        print(url, flush=True)
    else:
        webbrowser.open(url)
    server.serve_forever()


if __name__ == "__main__":
    main()
