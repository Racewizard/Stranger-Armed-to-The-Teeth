r"""Resolve CFG and ANC for a character record, and say when it cannot.

Every offset after `m_animationConfigFile` is quoted relative to one of two
anchors, because the config path is a variable-length string:

    CFG   end of the config path string
    ANC   end of the m_audioName / m_bountyCategory string run

Getting ANC wrong silently shifts every field after it, so this resolves it
FORWARD from CFG - the block between them is fixed-size - rather than counting
back from the end of the record, which is what previously failed.

THERE ARE THREE RECORD SHAPES. A survey that mixes them produces nonsense:

  full     67 records, audioName run starts at CFG+352. Ordinary NPCs.
  short    6 records, the run starts at CFG+348 - one 4-byte field earlier.
           GiantSleg, gloktigi, sekto, sektoMachine, shocktank.
  stub     15 records that have a MotionAnimConfig but stop long before the
           audioName block (ArmadilloWeapon, SquirrelWeapon, FuzzleWeapon,
           BeeGunWeapon, SpiderWeapon, SkunkWeapon, HiveQueenWeapon,
           sulphurBatWeapon, FuzzleAttack, SendToBow, steef). These are the live
           ammo and its effects. They carry NO health, attachments or affBy
           block; anchor() returns None for them and they must be excluded.

    python char_anchor.py            audit the whole roster
"""
import os, struct, sys, glob, collections

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rebuild_bundle as RB

NULL = 0x2DFD1072
BS = chr(92)


def cfg(b):
    """(offset just past the config path, config file name) or (None, None)."""
    o = 0
    while o < len(b) - 4:
        n = struct.unpack_from("<I", b, o)[0]
        if 2 <= n <= 200 and o + 4 + n <= len(b):
            s = b[o + 4:o + 4 + n]
            if all(32 <= c < 127 for c in s):
                if b"MotionAnimConfig" in s:
                    return o + 4 + n, s.decode().rsplit(BS, 1)[-1].replace(".txt", "")
                o += 4 + n
                continue
        o += 1
    return None, None


# Where the audioName run may start, relative to CFG: full records, then short.
# Every character in the retail roster starts it at exactly one of these. The
# old forward scan took the first thing after CFG that LOOKED like a lower-case
# string, and an edited float can look like one: 60.0 is 00 00 70 42, so with a
# 1 in the byte before it reads as the one-letter string "p". test_mortar
# (2026-09-13) got voice "p" at CFG+244 that way, ANC moved with it, and health,
# weapons and drops all locked as "front of record does not validate".
RUN_OFFSETS = (352, 348)


def _run_string(b, o):
    """Length of the audioName-run string at o, or 0 if there is none."""
    if o < 0 or o + 4 > len(b):
        return 0
    n = struct.unpack_from("<I", b, o)[0]
    if not (1 <= n <= 40 and o + 4 + n <= len(b)):
        return 0
    s = b[o + 4:o + 4 + n]
    return n if all(97 <= c <= 122 or c == 95 for c in s) else 0


def run_start(b, C):
    """Offset of the first string of the audioName run, or None (a stub)."""
    if C is None:
        return None
    for rel in RUN_OFFSETS:
        if _run_string(b, C + rel):
            return C + rel
    return None


def anchor(b):
    """ANC, or None when the record is a stub with no audioName block.

    The run is m_audioName, plus m_bountyCategory when the character has one -
    take the END of the whole consecutive run, not the first string. Using the
    first puts every later field 13 bytes early on characters that carry both.
    """
    C, _ = cfg(b)
    end = run_start(b, C)
    if end is None:
        return None
    n = _run_string(b, end)
    while n:
        end += 4 + n
        n = _run_string(b, end)
    return end


def validate(b, A, known):
    """Fields already confirmed in game. All must hold, or the anchor is wrong."""
    if A is None or A + 181 > len(b):
        return "past end of record"
    # 100000 is a real value, not a bad read: townsfolk, natives and several
    # bosses use it as "effectively invincible". An earlier bound of <100000
    # rejected 17 correctly-anchored records for having it.
    hp = struct.unpack_from("<f", b, A + 16)[0]
    st = struct.unpack_from("<f", b, A + 24)[0]
    if not (0.0 < hp <= 1e6 and hp == hp):
        return "m_health %r" % hp
    if not (0.0 <= st <= 1e6 and st == st):
        return "m_stamina %r" % st
    for o, nm in ((40, "m_onDeathGib"), (41, "m_allowOnDeathGibFromBolts"),
                  (62, "m_canBeBountied")):
        if b[A + o] not in (0, 1):
            return "%s = %d" % (nm, b[A + o])
    for o, nm in ((42, "m_onGibSpawnNPC"), (54, "m_meleeWeapon"), (58, "m_rangedWeapon"),
                  (149, "onDamage"), (153, "onExhaust"), (157, "onDeath"),
                  (161, "steefRamAlive"), (165, "strangerRamAlive"),
                  (169, "steefRamDead"), (173, "strangerRamDead")):
        h = struct.unpack_from("<I", b, A + o)[0]
        if h not in (NULL, 0) and h not in known:
            return "%s = %08X is not a record" % (nm, h)
    if struct.unpack_from("<I", b, A + 145)[0] > 200:
        return "m_collectableSpawnLimit too large"
    return None


def roster(root=None):
    """{hash: (cfgname, CFG, ANC or None, desc)} for every character record."""
    root = root or os.path.dirname(HERE)
    known, out = set(), {}
    # index EVERY .smb under data/, not just data/bundles - characters
    # reference records that live in data/global, and treating those as unknown
    # made correctly-anchored records look broken.
    for p in glob.glob(os.path.join(root, "data", "**", "*.smb"), recursive=True):
        # emptygulch's bundles are byte copies of region_01 that the engine never
        # reads - and they sort FIRST, so every region_01 character was read from
        # its emptygulch copy. Edit one in place and the Character Creator kept
        # showing the old values: the save worked, the display read a dead file.
        if "emptygulch" in os.path.normpath(p).lower().split(os.sep):
            continue
        try:
            recs = RB.parse(open(p, "rb").read())[1]
        except (Exception, SystemExit):
            continue          # not every .smb under data/ is a record bundle
        for r in recs:
            known.add(r["hash"])
            if r["hash"] in out:
                continue
            C, nm = cfg(r["desc"])
            if C:
                out[r["hash"]] = (nm, C, None, r["desc"])
    for h in out:
        nm, C, _, b = out[h]
        out[h] = (nm, C, anchor(b), b)
    return out, known


if __name__ == "__main__":
    rs, known = roster()
    good, stub, bad = [], [], []
    for h, (nm, C, A, b) in rs.items():
        if A is None:
            stub.append((nm, h))
            continue
        why = validate(b, A, known)
        (good if why is None else bad).append((nm, h, A - C, why))
    print("%d character records: %d anchored and validated, %d stubs, %d failed"
          % (len(rs), len(good), len(stub), len(bad)))
    shapes = collections.Counter(d for _, _, d, _ in good)
    print("   ANC-CFG distance: %s" % dict(shapes))
    if bad:
        print("\nfailed validation:")
        for nm, h, d, why in sorted(bad):
            print("   %-28s %08X  ANC-CFG=%d  %s" % (nm, h, d, why))
    print("\ncontrol - m_onDeathGib (ANC+40) true for:")
    print("   %s" % ", ".join(sorted({nm for nm, h, d, w in good
                                      if rs[h][3][rs[h][2] + 40] == 1})))
