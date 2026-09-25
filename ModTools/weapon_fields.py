r"""Weapon record fields: read them out of a weapon, write them into a clone.

The Weapon Creator's write layer - the counterpart of char_fields.py, built the
same way for the same reason: a dial with no locator is never offered, and
apply() refuses unless every edited field reads back AND every byte outside the
edited fields is unchanged.

WHAT A WEAPON IS MADE OF (retail, measured 2026-09-12 over all 78 records)

    weapon record          kind 7, 417-427 B. A packed layout fixed from +8 to
                           +306, then the weapon TYPE as a length-prefixed
                           string at +307 - "Club", "Firearm", "Turret", "Jump",
                           "Sekto", "Shock", "SpawnGun", "BomberBomb",
                           "gloktigimelee", "gloktigiranged". Size is not type
                           (two "Club"-sized records are Jump). Everything after
                           the string moves with its length: T = 311 + len.
      the tail (T..)       NPCWeaponPrefs' own fields, in the engine's order:
                           fire rate, fire-from-textkeys, reload time, reload
                           max, hit cone x3, min distance, then m_spawnPref - a
                           length-prefixed STRING ("Sleg" on the sloghandler's
                           spawn gun, empty elsewhere) plus a dword - then
                           countdown, accuracy width, miss time. The tail is
                           102 bytes + the spawn-pref string, on 79 of 79.
      +12 -> effect pref   kind 7, 222 or 226 B, never global. 11 of 59 are
                           shared by several weapons, so an effect edit ALWAYS
                           writes a new effect pref rather than touching one.
        +8   -> projectile mesh    a .geo, NULL on melee; three are global
        +117 -> impact sound set   two cue names; the cues are in the global
                                   audio banks, so nothing is ported for them
        +166 -> impact effect set  up to three EffectMixDef BASE names
        ~30 other slots            particle prefs, region or global_prefs.smb

HOW THE CLIP / TIMING / AIM FIELDS WERE LOCATED. The AT3 Official preset has
written clipCapacity, fireRate, reloadTime, accuracyWidth and missTime into
weapon records all along; its `Off` is the descriptor offset plus the 20-byte
record header. Read that way they land at +174, T+0, T+5, T+41 and T+45 - and
T+0/T+5/T+41/T+45 are exactly where the engine's NPCWeaponPrefs order puts
m_fireRate, m_reloadTime, m_accuracyWidth and m_missTime. Their neighbours are
named from the same order. NOTE the SWSE reflection schema lists each class in
REVERSE file order; read backwards from the confirmed m_maxKnockSpeed (+144),
it puts m_areaOfEffect at +135 and m_explosionSpeed at +127, which are
non-zero on exactly the exploding weapons.

THE PATH TRAP, A THIRD TIME. An impact effect set names bases such as
"EffectMixDef\bigHit". The engine appends the surface that was hit and loads

    \data\prefs\Effects\EffectMixDef\<base>_<surface>.txt

for flesh / metal / rock / snow / water / wood. Those are ordinary PER-REGION
records that no dword points at, so a dword closure never ports them. needs()
adds them, and follows embedded paths as well as dwords.

NULL is 0x2DFD1072 = game_hash(""), the engine's "no reference".

FIELD NAMES. m_* names come from the engine's reflection order or from
WEAPON_DIALS.md; each carries its evidence in the launcher tooltip. Fields with
a test history but no established meaning carry their offset instead.

    python weapon_fields.py read 5D994255
    python weapon_fields.py survey
"""
import argparse, glob, json, math, os, re, struct, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from gamehash import game_hash
from ensure_asset import closure

ROOT = os.path.dirname(HERE)
NULL = 0x2DFD1072
BS = chr(92)
TYPE_AT = 307
TAIL_BASE = 102
SPAWNPREF_AT = 29          # T-relative
EFFECT_SIZES = (222, 226)
MIX_ROOT = BS + "data" + BS + "prefs" + BS + "Effects" + BS + "EffectMixDef" + BS
SURFACES = ("flesh", "metal", "rock", "snow", "water", "wood")
NUMBERED = ("00", "01", "02", "02a", "03", "04", "05", "06")


class FieldError(Exception):
    pass


