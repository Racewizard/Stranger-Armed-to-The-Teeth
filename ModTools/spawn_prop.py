r"""Create a NEW object placement in a region .lvl.

A .lvl is a singly-linked list of variable-length object records, byte-packed
and unaligned. The loader (stranger.exe 0x641590) reads a token, reads the next
pointer, constructs the class, deserialises, seeks to next, and repeats until
the token stops matching - so record length is implied by the next pointer and
is never stored.

    record:  +0   u32 token 0x7A60600D
             +4   u32 ABSOLUTE offset of the next record
             +8   u32 0x000B4265 - marker meaning "class name is a hash".
                  Any other value is a string LENGTH and the name follows inline
                  (stranger.exe 0x610710).
             +12  u32 class name hash
             +16  u32 instance id
             +20  u32 ZONE INDEX          <- see below, this one matters
             +25  3x3 rotation, row-major
             +61  translation, three floats
             +73  f32 1.0  (reliable layout sentinel)
             +77  RGBA baked tint
             +96  u32 second instance id, or 2DFD1072 for none
             +104 u32 prefs/geometry hash
    the chain ends when next points at 0x601307A6 instead of a token

TWO THINGS DECIDE WHETHER A NEW OBJECT ACTUALLY APPEARS.

1. The zone index at +20 must match where the object stands. It is not
   cosmetic: an object whose zone disagrees with its position is registered to
   that other zone and never streams in at its location. Cloning a donor from
   elsewhere and keeping its zone is the single easiest way to produce a record
   that is perfectly valid and completely invisible. --zone auto reads the zone
   off the records already standing at the target, which is what you want.

2. The geometry has to be resident. Zone bundles are listed in
   <level>_blockmap.txt, and zonedep[zone] gives the bundle indices that zone
   loads. Assets under \data\instances\<area>\... live in that area's zone
   bundle and only render where it is loaded. Assets in the "normal" bundle
   (lm_level_01_tgl.smb) are not zone-gated at all - the treasure chest
   (\data\geometry\Collectables\civilized_treasure_chest.geo) is one of
   those, so it can go anywhere.

--mode insert opens a gap at a record boundary beside the target's nearest
neighbour and shifts the rest of the chain along, fixing every next pointer.
next is the only real pointer in the file, so that is complete. The file grows;
there is no size constraint. The other two modes are kept only because they
document what does NOT work: --mode append leaves the record chain-distant from
its neighbours, and --mode spatial costs a backward next pointer, which also
corrupts the anchor because a record's extent is next minus start.

    python spawn_prop.py 01 --info
    python spawn_prop.py 01 --prefs 3BE028EE --site test --dry-run
    python spawn_prop.py 01 --prefs 3BE028EE --pos 47.37,91.98,38.22 --keep-ids --keep-name2
    python spawn_prop.py 01 --donor 207496 --pos 47.37,91.98,38.22   # rf_barrel
    python spawn_prop.py 01 --revert
"""
import argparse, math, os, shutil, struct, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POSITIONS = os.path.join(ROOT, "SWSEMods", "SWSE Console", "positions.txt")
SITES = os.path.join(ROOT, "SWSEMods", "SWSE Console", "sites.txt")
BAK = ".spawnbak"

TOKEN, SENTINEL, CHAIN_START = 0x7A60600D, 0x601307A6, 20
NULL_ID = 0x2DFD1072
NEXT, CLASS_ID, INST_ID = 4, 12, 16
ROT, POS, ONE, TINT, NAME2 = 25, 61, 73, 77, 96
ZONE = 20


def lvl_path(region):
    return os.path.join(ROOT, "data", "bundles", "region_" + region,
                        "lm_level_" + region + ".lvl")


def u32(d, off):
    return struct.unpack_from("<I", d, off)[0]


