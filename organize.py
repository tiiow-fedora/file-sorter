"""One-off tidy of the user folders (3D Objects, Desktop, Documents, Music,
Pictures, Videos) agreed on 2026-10-16.

    python organize.py            dry run
    python organize.py --apply    do it (moves logged + undo file; dupes to Recycle Bin)
    python organize.py --undo     put every MOVE back (recycled items: restore from the bin)
"""
import csv
import ctypes
import json
import os
import re
import shutil
import sys
import time
from ctypes import wintypes
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
H = Path(os.environ["USERPROFILE"])
HERE = Path(__file__).resolve().parent
UNDO = HERE / "organize_undo.json"
V, M, P, D, O, DT = (H / "Videos", H / "Music", H / "Pictures", H / "Documents", H / "3D Objects", H / "Desktop")

moves = []      # (src, dest_dir)
recycle = []    # paths
rmdirs = []     # empty app folders


def mv(folder, names, dest):
    for n in names:
        p = folder / n
        if p.exists():
            moves.append((p, dest))


def loose(folder):
    return [p for p in folder.iterdir() if p.is_file() and p.name.lower() != "desktop.ini"]


# ---------------- Videos
mv(V, ["Borat.2006.1080p.BrRip.x264.YIFY.mp4", "Spider-Man.Brand.New.Day.2026.TS-[noAD]DKS(DUAL).1080p.English.mp4"], V / "Movies")
mv(V, ["Video Project 2.mp4", "Timeline 1.mp4"], V / "Edits")
recycle += [V / f"Video Project 2 ({i}).mp4" for i in range(2, 6)]
for p in loose(V):
    if p in recycle or any(p == s for s, _ in moves):
        continue
    if re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}-\d{2}-\d{2}\.mp4", p.name) or p.name.startswith(("Recording_", "ScreenRecording_")):
        moves.append((p, V / "Recordings"))
    elif re.fullmatch(r"\d{4}-\d{4}\.mp4", p.name):
        moves.append((p, V / "Blender Renders"))
    elif p.suffix.lower() in (".mp4", ".mov"):
        moves.append((p, V / "Clips & Memes"))
rmdirs += [V / n for n in ("AnyDesk", "Medal", "Captures", "Discord Clips", "Radeon ReLive")]

# ---------------- Music
mv(M, ["shitsongv1.mp3", "Project_4.mp3", "fangirldisstrack.mp3", "mason diss track v2 might be worse or better idk.mp3"], M / "My Tracks")
mv(M, ["Clutterfunk.mp3", "Pigstep (Stereo Mix).mp3", "Forever Bound - Stereo Madness.mp3", "Wet Hands but it's in swing rhythm....mp3",
       "11 - Cow Cud Is a Twin..flac", "11 - Cow Cud Is a Twin.mp3", "Masta Artisan Oh My God Official Music Video.mp3"], M / "Songs")
mv(M, ["Family Guy Cutaway SFX (extended tail).mp3", "fortnite-boogie-bomb-sound-effect-(hd)-made-with-Voicemod.mp3", "Voicy_Boogie Bomb.mp3",
       "hardgroove-synth-stabs-orchestral-hit.wav", "rhythm-lab-amen-remake_170bpm.wav", "save-breakcore-drums_170bpm.wav", "morse.wav",
       "burger king plane guy.mp3", "ReelAudio-95609.mp3"], M / "Sound Effects & Samples")
mv(M, ["Voicemail Empire Networks_260825_150428.m4a", "ScreenRecording_12-27-2025_00-00-57_1.mp3", "ScreenRecording_12-27-2025_00-00-57_1-enhanced.mp3",
       "IMG_0834.mp3", "IMG_0834-enhanced.mp3", "20251121_212729.mp3", "20251121_212729-enhanced.mp3",
       "MedalTVGoldMiningSimulator20260906140931221-trim-1788725468488.mp3", "c85a6b21a211e1eccdb63b3bb0d8be9d.mp3"], M / "Voice & Recordings")
recycle += [M / "karen.zip", M / "YT Downloads tag backup", M / "YT Downloads metadata backup"]
recycle += sorted(p for p in M.iterdir() if p.is_file() and p.name.startswith("AlbumArt_{") and p.suffix.lower() == ".jpg")
rmdirs += [M / "Medal"]

# ---------------- Pictures
for p in loose(P):
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}_\d{2}\.\d{2}\.\d{2}\.png", p.name):
        moves.append((p, P / "Minecraft Screenshots"))
mv(P, ["realcolors.png", "realcustomers.webp", "splash.bmp", "splash.jpg"], P / "Mod & Project Art")
mv(P, ["TWMate.com-2fdea1926a6f3c49300c7ee224c36919.mp4"], V / "Clips & Memes")
recycle += [P / "aheat (2).zip"]
for p in loose(P):
    if p in recycle or any(p == s for s, _ in moves):
        continue
    if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"):
        moves.append((p, P / "Misc"))
rmdirs += [P / "UbisoftConnect"]

# ---------------- Documents
mv(D, ["Harrison_Lucas_FPPA_Cover_Letter.docx", "Harrison_Lucas_FPPA_Resume.docx"], D / "Jobs")
mv(D, ["alexth.png", "alexth.xcf", "tuxcustom.png", "tuxcustomlowqual.png", "tuxcustomlowqual.xcf",
       "2Untitled.blend", "Untitled.blend", "Untitled.blend1"], D / "Art (GIMP & Blender)")
