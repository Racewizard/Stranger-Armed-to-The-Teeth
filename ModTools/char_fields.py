r"""Character record fields: read them out of a record, write them into a clone.

This is Layer 2's field table made executable - the piece the Character
Creator was missing. Before it existed, every dial on the Physical, Behavior
and Rewards tabs was inert: the build copied the donor record byte for byte,
and the form's "defaults" were placeholders never read from any character.

ONE LOCATOR PER FIELD. A field whose locator does not resolve on a given record
is reported unwritable FOR THAT RECORD, with the reason, and is never written
at a guessed offset.

    abs      fixed offset from the record start      species, voice pitch
    cfg      offset from CFG (end of the anim path)  push / knock / only-stands,
                                                     the four sight blocks,
                                                     combat tuning (probable)
    motion   offset from the motion run, 40 bytes    mass, body sphere, turn
             before the config path's length prefix  speed, water offset/scale
             (char_model.motion_anchor)
    head     offset from ANC, validated on the       scale, health, stamina,
             front of the record only (ANC+8..+79)   exhaust, gibbing, bounty
    critter  offset from ANC, range-checked          fuzzle and armadillo tuning
    list     m_affList: a COUNT at ANC+137, then     the ammo listed on the
             that many record hashes                 character - SPLICED, so it
                                                     changes the record length
    flags    the four responds-to bytes, directly    dynamite / skunk / spider /
             after m_affList                         fuzzle
    tail     spawn limit + seven spawners, directly  collectable drops
             after the flags
    value    the single dword referencing that kind  body geometry, bounty icon
             of asset
    audio    first string of the audioName run -     voice - also spliced
             it can change the record's length
    attach   m_defaultAttachments: a COUNT directly  worn meshes - bone, mesh,
             after the spawners' empty neighbour,    rotation, position, scale -
             ending 29 bytes short of the record     SPLICED

THE TAIL, CORRECTED 2026-09-12. The bytes after the critter tuning are

    ANC+136            m_affGenerally, byte: 1 on 77 characters, 0 on four (Shock
                       Tank, Sekto's Machine, two region_06 copies). It decides what
                       the list MEANS: 1 = affected by every ammo EXCEPT the listed
                       (Fatty lists SniperDart); 0 = affected ONLY by the listed
                       (Shock Tank's list leaves out fuzzles, stingbees, skunk bombs
                       and chipmunks - what it shrugs off in play)
    ANC+137            count N
    ANC+141 ...        N record hashes - the player's AMMO prefs: SniperDart,
                       TrapFuzzle, ImmobilizeSkunkBomb, SendToChipmunk ...
    ANC+141+4N         m_respondsToDamageDynamite .. m_respondsToTrapFuzzle
    ANC+145+4N         m_collectableSpawnLimit, then the seven spawners

57 of 75 characters have N = 0. The old "layout B" ("affect block absent =
immune") was a MISREADING: on six characters the count and the listed hashes
passed for a spawn limit and spawners. Honouring the count resolves all 75.

WHAT THE LIST MEANS is not tested in game. SniperDart is listed on exactly the
characters the player named sniper-immune, and SendToChipmunk on the
chipmunk-immune outlaw bosses, so it reads like an immunity list. AMMO_NAMES
holds all 31 player ammo prefs, named by hashing \data\prefs\weapons\<name>.txt
- the ammo list the AT3 Official preset ships - and only those are accepted as
entries.

THE ATTACHMENT LIST, 2026-09-13. After the seven spawners the record ends

    tail+32     m_attachments          u32 count - 0 on all 77 characters
    tail+36     m_defaultAttachments   u32 count N, then N entries of
                    <u32 len><bone name><u32 mesh hash><9f rotation><3f position><f scale>
    len-29      29 fixed bytes         m_aiHighDetail .. m_damageStarsOffset

in the engine's own field order (REFLECTION_SCHEMA.md, NPCPrefs). Resolved by
the count and required to end exactly 29 bytes short of the record: 27
characters carry entries, 50 carry none, none fail. The bone is a name from the
body mesh's rig (the one kind-20 record the mesh references); a name the rig
lacks renders nothing, silently. Axes, from in-game testing on the Killer
Clakker: position X lateral (+ left), Y depth (+ back), Z vertical (+ up).
The rotation is stored as a 3x3 matrix; `euler` shows it as R = Rz * Ry * Rx in
degrees and an edit may send either. The clakker's helmet tilt reads back as
X = 22.5 exactly, and compose(decompose(R)) matches every retail matrix.

THE SAFETY NET. apply() verifies the edited record at the positions located on
the ORIGINAL record, mapped through the splices (voice string, m_affList):
every edited field must read back as requested, every other field must read
back unchanged, and every byte outside the edited fields and the splices must
be identical. After an m_affList edit the tail must also re-parse with the new
count, flags and spawners exactly where the new list puts them. It refuses an
edit that overlaps the audioName string run.

WEAPONS. m_meleeWeapon / m_rangedWeapon are plain hash fields here; the
Weapon Creator makes new weapons and build_character.py checks that a chosen
hash really is a weapon record (weapon_fields.is_weapon) and ports it, with
its effects, into the target region.

SPAWN ON GIB. m_onGibSpawnNPC (ANC+42) is a plain hash field: the character
that takes this one's place when it gibs (retail: Shock Tank -> Wolvark
shooter, Tiny -> Meagly McGraw). build_character.py and edit_character.py
refuse a hash that is not a character record (is_character) and port the
chosen character, with everything it needs, into the target region.

    python char_fields.py read 35179A52
"""
import argparse, json, math, os, re, struct, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import char_anchor as CA
import char_model as CM
from gamehash import game_hash

