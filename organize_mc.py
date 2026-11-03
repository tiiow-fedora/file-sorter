"""Sort Downloads\\minecraft by what each file actually is (read from the jar /
pack metadata), plus the last Downloads strays. Agreed 2026-10-16.

    python organize_mc.py            dry run
    python organize_mc.py --apply    do it (logged; undo file written)
    python organize_mc.py --undo     put every move back
"""
import csv
import json
import os
import re
import shutil
import sys
import time
import zipfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
H = Path(os.environ["USERPROFILE"])
DL = H / "Downloads"
MC = DL / "minecraft"
HERE = Path(__file__).resolve().parent
UNDO = HERE / "organize_mc_undo.json"

F17 = MC / "1.7.10 Forge (GTNH & NTM)"
PAPER = MC / "Paper Server 26.1"
FAB26 = MC / "Fabric 26.x Mods"
NEO = MC / "NeoForge 1.21.1 (Long Haul)"
FAB121 = MC / "Fabric 1.21 (old server)"
F118 = MC / "Forge 1.18.2"
PACKS = MC / "Modpacks"
SHADERS = MC / "Shaders & Resource Packs"
TOOLS = MC / "Tools"
DEV = MC / "Mod Dev Projects"


def detect(p):
    try:
        z = zipfile.ZipFile(p)
    except (zipfile.BadZipFile, OSError):
        return "?"
    n = set(z.namelist())
    rd = lambda x: z.read(x).decode("utf-8", "replace")
    if "plugin.yml" in n or "paper-plugin.yml" in n:
        return "paper"
    if "fabric.mod.json" in n:
        try:
            mc = str((json.loads(rd("fabric.mod.json"), strict=False).get("depends") or {}).get("minecraft", ""))
        except ValueError:
            mc = ""
        return "fabric121" if "1.21" in mc else "fabric26"
    if "META-INF/neoforge.mods.toml" in n:
        return "neo"
    if "META-INF/mods.toml" in n:
        return "f118" if "1.18" in rd("META-INF/mods.toml") else "?"
    if "mcmod.info" in n or any(x.startswith(("cpw/mods/fml", "net/minecraftforge")) for x in n):
        return "f17"
    if "modrinth.index.json" in n:
        dep = json.loads(rd("modrinth.index.json")).get("dependencies", {})
        return "neo" if "neoforge" in dep else "pack"
    if "manifest.json" in n:
        return "neo"  # the CurseForge export of Modded 1.0.0 (NeoForge 1.21.1)
    if "pack.mcmeta" in n:
        return "datapack"
    if any(x.startswith("shaders/") for x in n):
        return "shader"
    return "?"


WHERE = {"paper": PAPER / "plugins", "fabric26": FAB26, "fabric121": FAB121, "neo": NEO, "f118": F118,
         "f17": F17, "pack": PACKS, "datapack": PAPER / "datapacks", "shader": SHADERS}
BY_NAME = {  # things metadata can't classify
    "paper-26.1.2-72.jar": PAPER, "players-drop-heads-26.1-101.1.zip": PAPER / "datapacks",
    "Xray_Ultimate_26.X_v5.4.0.zip": SHADERS, "Minecraft.ttf": TOOLS,
    "forge-1.7.10-10.13.4.1614-1.7.10-src.zip": F17, "GT_New_Horizons_2.8.4_Java_17-25.zip": F17,
    "LongHaul-client-mods.zip": NEO, "Fabric 26.1.2 1.0.0.mrpack": PACKS,
    "lithostitched-1.7.10-fabric-26.2.jar": FAB26,
}
DIRS = {"gtnh": F17, "New folder (4)": PAPER, "mc": FAB121, "mods": FAB121, "config": FAB121, "versions": FAB121,
        "logs": FAB121, "playerdata": FAB121, "treecapitator_mdk_fixed": DEV, "autoop-mod": DEV,
        "mcrcon-0.7.2-windows-x86-64": TOOLS, "BedrockLauncher.2025.8.25.24": TOOLS}
RENAME = {"New folder (4)": "server files"}  # inside its new home

moves, recycle = [], []
for p in sorted(MC.iterdir(), key=lambda p: p.name.lower()):
    if p.is_dir():
        if p.name in DIRS:
            moves.append((p, DIRS[p.name], RENAME.get(p.name, p.name)))
        continue
    dest = BY_NAME.get(p.name) or WHERE.get(detect(p))
    if dest:
        moves.append((p, dest, p.name))
    else:
        print("  (left in place, unknown:", p.name + ")")

# Downloads strays
moves += [(DL / "README.md", H / "3D Objects" / "3D Printing" / "Fan Mount", "README.md"),
          (DL / "Claude outputs" / "quest-book-content.md", NEO, "quest-book-content.md"),
          (DL / "bot.js", H / "Documents" / "Projects" / "discord-claude-bot", "bot.js"),
          (DL / "discord-category-cloner", H / "Documents" / "Projects", "discord-category-cloner")]
recycle += [DL / "quest-book-content.md"]  # byte-identical copy of the one in Claude outputs
TOOL_ITEMS = ["AnyDesk.exe", "AutoClicker-3.1.1.exe", "rufus-4.15p.exe", "rbxlx-to-rojo.exe",
              "[Guru3D]-DDU", "ADB_AppControl", "HackBGRT-2.6.0"]
moves += [(DL / n, DL / "Tools", n) for n in TOOL_ITEMS]
moves = [m for m in moves if m[0].exists()]


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
            if os.path.exists(m["to"]) and not os.path.exists(m["from"]):
                shutil.move(m["to"], m["from"])
        print(f"Moved {len(done)} items back.")
        return
    groups = {}
    for s, d, n in moves:
        groups.setdefault(str(d).replace(str(H), "~"), []).append(n)
    for d, names in groups.items():
        print(f"{len(names):3} -> {d}:  " + ", ".join(names[:4]) + (" …" if len(names) > 4 else ""))
    print("Recycle:", ", ".join(str(p.relative_to(H)) for p in recycle if p.exists()))
    if "--apply" not in sys.argv:
        return
    done = []
    with (HERE / "actions.csv").open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        for s, d, n in moves:
            d.mkdir(parents=True, exist_ok=True)
            t = d / n
            if t.exists():
                print("  skipped (name taken):", t)
                continue
            shutil.move(str(s), str(t))
            done.append({"from": str(s), "to": str(t)})
            w.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), "organize-mc", s, t, ""])
        for p in recycle:
            if p.exists():
                to_bin(p)
                w.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), "recycle", p, "", ""])
    UNDO.write_text(json.dumps(done, indent=1), "utf-8")
    for d in (DL / "Claude outputs",):
        if d.exists() and not any(d.iterdir()):
            d.rmdir()
    print(f"\nMoved {len(done)}. Undo: python organize_mc.py --undo")


if __name__ == "__main__":
    main()
