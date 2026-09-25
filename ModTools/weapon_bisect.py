r"""Binary-search which byte runs carry a weapon's behaviour.

Six single-field edits to McGee's rifle (+16 range, +20 arcAngle, +46 speed,
+72 pitchClamp, +76 maxLeadVel, +228) all did NOTHING, while pasting the outlaw
mortar's whole descriptor DID change the trajectory. So the field that matters
is real but is not one we have named - the named block is inert for firearms.

Rather than keep guessing, diff the two records into runs of differing bytes and
bisect: apply half the runs, test, halve again. 32 runs is at most 5 launches.

The effect pref at +12 is EXCLUDED from every paste - it selects the projectile
mesh and the sounds, and the whole point is to keep McGee's while changing how
the shot flies.

    python weapon_bisect.py --list
    python weapon_bisect.py --apply 0-15
    python weapon_bisect.py --apply 0-7,20
    python weapon_bisect.py --revert
"""
import argparse, glob, os, shutil, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rebuild_bundle as RB

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TGT = os.path.join(ROOT, "data/bundles/region_01/lm_level_01/lm_level_01_tgl.smb".replace("/", os.sep))
FLAT, ARC = 0xC8F313D2, 0x5D994255        # McGee (flat)  /  outlawMortar (up)
KEEP = set(range(12, 16))                 # effectPref - never paste over it
BAK = ".bisectbak"


def find(h, pat):
    for p in glob.glob(os.path.join(ROOT, pat)):
        try:
            recs = RB.parse(open(p, "rb").read())[1]
        except (Exception, SystemExit):
            continue
        for r in recs:
            if r["hash"] == h:
                return r
    return None


def runs():
    a = find(FLAT, "data/bundles/region_03/lm_level_03/*.smb")["desc"]   # pristine
    b = find(ARC, "data/bundles/region_02/lm_level_02/*.smb")["desc"]
    d = [i for i in range(min(len(a), len(b))) if a[i] != b[i] and i not in KEEP]
    out = []
    for i in d:
        if out and i == out[-1][1] + 1:
            out[-1][1] = i
        else:
            out.append([i, i])
    return a, b, out


def parse_sel(s, n):
    sel = set()
    for part in s.split(","):
        if "-" in part:
            lo, hi = part.split("-")
            sel.update(range(int(lo), int(hi) + 1))
        else:
            sel.add(int(part))
    return {i for i in sel if 0 <= i < n}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--apply")
    ap.add_argument("--revert", action="store_true")
    a = ap.parse_args()
    flat, arc, rr = runs()

    if a.revert:
        if os.path.exists(TGT + BAK):
            shutil.copyfile(TGT + BAK, TGT)
            print("reverted from" + BAK)
        return
    if a.list or not a.apply:
        print("%d differing runs between McGee (flat) and outlawMortar (up):" % len(rr))
        for i, (s, e) in enumerate(rr):
            fa = struct.unpack_from("<f", flat, s)[0] if s + 4 <= len(flat) else 0
            fb = struct.unpack_from("<f", arc, s)[0] if s + 4 <= len(arc) else 0
            print("  [%2d] +%-4d..%-4d  %-10.6g -> %-10.6g" % (i, s, e, fa, fb))
        return

    sel = parse_sel(a.apply, len(rr))
    raw = open(TGT, "rb").read()
    hdr, recs, v, off = RB.parse(raw)
    probe, _ = RB.build(hdr, recs, v, off, len(raw))
    if probe != raw:
        sys.exit("rebuild not lossless - refusing")
    r = [x for x in recs if x["hash"] == FLAT][0]
    d = bytearray(flat)                    # always start from pristine McGee
    for i in sorted(sel):
        s, e = rr[i]
        d[s:e + 1] = arc[s:e + 1]
    r["desc"] = bytes(d)
    print("applied %d of %d runs: %s" % (len(sel), len(rr), sorted(sel)))
    print("  effectPref +12 = %08X (McGee's, preserved)" % struct.unpack_from("<I", d, 12)[0])
    if not os.path.exists(TGT + BAK):
        shutil.copyfile(TGT, TGT + BAK)
    out, _ = RB.build(hdr, recs, v, off, len(raw))
    open(TGT, "wb").write(out)
    print("  wrote %d bytes" % len(out))


if __name__ == "__main__":
    main()