NULL = 0x2DFD1072
BS = chr(92)
SPECIES_NAMES = ("outlaw", "wolvark", "slog", "native", "townsfolk")
SPECIES_BY_HASH = {game_hash(n): n for n in SPECIES_NAMES}
NUMBERED = ("00", "01", "02", "02a", "03", "04", "05", "06")
AFFLIST_MAX = 32
ATTACH_MAX = 16          # retail carries at most 5
ATTACH_TAIL = 29
IDENT = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
BONE_RE = re.compile(r"^[A-Za-z0-9_]{1,40}$")

# Every player ammo pref, by name. game_hash upper-cases, so the capitalisation
# here is for display only; each hash was matched to a real record 2026-09-13.
AMMO_NAMES = {game_hash(BS + "data" + BS + "prefs" + BS + "weapons" + BS + _n + ".txt"): _n for _n in (
    "ActivateHiveQueen", "ActivateHiveQueenCharged", "DamageArmadillo", "DamageArmadilloLoader",
    "DamageArmadilloLoaderExtender", "DamageBeeGun", "DamageBeeGunExtenderSmall", "DamageBoombatQueen",
    "DamageDynamite", "DamageDynamiteExtender", "DamageDynamiteExtenderLoader", "DamageRiotSlug",
    "DamageStingBee", "ImmobilizeBolaBlast", "ImmobilizeSkunkBomb", "ImmobilizeSkunkBombExtender",
    "ImmobilizeSparkStunkz", "ImmobilizeSpiderBola", "ImmobilizeSpiderBolaExtenderMedium",
    "ImmobilizeSpiderBolaExtenderSmall", "Punch", "SendToChipmunk", "SendToChipmunkExtender",
    "SendToHowlerPunk", "SniperDart", "TrapFuzzle", "TrapFuzzleJump", "TrapFuzzleLoader",
    "TrapFuzzleLoaderExtender", "TrapFuzzleRabid", "TrapFuzzleRabidJump")}


class FieldError(Exception):
    pass


SIGHT_BLOCKS = (("m_sightNormal", 91), ("m_sightAgit", 123),
                ("m_sightCombat", 155), ("m_sightPanic", 187))
SIGHT_FIELDS = ("m_6thSenseDistance", "m_seeDistance", "m_seeAbove", "m_seeBelow",
                "m_horizontalAngleDeg", "m_verticalAngleDeg",
                "m_instantSightDistance", "m_hideVolSeeDistance")
CFG_BYTES = (("m_canBePushed", 0), ("m_canBeKnocked", 1), ("m_onlyStands", 2))
COMBAT = (("fireSpot_NumShots", 232, "i"),
          ("ranged_desiredDistMin", 246, "f"), ("ranged_desiredDistMax", 250, "f"),
          ("ranged_beatApproachDist", 254, "f"), ("fireSpot_pauseAfter", 258, "f"),
          ("fireSpot_wanderRadius", 266, "f"), ("melee_approachDist_Front", 270, "f"),
          ("melee_approachDist_Behind", 274, "f"), ("lostLOSTime_1_Search", 278, "f"),
          ("lostLOSTime_2_Cover", 282, "f"), ("lostLOSTime_3_Hunt", 286, "f"),
          ("lostLOSTime_3_Hunt_WithoutFireSearch", 290, "f"),
          ("lostLOSTime_3_Hunt_MeleeGuy", 294, "f"), ("ranged_PercentUseOfCover", 298, "f"))
HEAD = (("m_geoScaleMin", 8, "f"), ("m_geoScaleMax", 12, "f"), ("m_health", 16, "f"),
        ("m_healthRecoverTime", 20, "f"), ("m_stamina", 24, "f"),
        ("m_staminaRecoverTime", 28, "f"), ("m_exhaustTime", 32, "f"),
        ("m_exhaustedRecoverMultiplier", 36, "f"), ("m_onDeathGib", 40, "b"),
        ("m_allowOnDeathGibFromBolts", 41, "b"), ("m_onGibSpawnNPC", 42, "h"),
        ("m_autoAimRadius", 46, "f"), ("m_hurtReaction", 50, "i"),
        ("m_meleeWeapon", 54, "h"), ("m_rangedWeapon", 58, "h"),
        ("m_canBeBountied", 62, "b"), ("m_captureMoolah", 63, "f"), ("m_killMoolah", 67, "f"),
        ("m_bountyAmmoBoost", 71, "f"), ("m_bountyEnduranceBoost", 75, "f"))
