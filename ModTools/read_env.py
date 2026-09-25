r"""Print a region's LIVE environment values, as the Ambience Config shows them.

The Ambience tables used to be filled from env_<id>.csv / envregion_<id>.csv,
which are VANILLA snapshots - so the window always showed vanilla, even over a
modded level, and setting a value back to vanilla wrote nothing because it
"matched". This reads the .lvl the game actually loads.

Output is CSV on stdout - Field,SetIndex,Value - with values formatted exactly
as the vanilla CSVs format them, so the launcher can compare strings:

    fog fields (fogColor, fogStart, fogEnd) for every set (area)
    every region-level field (set 0)

    python read_env.py 01
"""
import csv, sys

import levelprefs as L

FOG = ("fogColor", "fogStart", "fogEnd")


def fmt(v):
    if isinstance(v, tuple):
        return ", ".join(repr(x) for x in v)
    return str(v)


def main():
    if len(sys.argv) != 2:
        sys.exit("usage: read_env.py <region>")
    d = open(L.lvl_path(sys.argv[1]), "rb").read()
    aa = L.anchors(d)
    if not aa:
        sys.exit("no LevelPrefs anchor in region_%s" % sys.argv[1])
    w = csv.writer(sys.stdout, lineterminator="\n")
    w.writerow(["Field", "SetIndex", "Value"])
    for i, c in enumerate(aa):
        for f in FOG:
            off, kind, _ = L.FIELDS[f]
            w.writerow([f, i, fmt(L.read_field(d, c, off, kind))])
    for f, (off, kind, region_only) in L.FIELDS.items():
        if f in FOG:
            continue
        w.writerow([f, 0, fmt(L.read_field(d, aa[0], off, kind))])


if __name__ == "__main__":
    main()
