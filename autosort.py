"""Bulk-apply the sorting scheme learned from File Sorter's log to a folder.

    python autosort.py            dry run: show what would move where
    python autosort.py --apply    move them (logged to actions.csv, undo file written)
    python autosort.py --undo     move everything from the last --apply back
"""
import csv
import json
import os
import shutil
import sys
import time
from pathlib import Path

HOME = Path(os.environ["USERPROFILE"])
SRC = HOME / "Downloads"
HERE = Path(__file__).resolve().parent
UNDO = HERE / "autosort_undo.json"

RULES = [  # (extensions, destination)
    (".jar .mrpack .mcpack .mcworld .mcaddon .litematic .schem .schematic .nbt .snbt", SRC / "minecraft"),
    (".mp4 .mov .mkv .webm .avi .m4v", HOME / "Videos"),
    (".mp3 .flac .wav .ogg .m4a .aac .opus", HOME / "Music"),
    (".png .jpg .jpeg .jfif .webp .gif .bmp .heic .avif", HOME / "Pictures" / "From Downloads"),
    (".unitypackage .stl .blend .fbx .obj .3mf .glb .gltf .dae", HOME / "3D Objects"),
]
EXT_DEST = {e: d for exts, d in RULES for e in exts.split()}
# Folders that are clearly Minecraft mod/server leftovers.
MC_FOLDERS = {"playerdata", "config", "logs", "treecapitator_mdk_fixed", "autoop-mod", "mcrcon-0.7.2-windows-x86-64"}


def unique(dest_dir, name):
    t = dest_dir / name
    if not t.exists():
        return t
    stem, ext = os.path.splitext(name)
    i = 2
    while (dest_dir / f"{stem} ({i}){ext}").exists():
        i += 1
    return dest_dir / f"{stem} ({i}){ext}"


def plan():
    out = []
    for p in sorted(SRC.iterdir(), key=lambda p: p.name.lower()):
        if p.name.lower() == "desktop.ini":
            continue
        if p.is_dir():
            if p.name.lower() in MC_FOLDERS:
                out.append((p, SRC / "minecraft"))
        elif p.suffix.lower() in EXT_DEST:
            out.append((p, EXT_DEST[p.suffix.lower()]))
    return out


def main():
    if "--undo" in sys.argv:
        moves = json.loads(UNDO.read_text("utf-8"))
        for m in reversed(moves):
            if os.path.exists(m["to"]) and not os.path.exists(m["from"]):
                shutil.move(m["to"], m["from"])
        print(f"Moved {len(moves)} items back.")
        UNDO.unlink()
        return
    moves = plan()
    by_dest = {}
    for p, d in moves:
        by_dest.setdefault(str(d), []).append(p.name)
    for d, names in by_dest.items():
        print(f"{len(names):4}  -> {d.replace(str(HOME), '~')}")
        print("        e.g. " + ", ".join(names[:4]) + (" …" if len(names) > 4 else ""))
    left = [p for p in SRC.iterdir() if p.name.lower() != "desktop.ini" and p not in {m[0] for m in moves}]
    print(f"\n{len(moves)} would move; {len(left)} left for you to review "
          f"({sum(1 for p in left if p.is_dir())} folders, {sum(1 for p in left if p.is_file())} files).")
    if "--apply" not in sys.argv:
        return
    done = []
    with (HERE / "actions.csv").open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        for p, d in moves:
            d.mkdir(parents=True, exist_ok=True)
            t = unique(d, p.name)
            try:
                shutil.move(str(p), str(t))
            except OSError as e:
                print("  skipped", p.name, "-", e)
                continue
            done.append({"from": str(p), "to": str(t)})
            w.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), "autosort", str(p), str(t), ""])
    UNDO.write_text(json.dumps(done, indent=1), "utf-8")
    print(f"\nMoved {len(done)}. Undo with: python autosort.py --undo")


if __name__ == "__main__":
    main()