CRITTER = (("m_fuzzleShakeOffTime", 115, "f"), ("m_fuzzleFlopFrequency", 119, "f"),
           ("m_fuzzleFleeRadius", 123, "f"), ("m_armadilloStaminaMultiplier", 127, "f"),
           ("m_armadilloKnocks", 131, "b"), ("m_armadilloDamageMultiplier", 132, "f"))
# Offsets are the N = 0 positions; the real ones are relative to the end of
# m_affList (see tail_layout).
FLAGS = (("m_respondsToDamageDynamite", 141), ("m_respondsToImmobilizeSkunkBomb", 142),
         ("m_respondsToImmobilizeSpiderBola", 143), ("m_respondsToTrapFuzzle", 144))
TAIL = (("m_collectableSpawnLimit", 0, "i"), ("m_onDamageCollectableSpawner", 4, "h"),
        ("m_onExhaustCollectableSpawner", 8, "h"), ("m_onDeathCollectableSpawner", 12, "h"),
        ("m_onSteefRamAliveCollectableSpawner", 16, "h"),
        ("m_onStrangerRamAliveCollectableSpawner", 20, "h"),
        ("m_onSteefRamDeadCollectableSpawner", 24, "h"),
        ("m_onStrangerRamDeadCollectableSpawner", 28, "h"))
# Nothing is held back any more. m_onGibSpawnNPC was, until the Character
# Library picker existed; build/edit now check the chosen hash is a character.
READ_ONLY = {}
RANGES = {"m_minRandomSpeechPitch": (0, 4), "m_maxRandomSpeechPitch": (0, 4),
          "m_collectableSpawnLimit": (0, 200), "fireSpot_NumShots": (0, 100)}
WIDTH = {"b": 1}


def _u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def _f(b, o):
    return struct.unpack_from("<f", b, o)[0]


def _read(b, o, t):
    if o < 0 or o + (1 if t == "b" else 4) > len(b):
        return None
    if t == "f":
        v = _f(b, o)
        return round(v, 6) if math.isfinite(v) else None
    if t == "i":
        return struct.unpack_from("<i", b, o)[0]
    if t == "b":
        return b[o]
    v = _u32(b, o)
    return None if v in (NULL, 0) else "%08X" % v


def _audio_run(b, C):
    """(offset, length, text) of the FIRST string in the audioName run.

    char_anchor.run_start() finds it for both, so the two can never disagree
    about where the run starts.
    """
    o = CA.run_start(b, C)
    if o is None:
        return None
    n = _u32(b, o)
    return o, n, b[o + 4:o + 4 + n].decode()


def head_problem(b, A, known):
    """None when ANC+8..+79 hold what they must; otherwise the first reason."""
    if A is None or A + 80 > len(b):
        return "past end of record"
    smin, smax, hp = struct.unpack_from("<3f", b, A + 8)
    st = _f(b, A + 24)
    if not (0.05 <= smin <= 20 and 0.05 <= smax <= 20):
        return "scale %r / %r" % (smin, smax)
    if not (0.0 < hp <= 1e6):
        return "health %r" % hp
    if not (0.0 <= st <= 1e6):
        return "stamina %r" % st
    for o in (40, 41, 62):
        if b[A + o] not in (0, 1):
            return "byte ANC+%d = %d" % (o, b[A + o])
    for o in (42, 54, 58):
        v = _u32(b, A + o)
        if v not in (NULL, 0) and v not in known:
            return "ANC+%d %08X is not a record" % (o, v)
    for o in (63, 67, 71, 75):
        v = _f(b, A + o)
        if not (math.isfinite(v) and -1 <= v <= 1e6):
            return "float ANC+%d %r" % (o, v)
    return None


def critter_ok(b, A):
    if A + 136 > len(b):
        return False
    vals = struct.unpack_from("<4f", b, A + 115) + (_f(b, A + 132),)
    lim = (120, 20, 100, 20, 20)
    if not all(math.isfinite(v) and 0 <= v <= m for v, m in zip(vals, lim)):
        return False
    return b[A + 131] in (0, 1)


def _spawn_block(b, o, known):
    if o < 0 or o + 32 > len(b) or _u32(b, o) > 200:
        return False
    for k in range(4, 32, 4):
        v = _u32(b, o + k)
        if v not in (NULL, 0) and v not in known:
            return False
    return True


def tail_layout(b, A, known):
    """(m_affList hashes, flags offset, spawn-limit offset), or (None, None, None).

    See the module docstring for the layout. Every part is checked where the
    count puts it: each listed hash must be a real record, the four flags must
    be 0/1, and the spawn block must be a small limit plus seven dwords that
    are each NULL or a real record.
    """
    if A is None or A + 141 > len(b):
        return None, None, None
    n = _u32(b, A + 137)
    if n > AFFLIST_MAX or A + 141 + 4 * n + 36 > len(b):
        return None, None, None
    ents = [_u32(b, A + 141 + 4 * i) for i in range(n)]
    if any(e not in known for e in ents):
        return None, None, None
    f = A + 141 + 4 * n
    if not all(b[f + i] in (0, 1) for i in range(4)) or not _spawn_block(b, f + 4, known):
        return None, None, None
    return ents, f, f + 4


