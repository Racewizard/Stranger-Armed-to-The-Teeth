r"""Create NEW character spawns in a region, rather than replacing existing ones.

Character spawns turn out to be the SAME record type as props: entries in the
.lvl's linked list, class 2B9F6678, differing only in which fields are filled
in. So this works exactly like place_props.py - see OBJECT_SPAWNING.md for the
container format - with one extra field to set.

    record +16   instance id        per instance, unique
           +20   zone index
           +25   3x3 rotation
           +61   translation
           +77   baked lighting tint
           +92   job hash           mirrored at +195; 2DFD1072 = no job
           +96   second id          per instance, unique
           +108  third id           per instance, unique
           +128  CHARACTER TYPE     <- what makes it a spawn rather than a prop

Every field above except the type is per-instance and gets fresh values; the
rest of the record is copied verbatim from a donor of the same type, so any
AI/loadout wiring that lives elsewhere in the record comes along untouched.

DONOR CHOICE MATTERS. 19 of region_01's 32 outlaw_shooter spawns carry a null
job (2DFD1072) and the rest are wired to a specific job script. Cloning a
job-carrying spawn would duplicate that wiring and put two characters on one
job, so this prefers a null-job donor and says so when none exists.

    python spawn_char.py 01 --list
    python spawn_char.py 01 --char FFFC00CB --pos 47,92,38.2 --yaw 90
    python spawn_char.py 01 --char FFFC00CB --site test --count 3
    python spawn_char.py 01 --revert
"""
import argparse, math, os, shutil, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from whose_attachment import spawn_table
from spawn_prop import (ROOT, TOKEN, SENTINEL, CHAIN_START, NEXT, CLASS_ID,
                        INST_ID, ROT, POS, ONE, TINT, NAME2, ZONE,
                        lvl_path, u32, walk, pos_of, read_marker)
from place_props import matrix_from_euler, zone_at

BAK = ".charbak"
TYPE_OFF = 128          # character type hash
JOB_OFF = 92            # job hash, mirrored at +195
JOB_MIRROR = 195
ID3_OFF = 108           # third per-instance id
NULL_ID = 0x2DFD1072
ACTOR_CLASS = 0x2B9F6678