def walk(d):
    """Every record offset in chain order, plus the offset the chain ends at."""
    recs, cur, seen = [], CHAIN_START, set()
    while cur + 8 <= len(d) and u32(d, cur) == TOKEN:
        if cur in seen:
            raise ValueError("chain loops at " + str(cur))
        seen.add(cur)
        recs.append(cur)
        cur = u32(d, cur + NEXT)
    return recs, cur


def scale_of(d, s):
    """Uniform scale at +73, or None when this record has no transform.

    +73 IS A SCALE, NOT A SENTINEL. This field was read for a long time as a
    "must equal 1.0" validity flag, which silently discarded every scaled
    object: 9,103 of the game's 22,962 placed prop records - 40%, and 68% of
    region_02a - along with 602 objects that have no unscaled instance anywhere
    and so never appeared in the Prop Editor at all. The Wolvark gun_01 and
    gun_02 in region_06 are scaled 4.372 and were among them.

    The authored values are plainly a scale: 0.5, 0.75, 1.25, 1.5, 2.0, all
    positive.
    """
    if s + ONE + 4 > len(d):
        return None
    v = struct.unpack_from("<f", d, s + ONE)[0]
    if v != v or v <= 0.0 or v > 1e6:
        return None
    return v


def pos_of(d, s):
    """Translation, or None when this record does not carry a transform.

    Validity is decided by the ROTATION MATRIX, not by the scale. Every one of
    the game's 22,962 placed prop records has a perfectly orthonormal 3x3 at
    +25 - measured, zero deviation in all eight regions - so an orthonormal
    matrix is a far stronger test of "this really is a transform" than the old
    scale==1.0 check, and it does not throw away scaled objects.
    """
    if s + ONE + 4 > len(d):
        return None
    if scale_of(d, s) is None:
        return None
    m = struct.unpack_from("<9f", d, s + ROT)
    if any(v != v or abs(v) > 1e6 for v in m):
        return None
    for i in (0, 3, 6):
        n = math.sqrt(m[i] * m[i] + m[i + 1] * m[i + 1] + m[i + 2] * m[i + 2])
        if abs(n - 1.0) > 1e-3:
            return None
    p = struct.unpack_from("<3f", d, s + POS)
    if any(v != v or abs(v) > 1e6 for v in p):
        return None
    return p