def attach_parse(b, D):
    """(entries, end offset) for the attachment vector whose count is at D, or (None, None).

    Floats are kept at full float32 precision - rounding them would change the
    bytes of an entry nobody edited when it is written back.
    """
    if D is None or D + 4 > len(b):
        return None, None
    n = _u32(b, D)
    if n > ATTACH_MAX:
        return None, None
    o, ents = D + 4, []
    for _ in range(n):
        if o + 4 > len(b):
            return None, None
        ln = _u32(b, o)
        if not (1 <= ln <= 40 and o + 4 + ln + 56 <= len(b)):
            return None, None
        nm = b[o + 4:o + 4 + ln]
        if not all(48 <= c <= 57 or 65 <= c <= 90 or 97 <= c <= 122 or c == 95 for c in nm):
            return None, None
        p = o + 4 + ln
        fl = struct.unpack_from("<13f", b, p + 4)
        if not all(math.isfinite(x) for x in fl):
            return None, None
        ents.append({"bone": nm.decode("ascii"), "geo": "%08X" % _u32(b, p),
                     "rot": list(fl[:9]), "tr": list(fl[9:12]), "scale": fl[12]})
        o = p + 56
    return ents, o


def attach_layout(b, tail):
    """(entries, count offset, None) or (None, None, reason) - THE ATTACHMENT LIST."""
    T = tail + 32
    if T + 8 > len(b):
        return None, None, "the record ends before the attachment lists"
    if _u32(b, T) != 0:
        return None, None, "m_attachments is not empty on this record (it is 0 on every retail character)"
    ents, end = attach_parse(b, T + 4)
    if ents is None:
        return None, None, "m_defaultAttachments does not parse by its count"
    if end != len(b) - ATTACH_TAIL:
        return None, None, "m_defaultAttachments does not end %d bytes short of the record" % ATTACH_TAIL
    return ents, T + 4, None


def attach_pack(ents):
    out = [struct.pack("<I", len(ents))]
    for e in ents:
        nm = e["bone"].encode("ascii")
        out.append(struct.pack("<I", len(nm)) + nm + struct.pack("<I", int(e["geo"], 16)))
        out.append(struct.pack("<9f", *e["rot"]) + struct.pack("<3f", *e["tr"]) + struct.pack("<f", e["scale"]))
    return b"".join(out)


def euler_of(R):
    """[x, y, z] degrees with R = Rz * Ry * Rx (row-major), rounded for display."""
    y = math.asin(max(-1.0, min(1.0, -R[6])))
    if abs(R[6]) < 0.999999:
        x, z = math.atan2(R[7], R[8]), math.atan2(R[3], R[0])
    else:                                   # gimbal lock: fold X into Z
        x, z = 0.0, math.atan2(-R[1], R[4])
    return [round(math.degrees(v), 4) + 0.0 for v in (x, y, z)]


def _axis(i, deg):
    # Snapped, so 90 degrees stores exactly 0 and 1 rather than 6.1e-17.
    a = math.radians(deg)
    c, s = round(math.cos(a), 12) + 0.0, round(math.sin(a), 12) + 0.0
    if i == 0:
        return [1.0, 0.0, 0.0, 0.0, c, -s, 0.0, s, c]
    if i == 1:
        return [c, 0.0, s, 0.0, 1.0, 0.0, -s, 0.0, c]
    return [c, -s, 0.0, s, c, 0.0, 0.0, 0.0, 1.0]


def _mul(a, b):
    return [sum(a[i * 3 + k] * b[k * 3 + j] for k in range(3)) for i in range(3) for j in range(3)]


def rot_of(euler):
    x, y, z = (float(v) for v in euler)
    return [round(v, 12) + 0.0 for v in _mul(_axis(2, z), _mul(_axis(1, y), _axis(0, x)))]


def _rot_ok(R):
    """A pure rotation: orthonormal rows, determinant +1."""
    for i in range(3):
        for j in range(3):
            if abs(sum(R[i * 3 + k] * R[j * 3 + k] for k in range(3)) - (1.0 if i == j else 0.0)) > 1e-3:
                return False
    det = (R[0] * (R[4] * R[8] - R[5] * R[7]) - R[1] * (R[3] * R[8] - R[5] * R[6])
           + R[2] * (R[3] * R[7] - R[4] * R[6]))
    return abs(det - 1.0) <= 1e-3


def is_character(desc):
    """A full character record: an animation config path AND the audioName run."""
    C, _ = CA.cfg(desc)
    return C is not None and CA.anchor(desc) is not None


def describe(name, v):
    """A change value for a log line - an attachment list as bone=mesh pairs."""
    if name == "m_defaultAttachments" and isinstance(v, list):
        return "%d attachment(s)%s" % (len(v), (": " + ", ".join("%s=%s" % (e["bone"], e["geo"]) for e in v)) if v else "")
    return repr(v)


