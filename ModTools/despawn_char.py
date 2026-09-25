r"""Remove character spawns from a region's .lvl - the exact inverse of spawn_char.

The .lvl chain is CONTIGUOUS, not a free list: every record's NEXT holds the
offset of the record physically after it, the whole chain is in ascending order,
and it ends at a SENTINEL. So a spawn cannot be unlinked and left in place -
its bytes must come out and every pointer past it must move down by its length,
mirroring spawn_char.insert().

Verified the same way spawn_char verifies an insert: walk the chain, require
every NEXT to equal the following record's offset, require ascending order and
the terminator. If any of that fails the file is restored and nothing is applied.

    python despawn_char.py 01 EDFB19EF --check
    python despawn_char.py 01 EDFB19EF
    python despawn_char.py 01 --revert
"""
import argparse, os, shutil, struct, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from spawn_prop import (ROOT, SENTINEL, NEXT, POS, lvl_path, u32, walk)
from spawn_char import spawn_records

BAK = ".despawnbak"


def region_lvl(region):
    if region == "utility":
        return os.path.join(ROOT, "data", "bundles", "utility", "empty.lvl")
    return lvl_path(region)


def remove(d, recs, off, ln):
    """Cut the record at `off` and fix every pointer, mirroring insert()."""
    src = bytes(d)
    out = bytearray(src[:off]) + bytearray(src[off + ln:])
    for s in recs:
        if s == off:
            continue
        moved = s if s < off else s - ln
        v = u32(src, s + NEXT)
        struct.pack_into("<I", out, moved + NEXT, v if v <= off else v - ln)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("region")
    ap.add_argument("chars", nargs="*", help="character type hashes, hex")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--revert", action="store_true")
    a = ap.parse_args()

    p = region_lvl(a.region)
    if a.revert:
        if os.path.exists(p + BAK):
            shutil.copy2(p + BAK, p)
            print("restored %s" % os.path.basename(p))
        else:
            print("no %s to restore" % BAK)
        return

    want = {int(c, 16) for c in a.chars}
    d = bytearray(open(p, "rb").read())
    before = len(spawn_records(bytes(d), walk(bytes(d))[0]))
    removed = 0
    while True:
        recs, end = walk(bytes(d))
        hit = next(((o, ln, t) for o, ln, t, job in spawn_records(bytes(d), recs)
                    if t in want), None)
        if hit is None:
            break
        off, ln, t = hit
        x, y, z = struct.unpack_from("<3f", bytes(d), off + POS)
        print("  removing %08X at (%.2f, %.2f, %.2f)  %d bytes at +%d" % (t, x, y, z, ln, off))
        d = remove(d, recs, off, ln)
        removed += 1

    recs, end = walk(bytes(d))
    bad = sum(1 for i, s in enumerate(recs)
              if u32(bytes(d), s + NEXT) != (recs[i + 1] if i + 1 < len(recs) else end))
    ok = (u32(bytes(d), end) == SENTINEL and bad == 0 and recs == sorted(recs))
    after = len(spawn_records(bytes(d), recs))
    print("  %d removed. chain: %d records, %d non-contiguous, terminator %08X -> %s"
          % (removed, len(recs), bad, u32(bytes(d), end), "OK" if ok else "BROKEN"))
    print("  character spawns: %d -> %d" % (before, after))
    if not ok:
        print("  chain did not verify - NOTHING WRITTEN")
        return
    if a.check:
        print("  check only - nothing written")
        return
    if removed and not os.path.exists(p + BAK):
        shutil.copy2(p, p + BAK)
    if removed:
        open(p, "wb").write(bytes(d))


if __name__ == "__main__":
    main()
