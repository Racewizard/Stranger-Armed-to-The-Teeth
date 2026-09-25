r"""Put an NPC into the utility (debug / weapon-test) region.

PROP_PLACEMENT.md sec.10 records why nothing else reaches this region: it uses
`utility\empty.lvl`, `utility\empty\empty_tag.smb`, `utility\empty_blockmap.smh`
instead of the region_NN / lm_level_NN scheme every path helper assumes, and its
level holds no InstancedObjectTag record to clone from.

So the donor comes from region_01 instead: a real spawn OF THE REQUESTED
CHARACTER, copied whole. Every field is therefore already correct - character
type, prefs key, the lot - and only position, yaw, zone and the record id are
rewritten. That is the same "clone something that works, then change what it is"
approach apply_spawns uses, which is the only one proven in game.

The character's own records must already be in empty_tag.smb, and the blockmap
must already list them:

    python blockmap_add.py utility empty_tag.smb <hashes...>

    python utility_spawn.py --list
    python utility_spawn.py --char FFFC00CB --pos 0,0,0 --yaw 180
    python utility_spawn.py --revert
"""
import argparse, os, shutil, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rebuild_bundle as RB
from spawn_prop import walk, u32, NEXT, ROT, POS
from whose_attachment import spawn_table

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LVL = os.path.join(ROOT, "data", "bundles", "utility", "empty.lvl")
TGL = os.path.join(ROOT, "data", "bundles", "utility", "empty", "empty_tag.smb")
DONOR_LVL = os.path.join(ROOT, "data", "bundles", "region_01", "lm_level_01.lvl")
BAK = ".utilbak"
TYPE_OFF = 128
TERM = 0x601307A6


def resident():
    return {r["hash"] for r in RB.parse(open(TGL, "rb").read())[1]}


NULL_ID = 0x2DFD1072
JOB_A, JOB_B = 92, 195


def donor_for(char_hash):
    """Shortest spawn of that character WITH A NULL JOB.

    The job filter is not optional. apply_spawns' pick_donor has always required
    it (`dr[3] == NULL_ID`); this tool did not, and picked purely by length. The
    shortest clakker_male spawn in region_01 carries a job - it is script-driven -
    so every clone made from it was created and never instantiated, while
    outlaw_shooter clones worked because its shortest happens to be null-job.
    That produced a whole run of invisible NPCs whose data was perfectly fine.
    """
    d = open(DONOR_LVL, "rb").read()
    best = None
    fallback = None
    for o, h in spawn_table(d):
        if h != char_hash:
            continue
        st = o - TYPE_OFF
        ln = u32(d, st + NEXT) - st
        blob = bytes(d[st:st + ln])
        free = (u32(d, st + JOB_A) == NULL_ID and u32(d, st + JOB_B) == NULL_ID)
        if free:
            if best is None or ln < best[1]:
                best = (blob, ln)
        elif fallback is None or ln < fallback[1]:
            fallback = (blob, ln)
    if best is None and fallback is not None:
        print("   WARNING: no null-job spawn of %08X - using a SCRIPTED donor, "
              "which usually does not appear" % char_hash)
        return fallback
    return best


def matrix(yaw):
    import math
    c, s = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    return [c, s, 0.0, -s, c, 0.0, 0.0, 0.0, 1.0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--char", help="character type hash, hex")
    ap.add_argument("--pos", help="x,y,z")
    ap.add_argument("--yaw", type=float, default=0.0)
    ap.add_argument("--zone", type=int, default=0)
    ap.add_argument("--donor", help="clone a spawn of THIS character, then retype "
                                    "it to --char. For a custom hash that has no "
                                    "spawn of its own anywhere.")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--revert", action="store_true")
    a = ap.parse_args()

    if a.revert:
        if os.path.exists(LVL + BAK):
            shutil.copy2(LVL + BAK, LVL)
            print("empty.lvl reverted")
        else:
            print("no backup to revert to")
        return 0

    d = bytearray(open(LVL, "rb").read())
    recs = walk(bytes(d))[0]
    if a.list:
        res = resident()
        print("utility level: %d record(s)" % len(recs))
        for s in recs:
            cls = u32(bytes(d), s + 12)
            extra = ""
            if cls == 0x2B9F6678:
                extra = "  character %08X" % u32(bytes(d), s + TYPE_OFF)
            print("   @%-6d class=%08X%s" % (s, cls, extra))
        # What you actually need before spending a launch: is every character
        # THIS level spawns resident? A spawn whose character record is absent
        # is created and never instantiated - the silent failure that has
        # already cost several launches.
        spawned = [u32(bytes(d), s + TYPE_OFF) for s in recs
                   if u32(bytes(d), s + 12) == 0x2B9F6678]
        print("")
        print("characters this level spawns:")
        for h in sorted(set(spawned)):
            print("   %08X  %s" % (h, "resident" if h in res
                  else "*** NOT RESIDENT - will not instantiate ***"))
        # Separately: which characters can be spawned from a region_01 donor.
        # This is NOT a residency list - clones and characters with no
        # region_01 spawn are legitimately absent from it. Mislabelling it as
        # one reads as a missing-record alarm when nothing is wrong.
        dl = open(DONOR_LVL, "rb").read()
        avail = sorted({h for _o, h in spawn_table(dl)} & res)
        print("")
        print("resident AND spawnable from a region_01 donor: %d" % len(avail))
        for h in avail:
            print("   %08X" % h)
        return 0

    if not (a.char and a.pos):
        sys.exit("need --char and --pos (or --list / --revert)")
    ch = int(a.char, 16)
    if ch not in resident():
        sys.exit("%08X is not resident in empty_tag.smb - import it first" % ch)
    dh = int(a.donor, 16) if a.donor else ch
    got = donor_for(dh)
    if not got:
        sys.exit("no region_01 spawn of %08X to clone" % dh)
    rec, ln = got
    rec = bytearray(rec)

    x, y, z = [float(v) for v in a.pos.split(",")]
    struct.pack_into("<9f", rec, ROT, *matrix(a.yaw))
    struct.pack_into("<3f", rec, POS, x, y, z)
    struct.pack_into("<I", rec, 20, a.zone)
    used = {u32(bytes(d), s + 16) for s in recs}
    nid = 0x00010000
    while nid in used:
        nid += 1
    struct.pack_into("<I", rec, 16, nid)
    if a.donor:                                  # retype the clone to the real character
        struct.pack_into("<I", rec, TYPE_OFF, ch)

    last = recs[-1]
    end = u32(bytes(d), last + NEXT)             # where the terminator sits
    struct.pack_into("<I", rec, NEXT, end + ln)
    struct.pack_into("<I", d, last + NEXT, end)  # unchanged; the new record follows
    out = bytearray(d[:end]) + rec + struct.pack("<I", TERM)
    out += b"\x00" * max(0, len(d) - len(out))

    if not os.path.exists(LVL + BAK):
        shutil.copy2(LVL, LVL + BAK)
    open(LVL, "wb").write(bytes(out))
    print("added %08X at (%.2f, %.2f, %.2f) yaw %.1f zone %d"
          % (ch, x, y, z, a.yaw, a.zone))
    print("   record %d bytes, id %08X, level %d -> %d bytes"
          % (ln, nid, len(d), len(out)))
    chk = walk(bytes(out))[0]
    print("   chain now %d record(s)" % len(chk))
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
