r"""Delete whole classes of record from a .lvl, fixing every offset that moves.

A .lvl is  header(20) | record chain | trailer , where the chain is singly
linked by an ABSOLUTE offset at +4 and ends by pointing at a SENTINEL word
that lives at the head of the trailer.  Record length is implied by the next
pointer and is never stored, so deleting a record means every later record
slides and every absolute offset in the file has to move with it.

NEXT is not the only absolute offset.  A stride-1 scan of region_01 finds 188
more dwords whose value is a record offset, clustered at repeated field
positions (+18, +55, +114) and in the level root's tables - far too many, and
far too regular, to be chance: with 29 candidate values over 734 KB the
expected number of accidental matches is about 1e-5.  They are real pointers
and they are NOT all 4-aligned, because the format is byte-packed.  Scanning
at stride 4, as an earlier version did, sees a quarter of them and produces a
file that loads and then crashes.

So this tool:
  * refuses to delete a record that anything points at,
  * rewrites NEXT explicitly,
  * then rescans the WHOLE rebuilt file - header and trailer included - at
    stride 1 and moves every surviving absolute offset,
  * and finally re-walks the result and re-runs the scan to prove no dangling
    offset survived.

    python strip_level.py emptygulch --class 2B9F6678 --dry-run
    python strip_level.py emptygulch --class 2B9F6678
    python strip_level.py emptygulch --revert
"""
import argparse, os, shutil, struct, sys, collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKEN, SENTINEL, CHAIN_START, NEXT, HASHMARK = 0x7A60600D, 0x601307A6, 20, 4, 0x000B4265
PROP = 0x2B9F6678          # InstancedObjectTag
BS = chr(92)


def u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def lvl_path(region):
    return os.path.join(ROOT, "data", "bundles", region, "lm_level_01.lvl")


def walk(d):
    recs, cur, seen = [], CHAIN_START, set()
    while cur + 8 <= len(d) and u32(d, cur) == TOKEN:
        if cur in seen:
            raise ValueError("chain loops at %d" % cur)
        seen.add(cur)
        recs.append(cur)
        cur = u32(d, cur + NEXT)
    return recs, cur


def parse(d):
    """[(off, len, classhash or None)] plus the offset the chain ends at."""
    offs, end = walk(d)
    ext = offs + [end]
    out = []
    for i, o in enumerate(offs):
        c = u32(d, o + 12) if u32(d, o + 8) == HASHMARK else None
        out.append((o, ext[i + 1] - o, c))
    return out, end


