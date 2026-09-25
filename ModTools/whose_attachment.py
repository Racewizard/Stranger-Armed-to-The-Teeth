"""Which character carries a given attachment geometry?

An attachment record sits inside the spawn record of the character wearing it,
so the owner is the nearest spawn anchor at or before the attachment's offset.

    python whose_attachment.py 0A60C227
"""
import csv, os, struct, sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gamehash import game_hash
import levelprefs as L
from scan_attachments import scan

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ANCHOR = bytes([0x72, 0x10, 0xFD, 0x2D, 0, 0, 0, 0, 0x65, 0x42, 0x0B, 0x00, 0x3E, 0x07, 0x16, 0x06])
BS = chr(92)


def spawn_table(d):
    """[(offset_of_type_hash, type_hash)] in file order."""
    out, i = [], 0
    while True:
        i = d.find(ANCHOR, i)
        if i < 0:
            return out
        h = struct.unpack_from("<I", d, i + len(ANCHOR))[0]
        out.append((i + len(ANCHOR), h))
        i += 1


def names():
    """type hash -> character name, from the launcher's catalogue."""
    m = {}
    p = os.path.join(ROOT, "StrangerAT3", "RegionData", "GlobalCatalogue.csv")
    if os.path.exists(p):
        for r in csv.DictReader(open(p, encoding="utf-8-sig")):
            try:
                m[int(r["Hash"], 16)] = r["Name"]
            except (KeyError, ValueError):
                pass
    return m


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    want = {int(a, 16) for a in sys.argv[1:]}
    nm = names()

    owners = defaultdict(lambda: defaultdict(int))
    for reg in L.REGIONS:
        p = L.lvl_path(reg)
        if not os.path.exists(p):
            continue
        try:
            d = open(p, "rb").read()
        except OSError:
            continue
        spawns = spawn_table(d)
        if not spawns:
            continue
        offs = [s[0] for s in spawns]
        for bone, h, off in scan(d):
            if h not in want:
                continue
            # nearest spawn anchor at or before this attachment
            lo, hi = 0, len(offs) - 1
            best = None
            while lo <= hi:
                mid = (lo + hi) // 2
                if offs[mid] <= off:
                    best = mid
                    lo = mid + 1
                else:
                    hi = mid - 1
            if best is None:
                continue
            th = spawns[best][1]
            gap = off - offs[best]
            owners[h][(reg, th, bone)] += 1
            if gap > 4000:      # suspiciously far - flag rather than trust
                owners[h][(reg, th, bone + " (distant)")] += 0

    for h in sorted(want):
        print(f"\n=== {h:08X} ===")
        rows = owners.get(h)
        if not rows:
            print("   no per-spawn occurrences found")
            continue
        tot = sum(rows.values())
        print(f"   {tot} occurrence(s)")
        for (reg, th, bone), n in sorted(rows.items(), key=lambda kv: -kv[1]):
            who = nm.get(th, f"unknown({th:08X})")
            print(f"     region_{reg:4} {who:<28} bone {bone:<22} x{n}")


if __name__ == "__main__":
    main()
