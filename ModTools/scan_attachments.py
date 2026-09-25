"""Find attachment records STRUCTURALLY, not by matching a list of known hashes.

The previous pass searched each .lvl for the hashes of attachment paths found
by the path harvester. That is circular: an attachment whose path string is not
harvestable is invisible, and whole regions came back empty as a result.

Detect the record instead. In the level data an attachment entry looks like:

    <u32 len> <bone name, ASCII, len bytes> <u32 geo hash> <float 1.0>

Anchoring on "a length-prefixed ASCII bone name followed by a dword followed by
1.0f" finds every entry regardless of whether the geometry path is known.

    python scan_attachments.py            # all regions
    python scan_attachments.py 04         # one region, with raw detail
"""
import os, struct, sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gamehash import game_hash
import resolve_assets as RA
import levelprefs as L

BS = chr(92)
ONE = struct.pack("<f", 1.0)


def scan(d):
    """Yield (bone, geohash, offset) for every attachment-shaped record."""
    out = []
    i = 0
    while True:
        i = d.find(ONE, i)
        if i < 0:
            return out
        # geo hash sits immediately before the 1.0f
        gpos = i - 4
        if gpos < 8:
            i += 1
            continue
        # walk back for <u32 len><len ASCII bytes> ending at gpos
        for ln in range(1, 48):
            p = gpos - ln - 4
            if p < 0:
                break
            if struct.unpack_from("<I", d, p)[0] != ln:
                continue
            raw = d[p + 4:p + 4 + ln]
            if not all(32 <= c < 127 for c in raw):
                continue
            # a bone name is a plausible identifier, not arbitrary text
            s = raw.decode()
            if not all(ch.isalnum() or ch == "_" for ch in s):
                continue
            h = struct.unpack_from("<I", d, gpos)[0]
            if h in (0, 0x2DFD1072):
                continue
            out.append((s, h, gpos))
            break
        i += 1


def main():
    paths = RA.harvest()
    known = {}
    for p in paths:
        if p.lower().endswith(".geo"):
            known[game_hash(p)] = p

    regions = sys.argv[1:] or L.REGIONS
    grand = defaultdict(lambda: defaultdict(int))
    for reg in regions:
        fp = L.lvl_path(reg)
        if not os.path.exists(fp):
            continue
        try:
            d = open(fp, "rb").read()
        except OSError:
            print(f"region_{reg}: LOCKED")
            continue
        recs = scan(d)
        bones = defaultdict(lambda: defaultdict(int))
        for bone, h, off in recs:
            nm = known.get(h)
            nm = nm.split(BS)[-1] if nm else f"unknown_{h:08X}"
            bones[bone][nm] += 1
            grand[bone][nm] += 1
        nres = sum(1 for b, h, o in recs if h in known)
        print(f"region_{reg:4} ({L.NAMES.get(reg,''):18}) {len(recs):>4} attachment record(s), "
              f"{nres} resolved, {len(recs)-nres} unknown geometry, {len(bones)} bone(s)")
        if len(regions) == 1:
            for bone in sorted(bones, key=lambda b: -sum(bones[b].values())):
                print(f"\n   BONE {bone}  ({sum(bones[bone].values())})")
                for nm, n in sorted(bones[bone].items(), key=lambda kv: -kv[1]):
                    print(f"      x{n:<4} {nm}")

    if len(regions) > 1:
        print(f"\nbones across all regions: {len(grand)}")
        for bone in sorted(grand, key=lambda b: -sum(grand[b].values())):
            print(f"   {bone:<24} {sum(grand[bone].values()):>5}")


if __name__ == "__main__":
    main()
