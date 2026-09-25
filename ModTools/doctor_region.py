r"""Cross-check the four things that must agree about a region's bundles.

A region names its 175 bundles in FOUR independent places:

    1. the bundle subfolder on disk
    2. lm_level_01_blockmap.smh   - group headers, each holding a full path
    3. lm_level_01_blockmap.txt   - "normal:/cinematic:/zone:" lines
    4. lm_level_01.sbl            - the streaming list

Nothing in the toolchain made them agree, and they can disagree silently.
Copying region_01 to emptygulch and then renaming the bundle subfolder
lm_level_01 -> lm_level_0 (done so the .smh group paths keep their vanilla
length) updated 1, 2 and 4 but not 3, leaving all 175 paths in the .txt
pointing at a folder that no longer existed.  The level loaded and then
crashed, and because the crash arrived one edit later it was blamed on that
edit instead.  A stale manifest does not announce itself: check_groups still
said "consistent", because the .smh really was fine.

The lesson is that the useful check is not "is each file valid" but "do the
files agree with each other", so that is what this does.

Asset paths are deliberately NOT disk-checked.  \data\levels\... and
\data\textures\... live inside bundles - data/levels does not exist as a
directory at all - so "absent from disk" is normal for them and means nothing.
Only bundle paths, which are real loose files, are resolved.

    python doctor_region.py emptygulch
    python doctor_region.py region_01
"""
import argparse, os, re, struct, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BS = chr(92)
MAGIC = 0x3A4B5C6D


def norm(s):
    return os.path.join(ROOT, s.strip().lstrip("/" + BS).replace(BS, "/"))


def find_subdir(rdir):
    subs = [d for d in os.listdir(rdir) if os.path.isdir(os.path.join(rdir, d))]
    if len(subs) != 1:
        sys.exit("expected exactly one bundle subfolder in %s, found %r" % (rdir, subs))
    return subs[0]