# (name, anchor, offset, type). anchor: "abs" = record start, "T" = end of the
# type string, "P" = end of the spawn-pref block (string + its dword).
FIRING = (("m_range", "abs", 16, "f"), ("m_arcAngle", "abs", 20, "f"), ("m_arcDist", "abs", 24, "f"),
          ("m_arcTime", "abs", 28, "f"), ("m_speed", "abs", 46, "f"), ("m_gravity", "abs", 50, "f"),
          ("m_pitchClamp", "abs", 72, "f"), ("m_maxLeadVel", "abs", 76, "f"), ("homing_228", "abs", 228, "f"))
DAMAGE = (("m_damage", "abs", 93, "f"), ("potent_089", "abs", 89, "f"), ("m_stamina", "abs", 103, "f"),
          ("m_maxKnockSpeed", "abs", 144, "f"), ("m_bounceParameter", "abs", 255, "f"))
CLIP = (("m_clipCapacity", "abs", 174, "i"), ("m_clipCapacityMin", "abs", 170, "i"),
        ("m_totalCapacity", "abs", 178, "i"))
TIMING = (("m_fireRate", "T", 0, "f"), ("m_fireFromTextkeys", "T", 4, "b"),
          ("m_reloadTime", "T", 5, "f"), ("m_reloadTimeMax", "T", 9, "f"))
AIM = (("m_minDistance", "T", 25, "f"), ("m_accuracyWidth", "P", 4, "f"), ("m_missTime", "P", 8, "f"))
EXPLOSION = (("m_explosionDuration", "abs", 123, "f"), ("m_explosionSpeed", "abs", 127, "f"),
             ("m_explosionFriendAffectMultiplier", "abs", 131, "f"), ("m_areaOfEffect", "abs", 135, "f"))
UNKNOWN = (("unk_107", "abs", 107, "f"), ("unk_111", "abs", 111, "f"), ("unk_152", "abs", 152, "f"),
           ("unk_216", "abs", 216, "f"))
FIELDS = FIRING + DAMAGE + CLIP + TIMING + AIM + EXPLOSION + UNKNOWN
INT_RANGE = (-1, 1000000)
# Slots in the EFFECT pref, and what each must point at.
EFFECT = (("fx_projectile", 8, "geo"), ("fx_impactSounds", 117, "snd"),
          ("fx_impactEffects", 166, "mix"))
SLOT_LABEL = {"geo": "projectile mesh (.geo)", "snd": "impact sound set",
              "mix": "impact effect set"}
# The one type conversion proven in game (WEAPON_DIALS: "Converting a Turret
# into a rifle", 2026-09-07). Nothing else is offered.
RETYPE = {"Turret": ("Firearm",)}


def _u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def strings(b):
    """Every length-prefixed printable string: [(offset of its prefix, text)]."""
    out, o = [], 0
    while o < len(b) - 4:
        n = _u32(b, o)
        if 2 <= n <= 200 and o + 4 + n <= len(b):
            s = b[o + 4:o + 4 + n]
            if all(32 <= c < 127 for c in s):
                out.append((o, s.decode()))
                o += 4 + n
                continue
        o += 1
    return out


def weapon_type(b):
    """The type string at +307, or None when this is not a weapon record."""
    if len(b) < TYPE_AT + 8:
        return None
    n = _u32(b, TYPE_AT)
    if not 3 <= n <= 24 or TYPE_AT + 4 + n > len(b):
        return None
    s = b[TYPE_AT + 4:TYPE_AT + 4 + n]
    if not all(65 <= c <= 90 or 97 <= c <= 122 for c in s):
        return None
    T = TYPE_AT + 4 + n
    if len(b) < T + SPAWNPREF_AT + 4:
        return None
    sl = _u32(b, T + SPAWNPREF_AT)
    if sl > 64 or len(b) - T != TAIL_BASE + sl:
        return None
    if not all(32 <= c < 127 for c in b[T + SPAWNPREF_AT + 4:T + SPAWNPREF_AT + 4 + sl]):
        return None
    return s.decode()


def locate(b):
    t = weapon_type(b)
    if t is None:
        return {"ok": False, "type": None, "T": None, "P": None,
                "why": "no weapon type string at +307 - not a weapon record"}
    T = TYPE_AT + 4 + len(t)
    sl = _u32(b, T + SPAWNPREF_AT)
    return {"ok": True, "type": t, "T": T, "P": T + SPAWNPREF_AT + 4 + sl + 4,
            "spawnPref": b[T + SPAWNPREF_AT + 4:T + SPAWNPREF_AT + 4 + sl].decode("latin1"), "why": None}