def matrix_from_yaw(deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return [c, -s, 0.0, s, c, 0.0, 0.0, 0.0, 1.0]


def yaw_of(m):
    return math.degrees(math.atan2(m[3], m[0])) % 360.0


def read_marker(name):
    """Last matching entry wins - writepos appends, so the newest is the one."""
    for path, has_yaw in ((SITES, True), (POSITIONS, False)):
        if not os.path.exists(path):
            continue
        hit = None
        for line in open(path, encoding="utf-8", errors="replace"):
            p = line.split()
            if len(p) >= 4 and p[0] == name:
                try:
                    hit = (float(p[1]), float(p[2]), float(p[3]),
                           float(p[4]) if has_yaw and len(p) > 4 else None,
                           os.path.basename(path))
                except ValueError:
                    pass
        if hit:
            return hit
    return None


def fresh_id(d):
    """An instance id that appears nowhere in the file, at any alignment."""
    cand = 0xA73C0001
    while d.find(struct.pack("<I", cand)) >= 0:
        cand += 1
    return cand


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("region")
    ap.add_argument("--prefs", help="prefs hash of the thing to place, hex")
    ap.add_argument("--donor", type=int,
                    help="clone this exact record offset instead of --prefs")
    ap.add_argument("--site", help="name from positions.txt / sites.txt")
    ap.add_argument("--pos", help="x,y,z instead of --site")
    ap.add_argument("--yaw", type=float, default=0.0)
    ap.add_argument("--mode", choices=("spatial", "append", "insert"),
                    default="insert")
    ap.add_argument("--keep-ids", action="store_true",
                    help="keep the donor's +16 instance id rather than minting "
                         "a fresh one (vanilla does contain duplicates)")
    ap.add_argument("--keep-name2", action="store_true",
                    help="keep the donor's +96 id rather than nulling it")
    ap.add_argument("--zone", default="auto",
                    help="zone index for +20: 'auto' takes it from the records "
                         "already at the target, 'keep' inherits the donor's, "
                         "or give a number. An object whose zone does not match "
                         "its position is registered to the wrong zone and "
                         "never streams in.")
    ap.add_argument("--move", type=int, metavar="OFFSET",
                    help="DIAGNOSTIC: move an existing record to --pos/--yaw. "
                         "Adds nothing; proves whether the position field is "
                         "what places an object.")
    ap.add_argument("--info", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--revert", action="store_true")
    a = ap.parse_args()
    p = lvl_path(a.region)

    if a.revert:
        if os.path.exists(p + BAK):
            shutil.copy2(p + BAK, p)
            print("reverted lm_level_" + a.region + ".lvl")
        else:
            print("no backup to revert to")
        return

    d = bytearray(open(p, "rb").read())
    recs, end = walk(bytes(d))
    term = u32(bytes(d), end)
    # the tail is zero padding; the high-water mark is the last non-zero byte,
    # so repeated runs of this tool keep stacking rather than overwriting
    free = len(d)
    while free > 0 and d[free - 1] == 0:
        free -= 1
    print("chain: %d records, %d..%d" % (len(recs), CHAIN_START, end))
    print("terminator at %d: %08X %s" % (end, term,
          "(sentinel)" if term == SENTINEL else "(UNEXPECTED)"))
    print("free space %d..%d = %d bytes, all zero = %s"
          % (free, len(d), len(d) - free, set(d[free:]) <= {0}))

    if a.move is not None:
        if a.move not in recs:
            sys.exit("offset %d is not a record in the chain" % a.move)
        if not a.pos:
            sys.exit("--move needs --pos x,y,z")
        x, y, z = (float(v) for v in a.pos.split(","))
        before = pos_of(bytes(d), a.move)
        bm = list(struct.unpack_from("<9f", bytes(d), a.move + ROT))
        print("record @%d  class %08X" % (a.move, u32(bytes(d), CLASS_ID + a.move)))
        print("   position (%.2f, %.2f, %.2f) -> (%.2f, %.2f, %.2f)"
              % (before[0], before[1], before[2], x, y, z))
        print("   yaw      %.1f -> %.1f" % (yaw_of(bm), a.yaw))
        if a.dry_run:
            print("dry run")
            return
        if not os.path.exists(p + BAK):
            shutil.copy2(p, p + BAK)
        for i, v in enumerate(matrix_from_yaw(a.yaw)):
            struct.pack_into("<f", d, a.move + ROT + 4 * i, v)
        for i, v in enumerate((x, y, z)):
            struct.pack_into("<f", d, a.move + POS + 4 * i, v)
        open(p, "wb").write(bytes(d))
        d2 = open(p, "rb").read()
        q = pos_of(d2, a.move)
        print("   written; reads back (%.2f, %.2f, %.2f) yaw %.1f"
              % (q[0], q[1], q[2],
                 yaw_of(list(struct.unpack_from("<9f", d2, a.move + ROT)))))
        r2, e2 = walk(d2)
        print("   chain intact: %d records, terminator %08X"
              % (len(r2), u32(d2, e2)))
        return

    if a.info or not (a.prefs or a.donor):
        if not a.info:
            ap.print_help()
        return

    if term != SENTINEL:
        sys.exit("chain does not end at the expected sentinel - aborting")
    if set(d[free:]) - {0}:
        sys.exit("free space is not zeroed - aborting")

    if a.site:
        hit = read_marker(a.site)
        if hit is None:
            sys.exit("marker " + repr(a.site) + " not found")
        x, y, z, logged_yaw, src = hit
        yaw = a.yaw if a.yaw is not None else (logged_yaw or 0.0)
        print("\nsite %r from %s: (%.2f, %.2f, %.2f)" % (a.site, src, x, y, z))
    elif a.pos:
        x, y, z = (float(v) for v in a.pos.split(","))
        yaw = a.yaw
    else:
        sys.exit("need --site or --pos")

    # donor: an existing placement of the same prefs. Record length comes from
    # the next pointer, never from address order - the chain is not sorted by
    # address once anything has been spliced.
    if a.donor is not None:
        if a.donor not in recs:
            sys.exit("offset %d is not a record in the chain" % a.donor)
        donor = a.donor
        dlen = u32(bytes(d), donor + NEXT) - donor
        if dlen <= 0:
            sys.exit("donor record has a non-forward next pointer")
        print("donor: record @%d, %d bytes (named explicitly)" % (donor, dlen))
    else:
        ph = struct.pack("<I", int(a.prefs, 16))
        lengths = {}
        total = 0
        for s in recs:
            e = u32(bytes(d), s + NEXT)
            if e <= s or e > len(d):
                continue
            if ph in d[s:e]:
                total += 1
                lengths.setdefault(e - s, []).append(s)
        if not lengths:
            sys.exit("no existing placement of prefs " + a.prefs + " to copy")
        dlen = max(lengths, key=lambda n: len(lengths[n]))
        donor = lengths[dlen][0]
        print("donor: record @%d, %d bytes (%d placements, %d of this length)"
              % (donor, dlen, total, len(lengths[dlen])))
    if dlen > len(d) - free:
        sys.exit("not enough free space for a %d-byte record" % dlen)

    # the nearest positioned record - the source of the baked tint in both
    # modes, and the splice point in spatial mode
    nearest, best = None, None
    for s in recs:
        q = pos_of(bytes(d), s)
        if q is None:
            continue
        dist = math.dist(q, (x, y, z))
        if best is None or dist < best:
            nearest, best = s, dist
    if nearest is None:
        sys.exit("no positioned record to take a tint from")
    nq = pos_of(bytes(d), nearest)
    print("nearest: record @%d at (%.2f, %.2f, %.2f), %.2f units away"
          % (nearest, nq[0], nq[1], nq[2], best))

    # The zone at +20 has to agree with the position. Take it from the records
    # already standing at the target rather than from the donor, which may live
    # somewhere else entirely.
    ranked = sorted(
        ((math.dist(pos_of(bytes(d), s), (x, y, z)), s) for s in recs
         if pos_of(bytes(d), s) is not None))[:12]
    tally = {}
    for _, s in ranked:
        zv = u32(bytes(d), s + ZONE)
        tally[zv] = tally.get(zv, 0) + 1
    auto_zone = max(tally, key=tally.get)
    donor_zone = u32(bytes(d), donor + ZONE)
    if a.zone == "auto":
        zone = auto_zone
    elif a.zone == "keep":
        zone = donor_zone
    else:
        zone = int(a.zone, 0)
    print("zone:    target area is zone %d (%d of the 12 nearest records); "
          "donor is zone %d -> using %d"
          % (auto_zone, tally[auto_zone], donor_zone, zone))

    if a.mode == "insert":
        # open a gap right after the nearest record and shift the rest of the
        # chain along, fixing every next pointer. next is the only real pointer
        # in the file, so this is complete: the result is what the exporter
        # would have written had the object been there all along.
        anchor = nearest
        place = u32(bytes(d), anchor + NEXT)
        after = place + dlen
        print("anchor: inserting at %d, shifting %d bytes along by %d"
              % (place, len(d) - place, dlen))
    elif a.mode == "append":
        # take over the sentinel's slot and push the sentinel along. The last
        # record already points here, so no existing pointer changes at all.
        anchor, place, after = recs[-1], end, end + dlen
        if after + 4 > len(d):
            sys.exit("not enough tail room to append and move the sentinel")
        print("anchor: last record @%d (its next already points at %d)"
              % (anchor, end))
    else:
        anchor = nearest
        place, after = free, u32(bytes(d), anchor + NEXT)
        if place + dlen > len(d):
            sys.exit("not enough tail room for a %d-byte record" % dlen)
        print("anchor: splicing after the nearest record")

    rec = bytearray(d[donor:donor + dlen])
    struct.pack_into("<I", rec, NEXT, after)
    if a.keep_ids:
        new_id = u32(bytes(rec), INST_ID)
    else:
        new_id = fresh_id(bytes(d))
        struct.pack_into("<I", rec, INST_ID, new_id)
    if not a.keep_name2:
        struct.pack_into("<I", rec, NAME2, NULL_ID)
    struct.pack_into("<I", rec, ZONE, zone)
    for i, v in enumerate(matrix_from_yaw(yaw)):
        struct.pack_into("<f", rec, ROT + 4 * i, v)
    for i, v in enumerate((x, y, z)):
        struct.pack_into("<f", rec, POS + 4 * i, v)
    # the baked tint belongs to the spot, not the object - take the neighbour's
    if u32(bytes(d), nearest + NEXT) - nearest > TINT + 4:
        rec[TINT:TINT + 4] = d[nearest + TINT:nearest + TINT + 4]

    print("\nnew record -> offset %d, %d bytes  [mode %s]" % (place, dlen, a.mode))
    print("   instance id  %08X %s" % (new_id,
          "(cloned verbatim)" if a.keep_ids else "(unused anywhere in the file)"))
    print("   class id     %08X" % u32(bytes(rec), CLASS_ID))
    print("   position     (%.2f, %.2f, %.2f)" % (x, y, z))
    print("   yaw          %.1f" % yaw)
    print("   chain        %d -> %d -> %s" % (anchor, place,
          "sentinel" if a.mode == "append" else str(after)))

    if a.dry_run:
        print("\ndry run - re-run without --dry-run")
        return

    if not os.path.exists(p + BAK):
        shutil.copy2(p, p + BAK)
    if a.mode == "insert":
        # grow the file by the record length. There is no size constraint here
        # - the loader streams records until the token stops matching - so the
        # record goes in whole and everything after it simply moves along.
        src = bytes(d)
        out = bytearray(src[:place]) + rec + bytearray(src[place:])
        # every record that moved, and every pointer into the moved region
        for s in recs:
            moved = s if s < place else s + dlen
            v = u32(src, s + NEXT)
            struct.pack_into("<I", out, moved + NEXT,
                             v if v < place else v + dlen)
        # the anchor must point at the new record, not past it
        struct.pack_into("<I", out, anchor + NEXT, place)
        d = out
    else:
        d[place:place + dlen] = rec
        if a.mode == "append":
            struct.pack_into("<I", d, after, SENTINEL)
        else:
            struct.pack_into("<I", d, anchor + NEXT, place)
    open(p, "wb").write(bytes(d))

    # re-walk from scratch: the chain must be one longer and still terminate
    d2 = open(p, "rb").read()
    recs2, end2 = walk(d2)
    idx = recs2.index(place) if place in recs2 else -1
    q = pos_of(d2, place)
    m = list(struct.unpack_from("<9f", d2, place + ROT))
    print("\nverify: %d -> %d records, terminator %08X at %d"
          % (len(recs), len(recs2), u32(d2, end2), end2))
    print("   new record at chain index %d of %d, directly after anchor: %s"
          % (idx, len(recs2), idx > 0 and recs2[idx - 1] == anchor))
    print("   reads back (%.2f, %.2f, %.2f) yaw %.1f"
          % (q[0], q[1], q[2], yaw_of(m)))
    print("   file size %d (unchanged: %s)" % (len(d2), len(d2) == len(d)))


if __name__ == "__main__":
    main()