def catalogue(region):
    """{hash: name} from the launcher's pre-built region catalogue, if present."""
    out = {}
    p = os.path.join(ROOT, "StrangerAT3", "RegionData", "catalogue_%s.csv" % region)
    if not os.path.exists(p):
        return out
    import csv
    with open(p, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            try:
                out[int(r["Hash"], 16)] = r.get("Name") or ""
            except (ValueError, KeyError, TypeError):
                pass
    return out


def spawn_records(d, recs):
    """[(offset, length, type hash, job hash)] for every character spawn.

    Anchored on spawn_table(), the enumerator the earlier spawn work was built
    on, rather than on "does +128 look like a hash". Guessing from the field
    alone finds 386 records in region_01 against a true 148: plenty of props
    carry something hash-shaped at that offset.
    """
    import bisect
    starts = sorted(recs)
    out = []
    for off, _h in spawn_table(bytes(d)):
        i = bisect.bisect_right(starts, off) - 1
        if i < 0:
            continue
        s = starts[i]
        e = u32(d, s + NEXT)
        if not (s <= off < e):
            continue
        if e - s < TYPE_OFF + 4:
            continue
        out.append((s, e - s, u32(d, s + TYPE_OFF), u32(d, s + JOB_OFF)))
    return out


def pick_donor(spawns, want):
    """Prefer a null-job donor: cloning a job-wired spawn duplicates the wiring."""
    same = [r for r in spawns if r[2] == want]
    if not same:
        return None, "no existing spawn of that character in this region"
    free = [r for r in same if r[3] == NULL_ID]
    if free:
        # the most common length among null-job donors, to avoid an oddity
        lens = {}
        for r in free:
            lens.setdefault(r[1], []).append(r)
        best = max(lens, key=lambda n: len(lens[n]))
        return lens[best][0], "null-job donor (%d of %d available)" % (len(free), len(same))
    return same[0], ("WARNING: every donor carries a job (%08X) - the clone will "
                     "share it" % same[0][3])


def fresh_ids(d, used, n):
    out = []
    cand = 0xB1C40001
    while len(out) < n:
        if d.find(struct.pack("<I", cand)) < 0 and cand not in used:
            out.append(cand)
            used.add(cand)
        cand += 1
    return out


def insert(d, recs, donor, dlen, place, rec):
    """Splice `rec` in at `place`, shifting the rest and fixing every pointer."""
    src = bytes(d)
    out = bytearray(src[:place]) + rec + bytearray(src[place:])
    for s in recs:
        moved = s if s < place else s + dlen
        v = u32(src, s + NEXT)
        struct.pack_into("<I", out, moved + NEXT, v if v < place else v + dlen)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("region")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--char", help="character type hash, hex")
    ap.add_argument("--csv", help="batch: Char,X,Y,Z,Yaw per row")
    ap.add_argument("--pos", help="x,y,z")
    ap.add_argument("--site", help="name from positions.txt")
    ap.add_argument("--yaw", type=float, default=0.0)
    ap.add_argument("--count", type=int, default=1)
    ap.add_argument("--spread", type=float, default=2.5,
                    help="metres between multiple spawns")
    ap.add_argument("--fresh-ids", action="store_true",
                    help="mint new values for +16/+96/+108. OFF by default: "
                         "+16 is the spawn's TAG hash, not a free-form id, and "
                         "the props that verifiably appeared in game were "
                         "cloned with their ids left verbatim.")
    ap.add_argument("--base", help="rebuild from this file instead of the backup")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--revert", action="store_true")
    a = ap.parse_args()
    p = lvl_path(a.region)

    if a.revert:
        if os.path.exists(p + BAK):
            shutil.copy2(p + BAK, p)
            print("reverted lm_level_%s.lvl" % a.region)
        else:
            print("nothing to revert - no %s" % BAK)
        return

    if not os.path.exists(p + BAK):
        shutil.copy2(p, p + BAK)
    base_path = a.base if (a.base and os.path.exists(a.base)) else p + BAK
    src = open(base_path, "rb").read()
    d = bytearray(src)
    recs, end = walk(bytes(d))
    spawns = spawn_records(bytes(d), recs)
    names = catalogue(a.region)

    if a.list or not (a.char or a.csv):
        counts = {}
        for s, ln, t, job in spawns:
            c = counts.setdefault(t, {"n": 0, "free": 0, "len": ln})
            c["n"] += 1
            if job == NULL_ID:
                c["free"] += 1
        print("region_%s: %d character spawn(s), %d type(s)\n" % (a.region, len(spawns), len(counts)))
        print("   %-10s %-26s %6s %10s %6s" % ("hash", "name", "spawns", "null-job", "bytes"))
        for t, c in sorted(counts.items(), key=lambda kv: -kv[1]["n"]):
            print("   %08X   %-26s %6d %10d %6d"
                  % (t, names.get(t, "?")[:26], c["n"], c["free"], c["len"]))
        if not a.list:
            print("\npick one with --char <hash>")
        return

    if a.csv:
        import csv as _csv
        if not os.path.exists(a.csv):
            # No list means no characters - rebuild the base so a removed row
            # actually disappears instead of lingering from a previous launch.
            open(p, "wb").write(src)
            print("no character file: %s - level left as the base" % a.csv)
            return
        rows = []
        with open(a.csv, newline="", encoding="utf-8-sig") as f:
            for ln, r in enumerate(_csv.DictReader(f), 2):
                h = (r.get("Char") or "").strip()
                if not h:
                    continue
                try:
                    rows.append((int(h, 16), float(r.get("X") or 0), float(r.get("Y") or 0),
                                 float(r.get("Z") or 0), float(r.get("Yaw") or 0)))
                except ValueError:
                    print("  line %d: unreadable row - skipped" % ln)
        print("region_%s: %d character placement(s)" % (a.region, len(rows)))
        done = 0
        for want_h, cx, cy, cz, cyaw in rows:
            recs, end = walk(bytes(d))
            sp = spawn_records(bytes(d), recs)
            dr, why = pick_donor(sp, want_h)
            if dr is None:
                print("  %08X: %s - skipped" % (want_h, why))
                continue
            dn, dln = dr[0], dr[1]
            target = (cx, cy, cz)
            zone, votes = zone_at(bytes(d), recs, target)
            if zone is None:
                print("  %08X: no zone at that point - skipped" % want_h)
                continue
            nearest, best = None, None
            for sx in recs:
                q = pos_of(bytes(d), sx)
                if q is None:
                    continue
                dd = math.dist(q, target)
                if best is None or dd < best:
                    nearest, best = sx, dd
            place = u32(bytes(d), nearest + NEXT)
            rec = bytearray(d[dn:dn + dln])
            struct.pack_into("<I", rec, NEXT, place + dln)
            struct.pack_into("<I", rec, ZONE, zone)
            struct.pack_into("<I", rec, TYPE_OFF, want_h)
            for k, v in enumerate(matrix_from_euler(cyaw, 0.0, 0.0)):
                struct.pack_into("<f", rec, ROT + 4 * k, v)
            for k, v in enumerate(target):
                struct.pack_into("<f", rec, POS + 4 * k, v)
            if u32(bytes(d), nearest + NEXT) - nearest > TINT + 4:
                rec[TINT:TINT + 4] = d[nearest + TINT:nearest + TINT + 4]
            d = insert(d, recs, dn, dln, place, rec)
            struct.pack_into("<I", d, nearest + NEXT, place)
            done += 1
            print("  %08X %-22s (%8.2f,%8.2f,%7.2f) yaw %6.1f zone %d"
                  % (want_h, names.get(want_h, "?")[:22], cx, cy, cz, cyaw, zone))
        open(p, "wb").write(bytes(d))
        chk = open(p, "rb").read()
        r2, e2 = walk(chk)
        bad = sum(1 for i, sx in enumerate(r2)
                  if u32(chk, sx + NEXT) != (r2[i + 1] if i + 1 < len(r2) else e2))
        ok = (u32(chk, e2) == SENTINEL and bad == 0 and r2 == sorted(r2))
        print("")
        print("%d applied. chain: %d records, %d non-contiguous -> %s"
              % (done, len(r2), bad, "OK" if ok else "BROKEN"))
        if not ok:
            open(p, "wb").write(src)
            print("chain did not verify - reverted to the base")
        return

    want = int(a.char, 16)
    donor_rec, why = pick_donor(spawns, want)
    if donor_rec is None:
        sys.exit("%s: %s" % (a.char, why))
    donor, dlen, dtype, djob = donor_rec
    print("region_%s: %d records, %d spawns" % (a.region, len(recs), len(spawns)))
    print("character %08X (%s)" % (want, names.get(want, "?")))
    print("donor @%d, %d bytes - %s" % (donor, dlen, why))

    if a.site:
        hit = read_marker(a.site)
        if hit is None:
            sys.exit("marker %r not found" % a.site)
        x, y, z = hit[0], hit[1], hit[2]
        print("site %r: (%.2f, %.2f, %.2f)" % (a.site, x, y, z))
    elif a.pos:
        x, y, z = (float(v) for v in a.pos.split(","))
    else:
        sys.exit("need --pos x,y,z or --site NAME")

    used = set()
    placed = 0
    for i in range(max(1, a.count)):
        recs, end = walk(bytes(d))
        # the donor shifts as earlier clones are inserted; re-find it by type
        cur = [r for r in spawn_records(bytes(d), recs) if r[2] == want and r[1] == dlen]
        if not cur:
            print("  donor lost after %d insert(s)" % placed)
            break
        donor = cur[0][0]

        # ring the extras out so they do not stand inside one another
        if i == 0:
            tx, ty = x, y
        else:
            ang = 2.0 * math.pi * (i - 1) / max(1, a.count - 1)
            tx = x + a.spread * math.cos(ang)
            ty = y + a.spread * math.sin(ang)
        target = (tx, ty, z)

        zone, votes = zone_at(bytes(d), recs, target)
        if zone is None:
            print("  cannot determine a zone - skipped")
            break

        nearest, best = None, None
        for s in recs:
            q = pos_of(bytes(d), s)
            if q is None:
                continue
            dd = math.dist(q, target)
            if best is None or dd < best:
                nearest, best = s, dd
        place = u32(bytes(d), nearest + NEXT)

        rec = bytearray(d[donor:donor + dlen])
        struct.pack_into("<I", rec, NEXT, place + dlen)
        if a.fresh_ids:
            ids = fresh_ids(bytes(d), used, 3)
            struct.pack_into("<I", rec, INST_ID, ids[0])
            struct.pack_into("<I", rec, NAME2, ids[1])
            struct.pack_into("<I", rec, ID3_OFF, ids[2])
        else:
            ids = (u32(bytes(rec), INST_ID), u32(bytes(rec), NAME2),
                   u32(bytes(rec), ID3_OFF))
        struct.pack_into("<I", rec, ZONE, zone)
        struct.pack_into("<I", rec, TYPE_OFF, want)
        for k, v in enumerate(matrix_from_euler(a.yaw, 0.0, 0.0)):
            struct.pack_into("<f", rec, ROT + 4 * k, v)
        for k, v in enumerate(target):
            struct.pack_into("<f", rec, POS + 4 * k, v)
        if u32(bytes(d), nearest + NEXT) - nearest > TINT + 4:
            rec[TINT:TINT + 4] = d[nearest + TINT:nearest + TINT + 4]

        d = insert(d, recs, donor, dlen, place, rec)
        struct.pack_into("<I", d, nearest + NEXT, place)
        placed += 1
        print("  spawn %d: (%8.2f,%8.2f,%7.2f) yaw %5.1f  zone %-3d (%d/12)  ids %08X/%08X/%08X %s"
              % (placed, tx, ty, z, a.yaw, zone, votes, ids[0], ids[1], ids[2],
                 "fresh" if a.fresh_ids else "verbatim"))

    if a.check:
        print("\ncheck only - nothing written")
        return
    open(p, "wb").write(bytes(d))

    chk = open(p, "rb").read()
    r2, e2 = walk(chk)
    bad = sum(1 for i, s in enumerate(r2)
              if u32(chk, s + NEXT) != (r2[i + 1] if i + 1 < len(r2) else e2))
    ok = (u32(chk, e2) == SENTINEL and bad == 0 and r2 == sorted(r2))
    sp2 = spawn_records(chk, r2)
    print("\n%d spawn(s) added. chain: %d records, %d non-contiguous, terminator %08X -> %s"
          % (placed, len(r2), bad, u32(chk, e2), "OK" if ok else "BROKEN"))
    print("character spawns: %d -> %d" % (len(spawns), len(sp2)))
    if not ok:
        shutil.copy2(p + BAK, p)
        print("chain did not verify - reverted, nothing applied")


if __name__ == "__main__":
    main()
