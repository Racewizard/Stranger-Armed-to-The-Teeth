r"""Port a geometry into a region so the Prop Editor can place it there.

The Prop Editor's library is proplib_<region>.csv - only what that region
ships. This copies a mesh from whichever region holds it into the TARGET's tgl
(port_to_utility.port, NOT lean: a placement needs its source bundle's
lighting records or it renders impossibly bright), then adds a library row
keyed by the geometry hash, which is what a placement carries at +104.

The tgl is loaded for the whole level, so the row says Zones="*". Lighting is
the tgl's uniform fallback, not the source zone's bake (see "native residency
lights props") - it renders, but may not match the scene around it.

Safety, as build_character: the target blockmap must be consistent BEFORE,
the tgl and blockmap are backed up per port, and anything short of a
consistent, resident result restores both.

    python port_prop_geo.py 01 24AEBFC4
    python port_prop_geo.py 01 24AEBFC4 --dry-run
    python port_prop_geo.py --revert 24AEBFC4 --to 01
"""
import argparse, csv, io, os, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import port_to_utility as PT
import blockmap_add as BA
import build_character as BC
from ensure_asset import region_index
from resolve_assets import harvest
from gamehash import game_hash

ROOT = os.path.dirname(HERE)
REGIONDATA = os.path.join(ROOT, "StrangerAT3", "RegionData")
LIBCOLS = ["Key", "Name", "Asset", "Count", "Bundle", "Zones", "BakedZones"]


def lib_path(region):
    return os.path.join(REGIONDATA, "proplib_%s.csv" % region)


def lib_rows(region):
    p = lib_path(region)
    if not os.path.exists(p):
        return []
    with io.open(p, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def add_lib_row(region, row):
    """Append one row, keeping every existing byte of the file."""
    p = lib_path(region)
    raw = open(p, "rb").read() if os.path.exists(p) else b""
    eol = "\r\n" if (not raw or b"\r\n" in raw) else "\n"
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=LIBCOLS, lineterminator=eol, extrasaction="ignore")
    if not raw:
        w.writeheader()
    w.writerow(row)
    add = buf.getvalue().encode("utf-8")
    if raw and not raw.endswith(eol.encode()):
        add = eol.encode() + add
    with open(p, "ab") as f:
        f.write(add)


def pretty(path):
    b = path.replace("/", "\\").split("\\")[-1]
    b = b[:-4] if b.lower().endswith(".geo") else b
    return " ".join(w.capitalize() for w in b.replace("_", " ").split())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target", nargs="?")
    ap.add_argument("geo", nargs="?")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--revert")
    ap.add_argument("--to")
    a = ap.parse_args()

    if a.revert:
        dest, dreg, dname = PT.dest_for(a.to)
        bm = BA.bm_path(dreg)
        bk = ".propportbak_%s" % a.revert.upper()
        for f in (dest, bm, lib_path(a.to)):
            if os.path.exists(f + bk):
                shutil.copy2(f + bk, f)
                os.remove(f + bk)
        print("REVERTED port of %s into region %s" % (a.revert.upper(), a.to))
        return 0

    if not a.target or not a.geo:
        sys.exit("need: <target region> <geometry hash>")
    tgt, h = a.target, int(a.geo, 16)
    if tgt not in BC.NUMBERED:
        print("REFUSED: %s is not a shipped region" % tgt)
        return 1
    if any(int(r["Key"], 16) == h for r in lib_rows(tgt) if r.get("Key")):
        print("ALREADY %08X is in region %s's library" % (h, tgt))
        return 0

    path = None
    for q in harvest():
        if game_hash(q) == h:
            path = q
            break
    if not path or not path.lower().endswith(".geo"):
        print("REFUSED: %08X is not a geometry record" % h)
        return 1

    t_idx = region_index(tgt)
    src = None if h in t_idx else BC.find_source(h)
    if h not in t_idx and src is None:
        print("REFUSED: %08X is in no numbered region" % h)
        return 1

    dest, dreg, dname = PT.dest_for(tgt)
    bm = BA.bm_path(dreg)
    ok, why = BC.blockmap_consistent(dreg)
    if not ok:
        print("REFUSED: region %s blockmap is not consistent BEFORE the port: %s" % (tgt, why))
        return 1

    row = {"Key": "%08X" % h, "Name": "%s (ported%s)" % (pretty(path), " from " + src if src else ""),
           "Asset": path.replace("/", "\\").split("\\")[-1], "Count": 0,
           "Bundle": dname, "Zones": "*", "BakedZones": "?"}
    print("   geometry %08X %s" % (h, path))
    print("   from     %s" % ("already resident in region " + tgt if src is None else "region " + src))
    if a.dry_run:
        if src:
            PT.port(src, [h], dry=True, lean=False, to=tgt)
        print("   (dry run - nothing written)")
        return 0

    bk = ".propportbak_%08X" % h
    lp = lib_path(tgt)
    for f in (dest, bm) + ((lp,) if os.path.exists(lp) else ()):
        shutil.copy2(f, f + bk)

    def restore(reason):
        print("   FAILED: %s" % reason)
        for f in (dest, bm, lp):
            if os.path.exists(f + bk):
                shutil.copy2(f + bk, f)
                os.remove(f + bk)
        print("   region %s restored - nothing was left behind" % tgt)
        return 1

    if src:
        PT.port(src, [h], dry=False, lean=False, to=tgt)
        if h not in region_index(tgt):
            return restore("the geometry is still not resident in region %s after the port" % tgt)
    ok, why = BC.blockmap_consistent(dreg)
    if not ok:
        return restore("region %s blockmap not consistent after the port: %s" % (tgt, why))
    try:
        add_lib_row(tgt, row)
    except OSError as e:
        return restore("could not add the library row: %s" % e)
    print("   PORTED %08X into region %s as '%s'" % (h, tgt, row["Name"]))
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