# GIB EFFECT. The effect mix a character bursts into when gibbed - the SAME
# record type (9dbb3037) destructibles use for their debris. Every character
# carries the web-escape pair 6AC357BA 083796D7; the gib hash sits 56 bytes
# before it on 79 of 84 retail characters. On the other five (Duke, Floyd,
# Sekto, Sekto's Machine, one Outlaw Shooter) that position holds a weapon or
# a non-record - a shorter block - so the slot is writable ONLY where it
# already holds one of the known gibs. Offered set is deliberately closed.
GIB_WEB = struct.pack("<II", 0x6AC357BA, 0x083796D7)
GIB_BACK = 56
GIB_EFFECTS = {0xDA33DF83: "Default gibs", 0xA2A28E4F: "Default gibs (global copy)",
               0x026797F2: "Shock Tank chunks", 0x5978F009: "Turret chunks",
               0x4ABC85DB: "Mine cart chunks"}


def gib_slot(b):
    """(offset, None) or (None, reason)."""
    i = b.find(GIB_WEB)
    if i < 0 or b.find(GIB_WEB, i + 1) >= 0:
        return None, "no unique web-escape effect pair"
    o = i - GIB_BACK
    if o < 0 or _u32(b, o) not in GIB_EFFECTS:
        return None, "this record's effect block has a different layout (a boss)"
    return o, None


def locate(b, known, h2p):
    C, _ = CA.cfg(b)
    loc = {"C": C, "A": None, "audio": None, "motion": None, "head": False,
           "head_why": "no animation config path", "critter": False,
           "layout": None, "afflist": None, "flags": None, "tail": None,
           "attach": None, "attach_off": None,
           "attach_why": "the attachment list follows the drops, which do not resolve on this record",
           "geo": {}, "icon": {}, "gib": None, "gib_why": "not a character record"}
    if C is None:
        return loc
    loc["gib"], loc["gib_why"] = gib_slot(b)
    A = CA.anchor(b)
    loc["A"] = A
    loc["audio"] = _audio_run(b, C)
    loc["motion"] = CM.motion_anchor(b, C)
    loc["head_why"] = head_problem(b, A, known)
    loc["head"] = loc["head_why"] is None
    if loc["head"]:
        loc["critter"] = critter_ok(b, A)
        loc["afflist"], loc["flags"], loc["tail"] = tail_layout(b, A, known)
        if loc["tail"] is not None:
            loc["layout"] = "affList:%d" % len(loc["afflist"])
            loc["attach"], loc["attach_off"], loc["attach_why"] = attach_layout(b, loc["tail"])
    for k in range(len(b) - 3):
        v = _u32(b, k)
        q = h2p.get(v)
        if not q:
            continue
        ql = q.lower().replace(BS, "/")
        if ql.endswith(".geo") and "/characters/" in ql:
            loc["geo"].setdefault(v, []).append(k)
        elif "/character/icons/" in ql:
            loc["icon"].setdefault(v, []).append(k)
    return loc


def _table(loc):
    """name -> (absolute offset or None, type, reason-if-unwritable)."""
    C, A, M = loc["C"], loc["A"], loc["motion"]
    t = {}
    t["m_species"] = (12, "species", None)
    t["m_minRandomSpeechPitch"] = (52, "i", None)
    t["m_maxRandomSpeechPitch"] = (56, "i", None)
    for name, off in CFG_BYTES:
        t[name] = (C + off, "b", None)
    for blk, base in SIGHT_BLOCKS:
        for j, f in enumerate(SIGHT_FIELDS):
            t[blk + "." + f] = (C + base + 4 * j, "f", None)
    for name, off, ty in COMBAT:
        t[name] = (C + off, ty, None)
    for name, off, w, ty in CM.MOTION_FIELDS:
        t[name] = ((M + off) if M is not None else None, ty,
                   None if M is not None else "motion block not found on this record")
    for name, off, ty in HEAD:
        why = READ_ONLY.get(name) or (None if loc["head"] else
                                      "front of record does not validate: %s" % loc["head_why"])
        t[name] = ((A + off) if A is not None else None, ty, why)
    for name, off, ty in CRITTER:
        why = None if loc["critter"] else "critter tuning block is out of range here"
        t[name] = ((A + off) if (A is not None and loc["head"]) else None, ty, why)
    unresolved = "m_affList / flags / drops do not resolve on this record"
    ok = loc["afflist"] is not None
    t["m_affList"] = ((A + 137) if ok else None, "list", None if ok else unresolved)
    # The byte directly before the list's count, and what gives the list its
    # meaning - see THE TAIL. Located only where the list itself resolves.
    t["m_affGenerally"] = ((A + 136) if ok else None, "b", None if ok else unresolved)
    for i, (name, _n0) in enumerate(FLAGS):
        t[name] = ((loc["flags"] + i) if loc["flags"] is not None else None, "b",
                   None if loc["flags"] is not None else unresolved)
    for name, rel, ty in TAIL:
        t[name] = ((loc["tail"] + rel) if loc["tail"] is not None else None, ty,
                   None if loc["tail"] is not None else unresolved)
    for name, key, ty in (("m_geometry", "geo", "geo"), ("m_icon", "icon", "icon")):
        refs = loc[key]
        if len(refs) == 1 and len(next(iter(refs.values()))) == 1:
            t[name] = (next(iter(refs.values()))[0], ty, None)
        else:
            t[name] = (None, ty, "%d distinct reference(s) - not exactly one" % len(refs))
    t["m_audioName"] = (None, "audio", None if loc["audio"] else "no audioName string")
    t["m_defaultAttachments"] = (loc["attach_off"], "attach", loc["attach_why"])
    t["m_gibEffect"] = (loc["gib"], "gib", loc["gib_why"])
    return t