def scan(d, wanted, skip):
    """Every position holding a dword in `wanted`, at stride 1. skip = set of positions."""
    hits = collections.defaultdict(list)
    for p in range(0, len(d) - 3):
        if p in skip:
            continue
        v = u32(d, p)
        if v in wanted:
            hits[v].append(p)
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("region")
    ap.add_argument("--class", dest="cls", action="append", default=[],
                    help="8-hex class hash to delete; repeatable")
    ap.add_argument("--prefs-dir", action="append", default=[],
                    help="delete placed objects whose prefs path sits under decorators/<DIR>, e.g. destructible; repeatable")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--revert", action="store_true")
    a = ap.parse_args()

    path = lvl_path(a.region)
    bak = path + ".prestrip"
    if a.revert:
        if not os.path.exists(bak):
            sys.exit("no backup at " + bak)
        shutil.copyfile(bak, path)
        print("reverted from .prestrip")
        return
    if not a.cls and not a.prefs_dir:
        sys.exit("nothing to do: pass --class or --prefs-dir")

    d = open(path, "rb").read()
    rec, end = parse(d)
    print("%s: %d records, %d bytes, chain ends at %08X, trailer %d bytes"
          % (a.region, len(rec), len(d), end, len(d) - end))

    kill = {int(c, 16) for c in a.cls}
    byoff = {o: i for i, (o, l, c) in enumerate(rec)}
    nextpos = {o + NEXT for o, l, c in rec}

    # every absolute offset in the file, other than the NEXT chain itself
    targets = set(byoff) | {end}
    hits = scan(d, targets, nextpos)
    pointed = {byoff[v] for v in hits if v in byoff}
    print("inbound offsets (excl NEXT): %d dwords -> %d distinct targets"
          % (sum(len(v) for v in hits.values()), len(hits)))

    cand = [i for i, (o, l, c) in enumerate(rec) if c in kill]
    if a.prefs_dir:
        # A placed object names its model by PATH HASH at +104. Harvest every
        # path out of the bundles, hash each one, and the category falls out
        # of the directory it sits in - decorators/destructible, /civilized,
        # /foliage, /trees. That is the game's own classification, not ours.
        import resolve_assets as RA
        from gamehash import game_hash
        h2p = {}
        for q in RA.harvest():
            h2p.setdefault(game_hash(q), q)
        want = {x.lower() for x in a.prefs_dir}
        key = BS + "decorators" + BS
        sel = []
        for i, (o, l, c) in enumerate(rec):
            if c != PROP or l <= 108:
                continue
            q = h2p.get(u32(d, o + 104))
            if not q:
                continue
            q = q.replace("/", BS).lower()
            if key in q and q.split(key)[1].split(BS)[0] in want:
                sel.append(i)
        print("prefs-dir %s matched %d placement(s)" % (",".join(a.prefs_dir), len(sel)))
        cand = sorted(set(cand) | set(sel))
    blocked = sorted(set(cand) & pointed)
    doomed = [i for i in cand if i not in pointed]
    print("class match: %d    pointed at (kept): %d    deleting: %d"
          % (len(cand), len(blocked), len(doomed)))
    if blocked:
        print("  kept because something points at them: " +
              ", ".join("#%d@%08X" % (i, rec[i][0]) for i in blocked[:12]) +
              (" ..." if len(blocked) > 12 else ""))

    dead = set(doomed)
    keep = [i for i in range(len(rec)) if i not in dead]
    newoff, pos = {}, CHAIN_START
    for i in keep:
        newoff[rec[i][0]] = pos
        pos += rec[i][1]
    newoff[end] = pos
    print("new size: %d bytes (was %d, -%d)"
          % (pos + len(d) - end, len(d), len(d) - (pos + len(d) - end)))
    if a.dry_run:
        print("dry run, nothing written")
        return

    out = bytearray(d[:CHAIN_START])
    for i in keep:
        o, ln, c = rec[i]
        out += d[o:o + ln]
    out += d[end:]

    # 1. explicit NEXT, because the old NEXT may name a deleted record
    newnext = set()
    for k, i in enumerate(keep):
        here = newoff[rec[i][0]]
        nxt = newoff[rec[keep[k + 1]][0]] if k + 1 < len(keep) else newoff[end]
        struct.pack_into("<I", out, here + NEXT, nxt)
        newnext.add(here + NEXT)

    # 2. move every other absolute offset, stride 1, whole file
    # A 4-byte write starting up to 3 bytes BEFORE a NEXT slot still overwrites
    # part of it. Skipping only the exact slot corrupted the chain at record 1490
    # on the first real remap. Guard the whole overlapping window.
    guard = set()
    for n in newnext:
        guard.update(range(n - 3, n + 4))
    moved = 0
    for p in range(0, len(out) - 3):
        if p in guard:
            continue
        v = u32(out, p)
        if v in newoff and newoff[v] != v:
            struct.pack_into("<I", out, p, newoff[v])
            moved += 1
    print("remapped %d non-NEXT offsets" % moved)

    # 3. prove it
    rec2, end2 = parse(bytes(out))
    ok = len(rec2) == len(keep) and end2 == newoff[end]
    print("re-walk: %d records, ends at %08X  %s"
          % (len(rec2), end2, "OK" if ok else "MISMATCH"))
    if not ok:
        sys.exit("chain did not rebuild cleanly - nothing written")
    live = {o for o, l, c in rec2} | {end2}
    stale = scan(bytes(out), {v for v in newoff.values()} - live, set())
    dang = scan(bytes(out), {rec[i][0] for i in dead} - live, set())
    print("dangling offsets to deleted records: %d" % sum(len(v) for v in dang.values()))
    if dang:
        sys.exit("refusing to write: dangling references remain")

    if not os.path.exists(bak):
        shutil.copyfile(path, bak)
        print("backup -> .prestrip")
    open(path, "wb").write(bytes(out))
    print("wrote %s (%d bytes)" % (path, len(out)))


if __name__ == "__main__":
    main()