def smh_paths(p):
    d = open(p, "rb").read()
    out, o = [], 0
    key = struct.pack("<I", MAGIC)
    while True:
        i = d.find(key, o)
        if i < 0:
            break
        pl = struct.unpack_from("<I", d, i + 8)[0]
        if 4 <= pl <= 300 and i + 12 + pl <= len(d):
            s = d[i + 12:i + 12 + pl].rstrip(b"\0")
            if all(32 <= c < 127 for c in s):
                out.append(s.decode("latin1"))
        o = i + 4
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("region")
    a = ap.parse_args()

    rdir = os.path.join(ROOT, "data", "bundles", a.region)
    if not os.path.isdir(rdir):
        sys.exit("no such region: " + rdir)
    sub = find_subdir(rdir)
    bdir = os.path.join(rdir, sub)
    stem = "lm_level_01"
    smh = os.path.join(rdir, stem + "_blockmap.smh")
    txt = os.path.join(rdir, stem + "_blockmap.txt")
    sbl = os.path.join(rdir, stem + ".sbl")
    lvl = os.path.join(rdir, stem + ".lvl")

    print("region %s   bundle subfolder %s" % (a.region, sub))
    bad = 0

    # ---- 1. disk
    disk = {f for f in os.listdir(bdir) if f.lower().endswith(".smb")}
    print("  disk            : %d .smb" % len(disk))

    # ---- 2. .smh group paths
    gp = smh_paths(smh)
    gnames = {os.path.basename(x.replace(BS, "/")) for x in gp}
    gdirs = {os.path.dirname(x.replace(BS, "/")).lower() for x in gp}
    print("  blockmap.smh    : %d groups, %d distinct dirs" % (len(gp), len(gdirs)))

    # ---- 3. .txt bundle paths
    rx = re.compile("[/" + BS + BS + "]data[/" + BS + BS + "]bundles[^ \t\r\n]+" + BS + BS + "?[^ \t\r\n]*?" + r"\.smb", re.I)
    rx = re.compile("[/" + BS + BS + "]data[/" + BS + BS + r"]bundles[^ \t\r\n]+\.smb", re.I)
    t = open(txt, "rb").read().decode("latin1")
    tp = [m.group(0) for m in rx.finditer(t)]
    tnames = {os.path.basename(x.replace(BS, "/")) for x in tp}
    print("  blockmap.txt    : %d bundle paths" % len(tp))

    # ---- 4. .sbl bundle lines
    sl = [l.strip() for l in open(sbl, "rb").read().decode("latin1").splitlines() if l.strip()]
    sp = [l for l in sl if l.lower().endswith(".smb") and "bundles" in l.lower()]
    snames = {os.path.basename(x.replace(BS, "/")) for x in sp}
    print("  streaming .sbl  : %d lines, %d bundle refs" % (len(sl), len(sp)))

    # ---- agreement
    print()
    for label, s in (("blockmap.smh", gnames), ("blockmap.txt", tnames), (".sbl", snames)):
        miss, extra = disk - s, s - disk
        if miss or extra:
            bad += 1
            print("  MISMATCH %s vs disk: %d absent, %d unknown" % (label, len(miss), len(extra)))
            for x in sorted(miss)[:4]:
                print("      not listed:", x)
            for x in sorted(extra)[:4]:
                print("      not on disk:", x)
        else:
            print("  OK  %-14s names match disk exactly" % label)

    # ---- do the listed paths actually resolve?
    print()
    for label, paths in (("blockmap.smh", gp), ("blockmap.txt", tp), (".sbl", sp)):
        miss = [x for x in paths if not os.path.exists(norm(x))]
        if miss:
            bad += 1
            print("  BROKEN PATHS %s: %d of %d do not resolve" % (label, len(miss), len(paths)))
            for x in miss[:3]:
                print("      ", x)
        else:
            print("  OK  %-14s all %d paths resolve on disk" % (label, len(paths)))

    # ---- WHICH region do the paths point into?  Resolving is not enough:
    # emptygulch loaded successfully with a .smh whose 175 group paths all named
    # the region_01 bundle folder, so they resolved on disk while naming another
    # region entirely.  Whether that means the paths are inert labels or means
    # the game quietly loaded region_01's bundles is UNRESOLVED - and it decides
    # whether this region's own bundles are live or dead weight.  Report, do not fail.
    print()
    for label, paths in (("blockmap.smh", gp), ("blockmap.txt", tp), (".sbl", sp)):
        regs = set()
        for x in paths:
            q = x.replace(BS, "/").lower().split("/data/bundles/")
            if len(q) > 1:
                regs.add(q[1].split("/")[0])
        tag = "own region" if regs == {a.region.lower()} else "POINTS AT %s" % sorted(regs)
        print("  %-14s -> %s" % (label, tag))

    # ---- non-bundle .sbl entries (audio etc): compare, do not fail
    other = [l for l in sl if l not in sp]
    om = [x for x in other if not os.path.exists(norm(x))]
    print("\n  .sbl non-bundle entries: %d, of which %d absent%s"
          % (len(other), len(om), " (legacy .xwb, normal)" if all(x.lower().endswith(".xwb") for x in om) else " <-- CHECK"))
    if om and not all(x.lower().endswith(".xwb") for x in om):
        bad += 1
        for x in om[:5]:
            print("      ", x)

    # ---- level chain
    d = open(lvl, "rb").read()
    TOKEN, SENT, START = 0x7A60600D, 0x601307A6, 20
    cur, n, seen = START, 0, set()
    while cur + 8 <= len(d) and struct.unpack_from("<I", d, cur)[0] == TOKEN:
        if cur in seen:
            break
        seen.add(cur)
        n += 1
        cur = struct.unpack_from("<I", d, cur + 4)[0]
    term = struct.unpack_from("<I", d, cur)[0] if cur + 4 <= len(d) else 0
    good = term == SENT
    if not good:
        bad += 1
    print("  level chain     : %d records, terminator %08X %s" % (n, term, "OK" if good else "BAD"))

    print()
    print("  ==> %s" % ("HEALTHY" if bad == 0 else "%d PROBLEM(S)" % bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