def positions(info):
    """name -> (absolute offset, type) for this record's layout."""
    base = {"abs": 0, "T": info["T"], "P": info["P"]}
    return {name: (base[anc] + off, ty) for name, anc, off, ty in FIELDS}


def is_weapon(rec):
    return bool(rec) and rec["kind"] == 7 and weapon_type(rec["desc"]) is not None


# ---------------------------------------------------------------- effect assets
def mix_bases(desc):
    """The EffectMixDef base names an impact effect set carries, in order."""
    return [s.split(BS, 1)[1] for _, s in strings(desc)
            if s[:13].lower() == "effectmixdef" + BS and BS in s]


def composed(desc):
    """Hashes the engine composes from this record's EffectMixDef names.

    Candidates only - the caller keeps the ones a region actually holds.
    """
    out = []
    for base in mix_bases(desc):
        for s in SURFACES + ("",):
            h = game_hash(MIX_ROOT + base + ("_" + s if s else "") + ".txt")
            if h not in out:
                out.append(h)
    return out


def paths_in(desc):
    return [s for _, s in strings(desc)
            if (BS in s or "/" in s) and re.search(r"\.[A-Za-z0-9]{2,4}$", s)]


def needs(key, idx):
    """`key` plus everything it needs resident, from one region's index.

    closure() follows dwords. This adds what dwords cannot see: records named
    by embedded PATH, and the per-surface impact records composed from
    EffectMixDef names. Order is discovery order, `key` first.
    """
    out, todo = [], [key]
    while todo:
        h = todo.pop(0)
        if h in out or h not in idx:
            continue
        for x in closure(h, idx):
            if x in out:
                continue
            out.append(x)
            d = idx[x][1]["desc"]
            extra = [game_hash(p) for p in paths_in(d)]
            if idx[x][1]["kind"] == 7:
                extra += composed(d)
            for y in extra:
                if y in idx and y not in out:
                    todo.append(y)
    return out


def slot_kind(h, desc_of, h2p):
    """What an effect-slot dword points at: null / geo / snd / mix, or None."""
    if h in (NULL, 0):
        return "null"
    q = (h2p or {}).get(h)
    if q and q.lower().endswith(".geo"):
        return "geo"
    d = desc_of(h) if desc_of else None
    if d is None:
        return None
    ss = [s for _, s in strings(d)]
    if not ss:
        return None
    if all(s[:13].lower() == "effectmixdef" + BS for s in ss):
        return "mix"
    if all(re.match(r"^[A-Za-z0-9_]+$", s) for s in ss):
        return "snd"
    return None


def asset_label(h, desc_of, h2p):
    """A human label for a projectile / sound set / effect set."""
    if h in (NULL, 0):
        return "(none)"
    q = (h2p or {}).get(h)
    if q:
        return q.replace("/", BS).split(BS)[-1]
    d = desc_of(h) if desc_of else None
    if d is None:
        return "%08X" % h
    seen = []
    for _, s in strings(d):
        s = s.split(BS, 1)[1] if s[:13].lower() == "effectmixdef" + BS else s
        if s not in seen:
            seen.append(s)
    return " / ".join(seen) or "%08X" % h


# ---------------------------------------------------------------- reading
def _read_typed(b, off, ty):
    """(value, reason) - value None with a reason when implausible here."""
    if off < 0 or off + (1 if ty == "b" else 4) > len(b):
        return None, "past the end of the record"
    if ty == "f":
        v = struct.unpack_from("<f", b, off)[0]
        if math.isfinite(v) and abs(v) <= 1e7:
            return round(v, 6), None
        return None, "+%d is not a plausible float on this record" % off
    if ty == "i":
        v = struct.unpack_from("<i", b, off)[0]
        if INT_RANGE[0] <= v <= INT_RANGE[1]:
            return v, None
        return None, "+%d is not a plausible count on this record (%d)" % (off, v)
    v = b[off]
    return (v, None) if v in (0, 1) else (None, "+%d is not a boolean on this record (%d)" % (off, v))


