r"""Place a Mechanical (turret, door, lift) into the debug room.

A turret in the world is NOT a character and not an ordinary prop: it is an
`InstancedObjectTag` of class 2B9F6678 - the same container a character spawn
uses - whose PREFS HASH at +228 points at a `\data\prefs\Mechanicals\*.txt`
record. The weapon it fires is named by a region script, not by the placement,
which is why no turret weapon hash appears in any .lvl.

Like utility_spawn.py this clones a placement that works rather than building
one: the donor comes from a region level, and only position, zone, the three
per-instance ids and the chain pointer are rewritten.

The debug room's level has no Mechanical of its own to clone, so the donor is
always cross-region. Its records must already be resident in empty_tag.smb -
port them first, prefs AND geometry.

    python place_mechanical.py --prefs F8D35BDF --pos 0,10,12
    python place_mechanical.py --list
    python place_mechanical.py --revert
"""
import argparse, os, struct, shutil, sys, glob, bisect

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rebuild_bundle as RB
from spawn_prop import (ROOT, SENTINEL, NEXT, CLASS_ID, INST_ID, ROT, POS,
                        TINT, ZONE, walk, u32)

LVL = os.path.join(ROOT, "data", "bundles", "utility", "empty.lvl")
BAK = ".mechbak"
# The prefs hash is the LAST dword of the record, and Mechanical placements come
# in several lengths - 212, 232, 332, 392 all observed. A fixed offset finds only
# one turret type.
def prefs_off(ln):
    return ln - 4
ACTOR_CLASS = 0x2B9F6678


def donors(prefs):
    """Every placement of this prefs hash in any region level."""
    out = []
    for p in sorted(glob.glob(os.path.join(ROOT, "data", "bundles", "**", "*.lvl"), recursive=True)):
        if "utility" in p:
            continue
        d = open(p, "rb").read()
        try:
            recs, end = walk(d)
        except Exception:
            continue
        starts = sorted(recs)
        pat = struct.pack("<I", prefs)
        for i in range(len(d) - 4):
            if d[i:i + 4] != pat:
                continue
            k = bisect.bisect_right(starts, i) - 1
            if k < 0:
                continue
            s = starts[k]
            ln = u32(d, s + NEXT) - s
            if i - s != prefs_off(ln) or u32(d, s + CLASS_ID) != ACTOR_CLASS:
                continue
            out.append((os.path.basename(p), d[s:s + ln]))
    return out