mv(D, ["data-center", "claudebackup", "removeunwanted.py", "mc.html", "index.html"], D / "Projects")
mv(D, ["uihlfgrehkbildzgf 1.0.0.mrpack"], D / "Minecraft")
mv(D, ["CE3V3SE_C_keeper_x2.gcode"], O / "3D Printing" / "Fan Mount")

# ---------------- 3D Objects
mv(O, ["A_fan_frame.stl", "A_fan_frame_half_x2.stl", "B_drive_sled.stl", "C_clamp_x2.stl", "C_keeper_x2.stl", "CE3V3SE_C_keeper_x2.3mf"],
   O / "3D Printing" / "Fan Mount")
mv(O, [p.name for p in O.iterdir() if p.suffix.lower() == ".unitypackage"], O / "Unity Packages")
mv(O, ["Nicoreda_Protodal-20260601T214530Z-3-001", "Nicoreda_Protodal-20260601T214530Z-3-001a"], O / "VRChat Avatars")

# ---------------- Desktop
mv(DT, ["Geometry_Final_CheatSheet.html", "cheat_imgs", "geo_pages"], DT / "Study" / "Geometry")
mv(DT, ["Add Artist to Lidarr.bat", "Add Artist to Lidarr.ps1"], DT / "Lidarr Scripts")
mv(DT, ["plugin"], D / "Projects")
recycle += [DT / "brushed_concrete_04_4k.blend.zip"]

# ---------------- big move off C:
BIG = [(M / "musicshare", Path(r"D:\_cleanup_holding"))]


# ------------------------------------------------------------------ engine

class SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", ctypes.c_void_p),
                ("pTo", ctypes.c_void_p), ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]


def to_bin(p):
    buf = ctypes.create_unicode_buffer(str(p) + "\0")
    op = SHFILEOPSTRUCTW(wFunc=3, pFrom=ctypes.addressof(buf), fFlags=0x0040 | 0x0010 | 0x0004 | 0x4000)
    rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if rc or op.fAnyOperationsAborted or p.exists():
        raise OSError(f"recycle failed ({rc:#x})")


def unique(dest_dir, name):
    t = dest_dir / name
    if not t.exists():
        return t
    stem, ext = os.path.splitext(name)
    i = 2
    while (dest_dir / f"{stem} ({i}){ext}").exists():
        i += 1
    return dest_dir / f"{stem} ({i}){ext}"


def size(p):
    if p.is_file():
        return p.stat().st_size
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def main():
    if "--undo" in sys.argv:
        done = json.loads(UNDO.read_text("utf-8"))
        for m in reversed(done):
            if os.path.exists(m["to"]) and not os.path.exists(m["from"]):
                shutil.move(m["to"], m["from"])
        print(f"Moved {len(done)} items back. Recycled duplicates are in the Recycle Bin.")
        return
    short = lambda p: str(p).replace(str(H), "~")
    groups = {}
    for s, d in moves:
        groups.setdefault(short(d), []).append(s.name)
    for d, names in groups.items():
        print(f"{len(names):4} -> {d}:  " + ", ".join(names[:3]) + (" …" if len(names) > 3 else ""))
    rec = [p for p in recycle if p.exists()]
    print(f"\nRecycle {len(rec)} duplicates, {sum(size(p) for p in rec)/1e9:.1f} GB: "
          + ", ".join(p.name for p in rec if not p.name.startswith("AlbumArt_")) + f" + {sum(p.name.startswith('AlbumArt_') for p in rec)} AlbumArt jpgs")
    empties = [d for d in rmdirs if d.exists() and not any(f.is_file() and f.name.lower() != "desktop.ini" for f in d.rglob("*"))]
    print(f"Remove {len(empties)} empty app folders: " + ", ".join(short(d) for d in empties))
    for s, d in BIG:
        if s.exists():
            print(f"Move off C: {short(s)} -> {d}")
    if "--apply" not in sys.argv:
        return

    done, log = [], (HERE / "actions.csv").open("a", newline="", encoding="utf-8")
    w = csv.writer(log)
    stamp = lambda: time.strftime("%Y-%m-%d %H:%M:%S")
    for s, d in moves:
        d.mkdir(parents=True, exist_ok=True)
        t = unique(d, s.name)
        try:
            shutil.move(str(s), str(t))
        except OSError as e:
            print("  move failed:", s.name, e)
            continue
        done.append({"from": str(s), "to": str(t)})
        w.writerow([stamp(), "organize", s, t, ""])
    UNDO.write_text(json.dumps(done, indent=1), "utf-8")
    freed = 0
    for p in rec:
        try:
            sz = size(p)
            to_bin(p)
            freed += sz
            w.writerow([stamp(), "recycle", p, "", sz])
        except OSError as e:
            print("  recycle failed:", p.name, e)
    for d in empties:
        try:
            shutil.rmtree(d)
            w.writerow([stamp(), "rmdir-empty", d, "", 0])
        except OSError as e:
            print("  rmdir failed:", d, e)
    log.close()
    print(f"\nMoved {len(done)}, recycled {freed/1e9:.1f} GB, removed {len(empties)} empty folders. Undo moves: python organize.py --undo")


if __name__ == "__main__":
    main()