def read_effect(e, desc_of=None, h2p=None):
    """(values, why) for the three mapped slots of an EFFECT pref."""
    vals, why = {}, {}
    for name, off, ty in EFFECT:
        if len(e) not in EFFECT_SIZES:
            vals[name], why[name] = None, "effect pref is %d bytes - not a known layout" % len(e)
            continue
        h = _u32(e, off)
        if len(e) == 226 and name != "fx_projectile":
            # The three 226 B prefs (both fuzzle weapons, the gloktigi ranged)
            # carry four extra bytes before the impact slots: their effect set
            # sits at +170, and +166 holds -1.0. Where the sound slot went is
            # not verified, so neither is offered rather than read at a guess.
            vals[name] = None
            why[name] = ("226-byte effect pref (fuzzle / gloktigi weapons): the impact slots are "
                         "shifted and their exact positions are not verified")
            continue
        vals[name] = None if h in (NULL, 0) else "%08X" % h
        k = slot_kind(h, desc_of, h2p)
        why[name] = None if k in ("null", ty) else (
            "slot +%d holds %08X, which is not a %s - this effect pref is laid out differently"
            % (off, h, SLOT_LABEL[ty]))
    return vals, why


def read_values(b, desc_of=None, h2p=None):
    """(values, why, info) for a WEAPON record - why[name] is None where writable.

    With `desc_of` (hash -> descriptor or None) the weapon's effect-pref slots
    are read too, so one call gives the Weapon Creator everything it shows.
    """
    info = locate(b)
    vals, why = {}, {}
    if not info["ok"]:
        return vals, why, info
    for name, (off, ty) in positions(info).items():
        vals[name], why[name] = _read_typed(b, off, ty)
    ep = _u32(b, 12)
    vals["m_effectPref"] = None if ep in (NULL, 0) else "%08X" % ep
    why["m_effectPref"] = "set through the projectile / sound / impact choices, not directly"
    vals["m_weaponType"] = info["type"]
    why["m_weaponType"] = (None if info["type"] in RETYPE else
                           "only a Turret can be retyped (to Firearm) - the one conversion proven in game")
    if desc_of is not None:
        e = desc_of(ep) if ep not in (NULL, 0) else None
        if e is None:
            for name, off, ty in EFFECT:
                vals[name] = None
                why[name] = "this weapon's effect pref %08X is not in the install" % ep
        else:
            ev, ew = read_effect(e, desc_of, h2p)
            vals.update(ev)
            why.update(ew)
    return vals, why, info


# ---------------------------------------------------------------- writing
def _same(a, b):
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, float) or isinstance(b, float):
        try:
            a, b = float(a), float(b)
        except (TypeError, ValueError):
            return False
        return abs(a - b) <= 1e-4 * max(1.0, abs(b))
    return str(a).upper() == str(b).upper()


def _hash_or_none(v):
    if v in (None, "", "NULL", "(none)", "(nothing)"):
        return None
    return "%08X" % int(str(v), 16)


def _norm(name, ty, new):
    try:
        if new in (None, ""):
            raise ValueError
        if ty == "f":
            v = float(new)
            if not (math.isfinite(v) and abs(v) <= 1e7):
                raise ValueError
            return v
        v = float(new)
        if v != int(v):
            raise ValueError
        v = int(v)
    except (TypeError, ValueError):
        raise FieldError("%s: %r is not a valid %s" % (name, new, {"f": "number", "i": "whole number",
                                                                   "b": "0 or 1"}[ty]))
    if ty == "i" and not INT_RANGE[0] <= v <= INT_RANGE[1]:
        raise FieldError("%s must be a whole number %d..%d" % (name, INT_RANGE[0], INT_RANGE[1]))
    if ty == "b" and v not in (0, 1):
        raise FieldError("%s must be 0 or 1" % name)
    return v