def read_values(b, known, h2p):
    """(values, why, loc) - why[name] is None where the field is writable."""
    loc = locate(b, known, h2p)
    if loc["C"] is None:
        return {}, {}, loc
    vals, why = {}, {}
    for name, (off, ty, reason) in _table(loc).items():
        why[name] = reason
        if ty == "audio":
            vals[name] = loc["audio"][2] if loc["audio"] else None
        elif ty == "list":
            vals[name] = (["%08X" % x for x in loc["afflist"]]
                          if loc["afflist"] is not None else None)
        elif ty == "attach":
            vals[name] = ([dict(e, euler=euler_of(e["rot"])) for e in loc["attach"]]
                          if loc["attach"] is not None else None)
        elif off is None:
            vals[name] = None
        elif ty == "species":
            sp = _u32(b, off)
            vals[name] = SPECIES_BY_HASH.get(sp, "%08X" % sp)
            if sp not in SPECIES_BY_HASH:
                why[name] = "species hash is not one of the five known"
        elif ty in ("geo", "icon", "gib"):
            vals[name] = "%08X" % _u32(b, off)
        else:
            vals[name] = _read(b, off, ty)
            if name in dict(CFG_BYTES) and vals[name] not in (0, 1):
                why[name] = "not a boolean on this record"
    return vals, why, loc


def _norm(ty, v):
    if ty == "f":
        return None if v in (None, "") else float(v)
    if ty in ("i", "b"):
        return None if v in (None, "") else int(float(v))
    if ty in ("h", "geo", "icon", "gib"):
        if v in (None, "", "NULL", "(nothing)"):
            return None
        return "%08X" % int(str(v), 16)
    if ty == "list":
        if v in (None, ""):
            return []
        if isinstance(v, str):
            v = [x for x in re.split(r"[\s,;]+", v) if x]
        return ["%08X" % int(str(x), 16) for x in v]
    if ty == "attach":
        if v in (None, ""):
            return []
        if isinstance(v, str):
            v = json.loads(v)
        if isinstance(v, dict):        # a one-entry list, as PowerShell's ConvertTo-Json may send it
            v = [v]
        out = []
        for e in v:
            if e.get("rot") is not None:
                rot = [float(x) for x in e["rot"]]
            elif e.get("euler") is not None:
                rot = rot_of(e["euler"])
            else:
                rot = list(IDENT)
            out.append({"bone": str(e["bone"]), "geo": "%08X" % int(str(e["geo"]), 16), "rot": rot,
                        "tr": [float(x) for x in (e.get("tr") if e.get("tr") is not None else (0, 0, 0))],
                        "scale": float(e["scale"]) if e.get("scale") is not None else 1.0})
        return out
    return v


def _same(a, b):
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, list) or isinstance(b, list):
        return [str(x).upper() for x in (a or [])] == [str(x).upper() for x in (b or [])]
    if isinstance(a, float) or isinstance(b, float):
        try:
            a, b = float(a), float(b)
        except (TypeError, ValueError):
            return False
        return abs(a - b) <= 1e-4 * max(1.0, abs(b))
    return str(a).upper() == str(b).upper()


def _eq(ty, a, b):
    """_same, except an attachment list compares as the bytes it would write."""
    if ty != "attach":
        return _same(a, b)
    if a is None or b is None:
        return a is None and b is None
    try:
        return attach_pack(_norm("attach", a)) == attach_pack(_norm("attach", b))
    except (KeyError, TypeError, ValueError, AttributeError, struct.error):
        return False


