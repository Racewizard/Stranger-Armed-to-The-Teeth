r"""Assemble the AT3 release package: _release\AT3_v<version>\ and its .zip.

The development folder is also a live, modded game install, so it is full of
state that must NOT ship: backups of modded bundles, the author's custom
characters, logs, caches, edit CSVs. This copies an explicit ALLOW-LIST - a new
file only ships once someone adds it here on purpose.

    python StrangerAT3\make_release.py

What ships, relative to the game folder the player extracts into:

    README - AT3 v<version>.txt       install, what's new, uninstall
    StrangerAT3\                      launcher exe + its PowerShell source,
                                      bundled Python runtime, notices,
                                      reference data, an empty Presets folder
    ModTools\*.py                     the tools (source - AT3 is open source)
    (SWSE is NOT shipped - it is separate software by another developer
     that AT3 requires; players install it themselves.)

Nothing from data\ ships: no Oddworld game data is redistributed.
"""
import csv, glob, io, os, re, shutil, subprocess, sys, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC_PS1 = os.path.join(HERE, "Stranger_AT3_v2.ps1")
VERSION = re.search(r'\$script:AT3Version\s*=\s*"([0-9.]+)"', open(SRC_PS1, encoding="utf-8-sig").read()).group(1)
NAME = "AT3_v%s" % VERSION
OUTDIR = os.path.join(ROOT, "_release")
PKG = os.path.join(OUTDIR, NAME)

AT3_FILES = ["Stranger AT3.exe", "Stranger_AT3_v2.ps1", "Stranger_AT3.ico", "header_logo.png",
             "build.ps1", "build_runtime.py", "make_release.py", "THIRD_PARTY_NOTICES.txt",
             "AmmoNames.csv", "AmmoPatchMap.csv", "DisplayNames.csv", "HashNames.csv",
             "RegionNames.csv", "PropNames.csv"]
REGIONDATA = ("env_*.csv", "envregion_*.csv", "proplib_*.csv")
PRESETS = []          # none ship in 0.3.0


def copy(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)


def main():
    exe = os.path.join(HERE, "Stranger AT3.exe")
    if os.path.getmtime(exe) < os.path.getmtime(SRC_PS1):
        sys.exit("REFUSED: Stranger AT3.exe is older than Stranger_AT3_v2.ps1 - run build.ps1 first")
    if not os.path.exists(os.path.join(HERE, "python", "python.exe")):
        sys.exit("REFUSED: no bundled runtime - run build_runtime.py first")
    # Empty the folder rather than remove it: an Explorer window or shell
    # sitting in it holds the directory itself open, not its contents.
    os.makedirs(PKG, exist_ok=True)
    for item in os.listdir(PKG):
        p = os.path.join(PKG, item)
        shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
    at3 = os.path.join(PKG, "StrangerAT3")

    for f in AT3_FILES:
        copy(os.path.join(HERE, f), os.path.join(at3, f))
    # Ammo table: the author's CURRENT values reset to vanilla.
    with io.open(os.path.join(HERE, "AmmoKnockback.csv"), encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    with io.open(os.path.join(at3, "AmmoKnockback.csv"), "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for r in rows:
            r["CurrentKnock"], r["CurrentKnockPlayer"] = r["VanillaKnock"], r["VanillaKnockPlayer"]
            w.writerow(r)
    shutil.copytree(os.path.join(HERE, "python"), os.path.join(at3, "python"),
                    ignore=shutil.ignore_patterns("__pycache__"))
    for pat in REGIONDATA:
        for p in glob.glob(os.path.join(HERE, "RegionData", pat)):
            copy(p, os.path.join(at3, "RegionData", os.path.basename(p)))
    # Pristine libraries: drop any "(ported" rows the author's install added.
    for p in glob.glob(os.path.join(at3, "RegionData", "proplib_*.csv")):
        lines = open(p, encoding="utf-8-sig").read().splitlines(True)
        open(p, "w", encoding="utf-8").write("".join(l for l in lines if "(ported" not in l))
    for name in PRESETS:
        copy(os.path.join(HERE, "Presets", name + ".json"), os.path.join(at3, "Presets", name + ".json"))
        d = os.path.join(HERE, "Presets", name)
        if os.path.isdir(d):
            for p in glob.glob(os.path.join(d, "*.json")):
                copy(p, os.path.join(at3, "Presets", name, os.path.basename(p)))
    os.makedirs(os.path.join(at3, "PropPlacements"), exist_ok=True)
    os.makedirs(os.path.join(at3, "Presets"), exist_ok=True)

    for p in sorted(glob.glob(os.path.join(ROOT, "ModTools", "*.py"))):
        copy(p, os.path.join(PKG, "ModTools", os.path.basename(p)))

    copy(os.path.join(HERE, "README_RELEASE.txt"), os.path.join(PKG, "README - AT3 v%s.txt" % VERSION))

    # Self-check: the packaged runtime imports every packaged tool.
    py = os.path.join(at3, "python", "python.exe")
    bad = []
    for p in sorted(glob.glob(os.path.join(PKG, "ModTools", "*.py"))):
        m = os.path.splitext(os.path.basename(p))[0]
        r = subprocess.run([py, "-c", "import %s" % m], capture_output=True, text=True,
                           cwd=os.path.join(PKG, "ModTools"))
        err = (r.stderr.strip().splitlines() or [""])[-1]
        if r.returncode and ("ModuleNotFoundError" in err or "ImportError" in err):
            bad.append("%s: %s" % (m, err))
    for root_, dirs, files in os.walk(PKG):
        if "__pycache__" in dirs:
            shutil.rmtree(os.path.join(root_, "__pycache__"))
            dirs.remove("__pycache__")
    if bad:
        sys.exit("REFUSED: packaged tools fail to import:\n  " + "\n  ".join(bad))

    zpath = os.path.join(OUTDIR, NAME + ".zip")
    if os.path.exists(zpath):
        os.remove(zpath)
    n = 0
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for root_, dirs, files in os.walk(PKG):
            rel = os.path.relpath(root_, PKG)
            if not files and not dirs:
                z.writestr(rel.replace(os.sep, "/") + "/", "")
            for f in files:
                z.write(os.path.join(root_, f), os.path.join(rel, f) if rel != "." else f)
                n += 1
    print("packaged %s - %d files, %.1f MB zipped -> %s" % (NAME, n, os.path.getsize(zpath) / 1e6, zpath))


if __name__ == "__main__":
    main()