def apply(b, edits, desc_of=None, h2p=None):
    """(new_bytes, changes) for a WEAPON record. Raises FieldError rather than write anything wrong."""
    vals, why, info = read_values(b)
    if not info["ok"]:
        raise FieldError(info["why"])
    pos = positions(info)
    out = bytearray(b)
    changes, wanted, touched, newtype = [], {}, set(), None
    for name, new in edits.items():
        if name == "m_effectPref":
            try:
                same = _same(_hash_or_none(new), vals.get(name))
            except ValueError:
                same = False
            if same:
                wanted[name] = vals.get(name)
                continue
            raise FieldError("m_effectPref is %s" % why[name])
        if name == "m_weaponType":
            nv = str(new or "").strip()
            if nv == info["type"]:
                wanted[name] = nv
                continue
            if why[name]:
                raise FieldError("m_weaponType cannot be changed on this record: %s" % why[name])
            if nv not in RETYPE[info["type"]]:
                raise FieldError("a %s can only become %s, not %r"
                                 % (info["type"], " or ".join(RETYPE[info["type"]]), nv))
            newtype = wanted[name] = nv
            continue
        if name not in pos:
            raise FieldError("unknown weapon field %s" % name)
        off, ty = pos[name]
        nv = _norm(name, ty, new)
        # A value equal to what the record holds is not an edit, even on a field
        # this record cannot have written - the launcher sends the whole form.
        if _same(nv, vals.get(name)):
            wanted[name] = vals.get(name)
            continue
        if why.get(name):
            raise FieldError("%s cannot be written on this record: %s" % (name, why[name]))
        if ty == "f":
            struct.pack_into("<f", out, off, nv)
        elif ty == "i":
            struct.pack_into("<i", out, off, nv)
        else:
            out[off] = nv
        touched.update(range(off, off + (1 if ty == "b" else 4)))
        wanted[name] = nv
        changes.append((name, vals.get(name), nv))
    if newtype:
        enc = newtype.encode("ascii")
        out = out[:TYPE_AT] + struct.pack("<I", len(enc)) + enc + out[info["T"]:]
        changes.append(("m_weaponType", info["type"], newtype))

    new = bytes(out)
    ninfo = locate(new)
    if not ninfo["ok"]:
        raise FieldError("the edited record no longer reads as a weapon - refusing")
    shift = ninfo["T"] - info["T"]
    npos = positions(ninfo)
    for name in pos:
        got = _read_typed(new, npos[name][0], npos[name][1])[0]
        want = wanted[name] if name in wanted else vals.get(name)
        if not _same(got, want):
            if name in wanted:
                raise FieldError("read-back mismatch on %s: wanted %r, record now says %r" % (name, want, got))
            raise FieldError("%s changed without being edited (%r -> %r) - refusing" % (name, want, got))
    if ninfo["type"] != (newtype or info["type"]):
        raise FieldError("weapon type reads back as %r - refusing" % ninfo["type"])
    # Stronger than field read-back: most of a weapon record is unmapped, so
    # every byte outside the edited fields must be exactly as it was (the tail
    # moves as a block when the type string changes length).
    if len(new) != len(b) + shift:
        raise FieldError("record length changed by %d, expected %d - refusing" % (len(new) - len(b), shift))
    for i in range(len(b)):
        if TYPE_AT <= i < info["T"]:
            continue
        j = i if i < TYPE_AT else i + shift
        if i not in touched and new[j] != b[i]:
            raise FieldError("byte +%d changed without belonging to an edited field - refusing" % i)
    return new, changes


def apply_effect(e, edits, desc_of=None, h2p=None):
    """(new_bytes, changes) for an EFFECT pref. Raises FieldError rather than write anything wrong."""
    if len(e) not in EFFECT_SIZES:
        raise FieldError("not an effect pref (%d bytes)" % len(e))
    vals, why = read_effect(e, desc_of, h2p)
    table = {n: (o, t) for n, o, t in EFFECT}
    out = bytearray(e)
    changes, wanted, touched = [], {}, set()
    for name, new in edits.items():
        if name not in table:
            raise FieldError("unknown effect field %s" % name)
        off, ty = table[name]
        try:
            nv = _hash_or_none(new)
        except ValueError:
            raise FieldError("%s: %r is not a hash" % (name, new))
        if _same(nv, vals.get(name)):
            wanted[name] = nv
            continue
        if why.get(name):
            raise FieldError("%s cannot be written on this effect pref: %s" % (name, why[name]))
        h = NULL if nv is None else int(nv, 16)
        k = slot_kind(h, desc_of, h2p)
        if k not in ("null", ty):
            raise FieldError("%s: %s is not a %s" % (name, nv, SLOT_LABEL[ty]))
        struct.pack_into("<I", out, off, h)
        touched.update(range(off, off + 4))
        wanted[name] = nv
        changes.append((name, vals.get(name), nv))
    new = bytes(out)
    nvals, nwhy = read_effect(new, desc_of, h2p)
    for name, v in wanted.items():
        if not _same(nvals.get(name), v):
            raise FieldError("read-back mismatch on %s: wanted %r, got %r" % (name, v, nvals.get(name)))
    moved = [i for i in range(len(e)) if new[i] != e[i] and i not in touched]
    if moved:
        raise FieldError("effect pref bytes outside the edited slots changed (first at +%d) - refusing" % moved[0])
    return new, changes