def apply(b, edits, known, h2p, warnings=None):
    """(new_bytes, changes). Raises FieldError rather than write anything wrong.

    `warnings`, when a list, collects non-fatal notes - currently only that the
    locators would read the EDITED record differently, which does not make the
    record wrong but means the Character Creator may misread it later.
    """
    vals, why, loc = read_values(b, known, h2p)
    if loc["C"] is None:
        raise FieldError("not a character record")
    table = _table(loc)
    out = bytearray(b)
    changes, audio_new, list_new, attach_new = [], None, None, None
    wanted = {}
    for name, new in edits.items():
        if name not in table:
            raise FieldError("unknown field %s" % name)
        off, ty, _ = table[name]
        try:
            nv = _norm(ty, new)
        except (TypeError, ValueError, KeyError, AttributeError):
            raise FieldError("%s: %r is not a valid value" % (name, new))
        # A value equal to what the record already holds is not an edit, even
        # on a field this record cannot have written - the launcher sends the
        # whole form, and a form that merely shows a read-only value must not
        # make the build refuse.
        if _eq(ty, nv, vals.get(name)):
            wanted[name] = nv
            continue
        if why.get(name):
            raise FieldError("%s cannot be written on this record: %s" % (name, why[name]))
        wanted[name] = nv
        if ty == "audio":
            if not isinstance(nv, str) or not re.match(r"^[a-z_]{1,40}$", nv):
                raise FieldError("voice must be 1-40 lower-case letters or underscores, got %r" % nv)
            audio_new = nv
            continue          # spliced in below
        if ty == "list":
            if len(nv) > AFFLIST_MAX:
                raise FieldError("m_affList holds at most %d entries, got %d" % (AFFLIST_MAX, len(nv)))
            for x in nv:
                h = int(x, 16)
                if h not in AMMO_NAMES:
                    raise FieldError("m_affList: %s is not one of the player's ammo prefs" % x)
                if h not in known:
                    raise FieldError("m_affList: %s (%s) is not a record in this install" % (x, AMMO_NAMES[h]))
            list_new = nv
            continue          # spliced in below
        if ty == "attach":
            if len(nv) > ATTACH_MAX:
                raise FieldError("at most %d attachments, got %d" % (ATTACH_MAX, len(nv)))
            for i, e in enumerate(nv):
                tag = "attachment %d (%s)" % (i + 1, e["bone"])
                if not BONE_RE.match(e["bone"]):
                    raise FieldError("attachment %d: a bone name is 1-40 letters, digits or underscores, got %r"
                                     % (i + 1, e["bone"]))
                g = int(e["geo"], 16)
                q = h2p.get(g)
                if g not in known or not (q and q.lower().endswith(".geo")):
                    raise FieldError("%s: %s is not a geometry record in this install" % (tag, e["geo"]))
                if len(e["rot"]) != 9 or len(e["tr"]) != 3 or \
                        not all(math.isfinite(x) for x in e["rot"] + e["tr"] + [e["scale"]]):
                    raise FieldError("%s: rotation, position and scale must be finite numbers" % tag)
                if not _rot_ok(e["rot"]):
                    raise FieldError("%s: the rotation is not a pure rotation" % tag)
                if not 0.0 < e["scale"] <= 100.0 or max(abs(x) for x in e["tr"]) > 100.0:
                    raise FieldError("%s: scale must be above 0 and at most 100, position within +/-100" % tag)
            attach_new = nv
            continue          # spliced in below
        if ty == "species":
            if nv not in SPECIES_NAMES:
                raise FieldError("species must be one of %s" % ", ".join(SPECIES_NAMES))
            struct.pack_into("<I", out, off, game_hash(nv))
        elif ty == "f":
            if nv is None or not math.isfinite(nv):
                raise FieldError("%s needs a number" % name)
            struct.pack_into("<f", out, off, nv)
        elif ty == "i":
            lo, hi = RANGES.get(name, (-2 ** 31, 2 ** 31 - 1))
            if nv is None or not lo <= nv <= hi:
                raise FieldError("%s must be a whole number %d..%d" % (name, lo, hi))
            struct.pack_into("<i", out, off, nv)
        elif ty == "b":
            if nv not in (0, 1):
                raise FieldError("%s must be 0 or 1" % name)
            out[off] = nv
        elif ty == "h":
            h = NULL if nv is None else int(nv, 16)
            if nv is not None and h not in known:
                raise FieldError("%s: %s is not a record in this install" % (name, nv))
            struct.pack_into("<I", out, off, h)
        elif ty == "gib":
            h = int(nv, 16) if nv else None
            if h not in GIB_EFFECTS:
                raise FieldError("m_gibEffect: %s is not one of the offered gib effects" % nv)
            if h not in known:
                raise FieldError("m_gibEffect: %s is not a record in this install" % nv)
            struct.pack_into("<I", out, off, h)
        elif ty in ("geo", "icon"):
            q = h2p.get(int(nv, 16)) if nv else None
            ok = q and ((ty == "geo" and q.lower().endswith(".geo") and "/characters/" in q.lower().replace(BS, "/"))
                        or (ty == "icon" and "/character/icons/" in q.lower().replace(BS, "/")))
            if not ok:
                raise FieldError("%s: %s is not a character %s" % (name, nv, "mesh" if ty == "geo" else "icon"))
            struct.pack_into("<I", out, off, int(nv, 16))
        else:
            raise FieldError("%s cannot be written" % name)
        changes.append((name, vals.get(name), nv))

    # SPLICES - (original start, original length, new bytes). Both lie in
    # regions no fixed-width field occupies: the voice string before ANC, the
    # list between the critter tuning and the flags.
    splices = []
    if audio_new is not None:
        st, n_old, old = loc["audio"]
        enc = audio_new.encode("ascii")
        splices.append((st, 4 + n_old, struct.pack("<I", len(enc)) + enc))
    if list_new is not None:
        A, N = loc["A"], len(loc["afflist"])
        splices.append((A + 137, 4 + 4 * N,
                        struct.pack("<I", len(list_new)) + b"".join(struct.pack("<I", int(x, 16)) for x in list_new)))
    if attach_new is not None:
        D = loc["attach_off"]
        splices.append((D, len(b) - ATTACH_TAIL - D, attach_pack(attach_new)))

    # A field that overlaps the audioName run or a splice would corrupt the
    # structure every locator after it depends on. Refuse it outright.
    touched = set()
    for name, old, nv in changes:
        off, ty, _ = table[name]
        rng = range(off, off + WIDTH.get(ty, 4))
        if loc["audio"] and loc["A"] is not None and rng.start < loc["A"] and rng.stop > loc["audio"][0]:
            raise FieldError("%s at +%d overlaps the audioName string run - refusing" % (name, off))
        for s, ol, nb in splices:
            if rng.start < s + ol and rng.stop > s:
                raise FieldError("%s at +%d overlaps a spliced block - refusing" % (name, off))
        touched.update(rng)

    for s, ol, nb in sorted(splices, key=lambda x: -x[0]):
        out = out[:s] + nb + out[s + ol:]
    if audio_new is not None:
        changes.append(("m_audioName", loc["audio"][2], audio_new))
    if list_new is not None:
        changes.append(("m_affList", vals.get("m_affList"), list_new))
    if attach_new is not None:
        changes.append(("m_defaultAttachments", vals.get("m_defaultAttachments"), attach_new))
    new = bytes(out)

    def at(o):
        """Original offset outside every splice -> offset in the new record."""
        return o + sum(len(nb) - ol for s, ol, nb in splices if o >= s + ol)

    def in_splice(i):
        return any(s <= i < s + ol for s, ol, nb in splices)

    # VERIFY at the positions located on the ORIGINAL record, mapped through
    # the splices - see THE SAFETY NET in the module docstring.
    for name, (off, ty, _r) in table.items():
        want = wanted[name] if name in wanted else vals.get(name)
        if ty == "audio":
            if not loc["audio"]:
                continue
            s0 = loc["audio"][0]
            got = new[s0 + 4:s0 + 4 + _u32(new, s0)].decode("ascii", "replace")
        elif ty == "list":
            if off is None:
                continue
            p = off + sum(len(nb) - ol for s, ol, nb in splices if s + ol <= off)
            n = _u32(new, p)
            got = ["%08X" % _u32(new, p + 4 + 4 * i) for i in range(n)] if n <= AFFLIST_MAX else None
        elif ty == "attach":
            if off is None:
                continue
            p = off + sum(len(nb) - ol for s, ol, nb in splices if s + ol <= off)
            got, end = attach_parse(new, p)
            if got is not None and end != len(new) - ATTACH_TAIL:
                raise FieldError("the attachment list no longer ends %d bytes short of the record - refusing"
                                 % ATTACH_TAIL)
        elif off is None:
            continue
        elif ty == "species":
            sp = _u32(new, at(off))
            got = SPECIES_BY_HASH.get(sp, "%08X" % sp)
        elif ty in ("geo", "icon", "gib"):
            got = "%08X" % _u32(new, at(off))
        else:
            got = _read(new, at(off), ty)
        if not _eq(ty, got, want):
            if name in wanted:
                raise FieldError("read-back mismatch on %s: wanted %r, record now says %r" % (name, want, got))
            raise FieldError("%s changed without being edited (%r -> %r) - refusing" % (name, want, got))
    delta = sum(len(nb) - ol for s, ol, nb in splices)
    if len(new) != len(b) + delta:
        raise FieldError("record length changed by %d, expected %d - refusing" % (len(new) - len(b), delta))
    for i in range(len(b)):
        if in_splice(i):
            continue
        if i not in touched and new[at(i)] != b[i]:
            raise FieldError("byte +%d changed without belonging to an edited field - refusing" % i)
    if list_new is not None:
        # The tail must still PARSE: new count, new entries, then flags and
        # spawners exactly where the new count puts them.
        A2 = at(loc["A"])
        ents, f2, t2 = tail_layout(new, A2, known)
        if ents is None or ["%08X" % x for x in ents] != list_new:
            raise FieldError("the tail does not re-parse after the m_affList edit - refusing")
        if f2 != at(loc["flags"]) or t2 != at(loc["tail"]):
            raise FieldError("flags/drops did not move with the m_affList edit - refusing")

    if warnings is not None:
        nvals = read_values(new, known, h2p)[0]
        drift = [n for n, v in vals.items()
                 if not _eq(table[n][1] if n in table else None, nvals.get(n), wanted[n] if n in wanted else v)]
        if drift:
            warnings.append("the record is verified byte for byte, but the field locators read %d field(s) "
                            "differently on it (%s), so the Character Creator may show this character's "
                            "values wrongly" % (len(drift), ", ".join(drift[:4])))
    return new, changes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["read"])
    ap.add_argument("hash")
    a = ap.parse_args()
    import resolve_assets as RA
    from ensure_asset import region_index
    h = int(a.hash, 16)
    h2p = {}
    for q in RA.harvest():
        h2p.setdefault(game_hash(q), q)
    rs, known = CA.roster()
    for r in NUMBERED:
        idx = region_index(r)
        if h in idx:
            vals, why, loc = read_values(idx[h][1]["desc"], known, h2p)
            print(json.dumps({"region": r, "layout": loc["layout"], "values": vals,
                              "unwritable": {k: v for k, v in why.items() if v}}, indent=1))
            return 0
    sys.exit("%08X not found in any numbered region" % h)


if __name__ == "__main__":
    sys.exit(main() or 0)
