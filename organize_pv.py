"""Second pass on Pictures + Videos after the user renamed everything (2026-10-16).
Groups by subject using the new names.

    python organize_pv.py            dry run
    python organize_pv.py --apply    do it (logged; undo file written)
    python organize_pv.py --undo     put every move back
"""
import csv
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
H = Path(os.environ["USERPROFILE"])
P, V = H / "Pictures", H / "Videos"
HERE = Path(__file__).resolve().parent
UNDO = HERE / "organize_pv_undo.json"

FRIENDS = r"^(alex|matt|matthew|mason|tyler|young-aaron|selfie|dapper_alex)"
PIC_RULES = [  # (regex on lowercase name, destination) — first match wins
    (r"^dnd-map", P / "dndshit" / "maps"),
    (r"^dnd-", P / "dndshit"),
    (r"(mc-skin)", P / "Minecraft" / "Skins"),
    (r"(tuff|end-fight|old-server-pic)", P / "Minecraft"),
    (r"(protogen|furry|boykisser)", P / "Protogen & Furry"),
    (r"(pfp|banner)", P / "Profile Pics & Banners"),
    (r"(datacenterhelp|chaos-button|tuxcustom)", P / "Mod & Project Art"),
    (r"(firstspook|lumberland)", P / "Roblox"),
    (FRIENDS, P / "Friends"),
    (r"meme", P / "Memes"),
]
VID_RULES = [
    (r"mc-server", V / "Minecraft"),
    (r"promo", V / "Projects"),
    (r"^chair-", V / "Blender Renders"),
    (FRIENDS, V / "Friends"),
    (r".", V / "Memes"),
]
SOURCES = [(P / "From Downloads", PIC_RULES), (P / "Misc", PIC_RULES), (P, PIC_RULES),
           (V / "Clips & Memes", VID_RULES), (V / "Recordings", VID_RULES), (V / "Blender Renders", VID_RULES)]
RENAME_DIRS = [(P / "moon eclips pics", P / "Moon Eclipse 2026-08-27")]
RECYCLE = [P / "moon eclips pics" / "_claude_tmp"]
EMPTY_AFTER = [P / "From Downloads", P / "Misc", V / "Clips & Memes", V / "Recordings"]

moves = []
for src, rules in SOURCES:
    if not src.is_dir():
        continue
    for f in sorted(src.iterdir(), key=lambda p: p.name.lower()):
        if not f.is_file() or f.name.lower() == "desktop.ini":
            continue
        for rx, dest in rules:
            if re.search(rx, f.name.lower()):
                if dest != src:
                    moves.append((f, dest))
                break
        else:
            print("  (no rule, stays put):", f.relative_to(H))


def to_bin(p):
    import ctypes
    from ctypes import wintypes

    class OP(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", ctypes.c_void_p),
                    ("pTo", ctypes.c_void_p), ("fFlags", ctypes.c_ushort), ("ab", wintypes.BOOL),
                    ("hm", ctypes.c_void_p), ("t", wintypes.LPCWSTR)]
    buf = ctypes.create_unicode_buffer(str(p) + "\0")
    op = OP(wFunc=3, pFrom=ctypes.addressof(buf), fFlags=0x0040 | 0x0010 | 0x0004 | 0x4000)
    if ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op)) or p.exists():
        raise OSError("recycle failed")


def main():
    if "--undo" in sys.argv:
        done = json.loads(UNDO.read_text("utf-8"))
        for m in reversed(done):
            Path(m["from"]).parent.mkdir(parents=True, exist_ok=True)
            if os.path.exists(m["to"]) and not os.path.exists(m["from"]):
                shutil.move(m["to"], m["from"])
        print(f"Moved {len(done)} items back.")
        return
    groups = {}
    for s, d in moves:
        groups.setdefault(str(d).replace(str(H), "~"), []).append(s.name)
    for d, names in sorted(groups.items()):
        print(f"{len(names):3} -> {d}:  " + ", ".join(names[:5]) + (" …" if len(names) > 5 else ""))
    for a, b in RENAME_DIRS:
        print(f"Rename folder: {a.name} -> {b.name}")
    print("Recycle:", ", ".join(str(p.relative_to(H)) for p in RECYCLE if p.exists()))
    if "--apply" not in sys.argv:
        return
    done = []
    with (HERE / "actions.csv").open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        log = lambda a, s, t: w.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), a, s, t, ""])
        for p in RECYCLE:
            if p.exists():
                to_bin(p)
                log("recycle", p, "")
        for s, d in moves:
            d.mkdir(parents=True, exist_ok=True)
            t = d / s.name
            if t.exists():
                print("  skipped (name taken):", t)
                continue
            shutil.move(str(s), str(t))
            done.append({"from": str(s), "to": str(t)})
            log("organize-pv", s, t)
        for a, b in RENAME_DIRS:
            if a.exists() and not b.exists():
                a.rename(b)
                done.append({"from": str(a), "to": str(b)})
                log("rename-dir", a, b)
    for d in EMPTY_AFTER:
        if d.is_dir() and not [x for x in d.iterdir() if x.name.lower() != "desktop.ini"]:
            shutil.rmtree(d)
    UNDO.write_text(json.dumps(done, indent=1), "utf-8")
    print(f"\nMoved {len(done)}. Undo: python organize_pv.py --undo")


if __name__ == "__main__":
    main()