def fresh_ids(d, n):
    used = set()
    recs, _ = walk(d)
    for s in recs:
        for o in (INST_ID, 96, 108):
            used.add(u32(d, s + o))
    out, v = [], 0x00020000
    while len(out) < n:
        if v not in used:
            out.append(v)
            used.add(v)
        v += 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefs", help="Mechanical prefs hash, hex")
    ap.add_argument("--pos", help="x,y,z")
    ap.add_argument("--zone", type=int, default=0)
    ap.add_argument("--index", type=int, default=0,
                    help="which donor placement to clone when several exist; "
                         "they are not interchangeable - some are driven by a "
                         "track or cinematic and never render standalone")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--revert", action="store_true")
    a = ap.parse_args()

    if a.revert:
        if os.path.exists(LVL + BAK):
            shutil.copy2(LVL + BAK, LVL)
            print("empty.lvl restored")
        else:
            print("no %s" % BAK)
        return

    d = bytearray(open(LVL, "rb").read())
    if a.list:
        recs, end = walk(bytes(d))
        for s in recs:
            ln = u32(bytes(d), s + NEXT) - s
            print("   @%-6d len=%-5d class=%08X prefs=%s"
                  % (s, ln, u32(bytes(d), s + CLASS_ID),
                     "%08X" % u32(bytes(d), s + prefs_off(ln)) if ln > 8 else "-"))
        return

    prefs = int(a.prefs, 16)
    found = donors(prefs)
    if not found:
        sys.exit("no placement of prefs %08X in any region level" % prefs)
    if a.index >= len(found):
        sys.exit("only %d donor(s) available" % len(found))
    src, rec = found[a.index]
    rec = bytearray(rec)
    print("donor %d of %d: %s, %d bytes" % (a.index, len(found), src, len(rec)))

    # the records this placement needs must already be in the debug room
    tag = os.path.join(ROOT, "data", "bundles", "utility", "empty", "empty_tag.smb")
    have = {r["hash"] for r in RB.parse(open(tag, "rb").read())[1]}
    if prefs not in have:
        sys.exit("prefs %08X is NOT resident in empty_tag.smb - port it first" % prefs)

    # A PLACEMENT CARRIES ITS OWN DEPENDENCIES, and they are not the shared mesh.
    # +104 is a per-instance copy under \data\instances\<area>\..., and
    # +160/180/200 are that area's lightmap. Porting
    # \data\geometry\mechanicals\<name>.geo is NOT enough - the turret simply
    # does not render. Pull whatever this donor names.
    # scan the WHOLE record for real record hashes rather than fixed offsets -
    # the instance geometry and lightmap slots move with the record length
    known = {}
    for q in glob.glob(os.path.join(ROOT, "data", "bundles", "**", "*.smb"), recursive=True):
        if "bak" in q or "vanilla" in q:
            continue
        try:
            for r in RB.parse(open(q, "rb").read())[1]:
                known.setdefault(r["hash"], os.path.normpath(q).split(os.sep)[2])
        except Exception:
            continue
    refs = {u32(bytes(rec), o) for o in range(0, len(rec) - 4)}
    missing = sorted((refs & set(known)) - have)
    if missing:
        import subprocess
        print("   placement needs %d record(s) not in the debug room: %s"
              % (len(missing), " ".join("%08X" % h for h in missing)))
        reg = known[missing[0]].replace("region_", "")
        rc = subprocess.run([sys.executable, os.path.join(HERE, "port_to_utility.py"),
                             reg] + ["%08X" % h for h in missing] + ["--lean"],
                            capture_output=True, text=True)
        for _ln in rc.stdout.strip().splitlines():
            print("      " + _ln)
        if rc.returncode != 0:
            sys.exit("   porting failed - placement abandoned")

    recs, end = walk(bytes(d))
    last = recs[-1]
    ln = len(rec)
    struct.pack_into("<I", rec, NEXT, end + ln)
    ids = fresh_ids(bytes(d), 3)
    for o, v in zip((INST_ID, 96, 108), ids):
        struct.pack_into("<I", rec, o, v)
    struct.pack_into("<I", rec, ZONE, a.zone)
    x, y, z = (float(v) for v in a.pos.split(","))
    struct.pack_into("<3f", rec, POS, x, y, z)
    out = bytes(d[:end]) + bytes(rec) + bytes(d[end:])
    out = bytearray(out)
    struct.pack_into("<I", out, last + NEXT, end)

    r2, e2 = walk(bytes(out))
    bad = sum(1 for i, s in enumerate(r2)
              if u32(bytes(out), s + NEXT) != (r2[i + 1] if i + 1 < len(r2) else e2))
    ok = (u32(bytes(out), e2) == SENTINEL and bad == 0 and r2 == sorted(r2))
    print("   placed at (%.2f, %.2f, %.2f) zone %d, ids %08X/%08X/%08X"
          % (x, y, z, a.zone, *ids))
    print("   chain: %d records, %d non-contiguous, terminator %08X -> %s"
          % (len(r2), bad, u32(bytes(out), e2), "OK" if ok else "BROKEN"))
    if not ok:
        print("   NOT WRITTEN")
        return
    if not os.path.exists(LVL + BAK):
        shutil.copy2(LVL, LVL + BAK)
    open(LVL, "wb").write(bytes(out))


if __name__ == "__main__":
    main()