# ---------------------------------------------------------------- CLI
def _install_index():
    """hash -> (where, record) over every numbered region and data/global."""
    import rebuild_bundle as RB
    from ensure_asset import region_index
    out = {}
    for r in NUMBERED:
        for h, (fns, rec) in region_index(r).items():
            out.setdefault(h, ("region_" + r, rec))
    for p in glob.glob(os.path.join(ROOT, "data", "global", "*.smb")):
        try:
            for rec in RB.parse(open(p, "rb").read())[1]:
                out.setdefault(rec["hash"], (os.path.basename(p), rec))
        except (Exception, SystemExit):
            continue
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["read", "survey"])
    ap.add_argument("hash", nargs="?")
    a = ap.parse_args()
    import resolve_assets as RA
    h2p = {}
    for q in RA.harvest():
        h2p.setdefault(game_hash(q), q)
    ix = _install_index()
    desc_of = lambda h: ix[h][1]["desc"] if h in ix else None
    if a.action == "read":
        h = int(a.hash, 16)
        if h not in ix:
            sys.exit("%08X is not in the install" % h)
        vals, why, info = read_values(ix[h][1]["desc"], desc_of, h2p)
        if not info["ok"]:
            sys.exit("%08X: %s" % (h, info["why"]))
        print(json.dumps({"where": ix[h][0], "type": info["type"], "spawnPref": info["spawnPref"],
                          "values": vals, "unwritable": {k: v for k, v in why.items() if v}}, indent=1))
        return 0
    # survey: coverage, plus the no-op and single-edit round trips on every weapon
    weapons = {h: w for h, w in ix.items() if is_weapon(w[1])}
    cover, fails = {}, []
    for h, (where, rec) in sorted(weapons.items()):
        b = rec["desc"]
        vals, why, info = read_values(b, desc_of, h2p)
        for k, v in why.items():
            cover.setdefault(k, [0, 0])[0 if not v else 1] += 1
        try:
            if apply(b, {k: v for k, v in vals.items() if not k.startswith("fx_")}, desc_of, h2p)[0] != b:
                fails.append("%08X no-op apply changed bytes" % h)
            for name, anc, off, ty in FIELDS:
                if why[name]:
                    continue
                alt = vals[name] + 1.5 if ty == "f" else ((5 if vals[name] < 0 else vals[name] + 1) if ty == "i" else 1 - vals[name])
                nb, ch = apply(b, {name: alt}, desc_of, h2p)
                if sum(1 for i in range(len(b)) if nb[i] != b[i]) > 4:
                    fails.append("%08X %s moved more than 4 bytes" % (h, name))
            if info["type"] in RETYPE:
                nb, ch = apply(b, {"m_weaponType": RETYPE[info["type"]][0], "m_reloadTime": 2.5,
                                   "m_clipCapacity": 12}, desc_of, h2p)
                if len(nb) != len(b) + len(RETYPE[info["type"]][0]) - len(info["type"]):
                    fails.append("%08X retype length wrong" % h)
            ep = _u32(b, 12)
            if ep in ix and not why.get("fx_projectile"):
                e = ix[ep][1]["desc"]
                if apply_effect(e, {n: vals[n] for n, o, t in EFFECT}, desc_of, h2p)[0] != e:
                    fails.append("%08X no-op effect apply changed bytes" % h)
        except FieldError as ex:
            fails.append("%08X %s" % (h, ex))
    print("%d weapon records across the install" % len(weapons))
    for k in sorted(cover):
        ok, bad = cover[k]
        print("   %-34s writable on %3d, not on %3d" % (k, ok, bad))
    print("round-trip failures: %d" % len(fails))
    for f in fails[:20]:
        print("   " + f)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main() or 0)
