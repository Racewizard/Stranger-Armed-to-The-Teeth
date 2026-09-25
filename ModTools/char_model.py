r"""The Character Studio's compatibility graph - Layer 2, derived live.

WHAT THIS IS FOR

The studio's Anatomy tab is four dropdowns that constrain each other:

    Skeletal Species  ->  Behavioral Template  ->  Character Geometry
                                              ->  eligible weapon kinds

None of that is stored anywhere. It is DERIVED, and the derivation is the
whole point of this module - a hand-maintained table would go stale exactly
the way the stored RecOff values and GlobalCatalogue.csv did.

THE CHAIN, and why each link is trustworthy

    character record
      -> m_animationConfigFile           a PATH, read by char_anchor.cfg()
      -> game_hash(path)                 the compiled config record
      -> its clip dwords                 resolve via resolve_assets.harvest()
      -> /data/geometry/characters/<X>/  X is the SKELETON

Verified on outlawNailer: 104 clip references, 100% `minionc`. Every step is
retail data; nothing here reads the prototype tree or anything derived from
it (see the note on slot names below).

WEAPON KIND IS NOT WEAPON CLASS

at3names.WTYPE maps a weapon record's SIZE to a label, and 420 bytes is
called "Firearm". That class actually holds seventeen different things:

    OutlawShooter.geo x9   cruise_missle.geo x4   OutlawMortar.geo x3
    NativeCatapult.geo x3  OutlawThrowingKnife.geo x1  JoMommaHatchet.geo x1
    native_arrow.geo x2    ...

A cutter's throwing knife and a Packrat's cruise missile are the same class.
So eligibility is reported by PROJECTILE MESH, which is the thing a user
actually means by "kind of weapon", and which is what makes the
mortar-fires-a-throwing-knife failure visible in data instead of only in game.

WHAT THIS MODULE DOES NOT DO

It does not refuse anything. Missing animation degrades gracefully in this
engine - a character with no bounty clip can still be bountied, it just
T-poses - so "the template has no clips for X" is reported as a NOTE, never
as a gate. The only thing the UI should grey out is a slot the template's
characters never carry at all, which is pointless rather than dangerous.

Slot NAMES are not available: retail ships animation configs with the names
stripped, storing clips positionally. Naming those positions would need the
prototype's slot order, which is out of bounds. So capabilities are matched on
clip FILENAME, which is reliable for bounty/bola/chipmunk/swim and unreliable
for melee (the nailer's melee clips are `mc_fireUB`/`mc_readyUB`, with no
"melee" in the name). Only the reliable families are reported.

PROVENANCE IS REPORTED, NOT ENFORCED

`utility/empty` holds a nailer wearing a mortar and Boilz Booty's club -
a this-project experiment. Derived naively it teaches the studio that nailers
take rifles. Rather than filter such records out (porting between regions is a
solved operation here, so a ported record is legitimate evidence), every
character carries `origin`: stock / custom / workspace. Counts are given both
ways and the UI chooses.

    python char_model.py                    human-readable audit
    python char_model.py --json <path>      emit the graph for the launcher
    python char_model.py --why minionc      explain one skeleton's options
    python char_model.py --unknowns         the Experimental tab's candidates
"""
import argparse, collections, glob, io, json, os, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import char_anchor as CA
import rebuild_bundle as RB
import resolve_assets as RA
import at3names
from gamehash import game_hash

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BS = chr(92)
NULL = 0x2DFD1072

# Regions the game shipped. `utility` and `emptygulch` are this project's
# workspaces - at3catalogue.py draws the same line for the same reason.
SHIPPED = ("region_00", "region_01", "region_02", "region_02a",
           "region_03", "region_04", "region_05", "region_06")

SPECIES = {game_hash("outlaw"): ("outlaw", True),
           game_hash("wolvark"): ("wolvark", True),
           game_hash("slog"): ("slog", True),
           game_hash("native"): ("native", False),
           game_hash("townsfolk"): ("townsfolk", False)}

# Clip-filename families. ONLY families that resolve reliably by filename -
# see the module docstring. These are informational; they gate nothing.
FAMILIES = {"bounty": ("bounty",), "bola": ("bolo", "bola"),
            "chipmunk": ("sendto", "distracted"), "swim": ("swim",)}

# ANC-relative fields, all confirmed in game or against the engine's own
# reflection dump (SWSE Files/swse/research/FIELD_OFFSETS.tsv). `w` is the
# byte width. Unconfirmed fields are deliberately absent - they surface
# through --unknowns instead, which is what the Experimental tab consumes.
FIELDS = [
    ("m_geoScaleMin", 8, 4, "f"), ("m_geoScaleMax", 12, 4, "f"),
    ("m_health", 16, 4, "f"), ("m_healthRecoverTime", 20, 4, "f"),
    ("m_stamina", 24, 4, "f"), ("m_staminaRecoverTime", 28, 4, "f"),
    ("m_exhaustTime", 32, 4, "f"), ("m_exhaustedRecoverMultiplier", 36, 4, "f"),
    ("m_onDeathGib", 40, 1, "b"), ("m_allowOnDeathGibFromBolts", 41, 1, "b"),
    ("m_onGibSpawnNPC", 42, 4, "h"), ("m_autoAimRadius", 46, 4, "f"),
    ("m_hurtReaction", 50, 4, "i"), ("m_meleeWeapon", 54, 4, "h"),
    ("m_rangedWeapon", 58, 4, "h"), ("m_canBeBountied", 62, 1, "b"),
    # FLOATS, not ints. The raw dwords look like huge integers - 1092616192 is
    # 0x41200000 is 10.0f - and an earlier version of this table said "i",
    # which would have written 10 as 0x0000000A and paid out 1.4e-44 moolah.
    ("m_captureMoolah", 63, 4, "f"), ("m_killMoolah", 67, 4, "f"),
    # CONFIRMED 2026-09-12 by behavioural signature, which is the strongest
    # evidence available here (CHARACTER_DIALS: "behavioural signatures beat
    # byte analysis"). The player stated independently that wolvarks are the
    # only characters giving an AMMO bounty, plus MovieBoss. ANC+71 is
    # non-zero on exactly nine records: all seven wolvarks, MovieBoss (0.05)
    # and shocktank (0.5, a wolvark machine). Zero on the other 64.
    #
    # It is a FRACTION, not a count - every value is 0.05/0.1/0.2/0.3/0.5.
    #
    # Moolah and ammo are independent, and MovieBoss proves they coexist:
    # capture 200.0, kill 100.0 AND ammo 0.05. Otherwise the game keeps them
    # disjoint - wolvarks pay ammo and zero moolah, outlaws the reverse.
    ("m_bountyAmmoBoost", 71, 4, "f"),
    ("m_bountyEnduranceBoost", 75, 4, "f"),
    ("m_respondsToDamageDynamite", 141, 1, "b"),
    ("m_respondsToImmobilizeSkunkBomb", 142, 1, "b"),
    ("m_respondsToImmobilizeSpiderBola", 143, 1, "b"),
    ("m_respondsToTrapFuzzle", 144, 1, "b"),
    ("m_collectableSpawnLimit", 145, 4, "i"),
    ("m_onDamageCollectableSpawner", 149, 4, "h"),
    ("m_onExhaustCollectableSpawner", 153, 4, "h"),
    ("m_onDeathCollectableSpawner", 157, 4, "h"),
    ("m_onSteefRamAliveCollectableSpawner", 161, 4, "h"),
    ("m_onStrangerRamAliveCollectableSpawner", 165, 4, "h"),
    ("m_onSteefRamDeadCollectableSpawner", 169, 4, "h"),
    ("m_onStrangerRamDeadCollectableSpawner", 173, 4, "h"),
]
# Absolute offsets - independent of the ANC anchor, so they hold even on the
# records char_anchor cannot resolve.
ABS_FIELDS = [("m_species", 12, 4, "h"),
              ("m_minRandomSpeechPitch", 52, 4, "i"),
              ("m_maxRandomSpeechPitch", 56, 4, "i")]

# The motion block - nine consecutive floats sitting BEFORE the animation
# config path. Offsets are relative to the run's own start (see motion_anchor),
# NOT to CFG: the block is a fixed distance from the record start, and CFG is
# the end of a variable-length path, so its CFG-relative position ranges from
# -81 to -104 across the roster. Anchoring it on CFG is what made an earlier
# survey report outlawNailer's mass as three different numbers.
MOTION_FIELDS = [
    ("m_motionSphereHeight", 0, 4, "f"), ("m_motionSphereRadius", 4, 4, "f"),
    ("m_bipedTurnSpeedDegrees", 8, 4, "f"),
    ("m_bipedTurnSpeedDegrees_Panic", 12, 4, "f"),
    ("m_mass", 16, 4, "f"), ("m_waterOffset", 20, 4, "f"),
    ("m_waterVelocityScale", 24, 4, "f"),
    ("m_timeTillIdle1", 28, 4, "f"), ("m_timeTillIdle2", 32, 4, "f"),
]

# The block AFTER the config path, anchored on the eight-value acceleration
# run at CFG+27. The player states these are identical on every character and
# apply only to the player - confirmed here, all five sampled characters carry
# byte-identical values. They are listed so the Experimental tab can show them
# and so nobody re-derives them, NOT because they are worth tuning.
INERT_CFG_FIELDS = [
    ("m_maxRadiansToRotateHiSpeed", 3), ("m_maxRadiansToRotateBasic", 7),
    ("m_maxRadiansToRotateLoSpeed", 11), ("m_jumpHeightMin", 15),
    ("m_jumpHeightMax", 19), ("m_jumpHeightSpeedScale", 23),
    ("m_accelLo_Walk", 27), ("m_accelHi_Walk", 31),
    ("m_accelLo_Trot", 35), ("m_accelHi_Trot", 39),
    ("m_accelLo_Canter", 43), ("m_accelHi_Canter", 47),
    ("m_accelLo_Run", 51), ("m_accelHi_Run", 55),
    ("m_steefVelDriveSpeedUp", 59), ("m_steefVelDriveSpeedDown", 63),
    ("m_skidToStopTrotCanterLerper", 67), ("m_skidToStopCanterRunLerper", 71),
    ("m_overVel_Walk", 75), ("m_overVel_Trot", 79),
    ("m_overVel_Canter", 83), ("m_overVel_Run", 87),
]


def motion_anchor(b, C):
    r"""Start of the motion run, or None when the record has no config path.

    STRUCTURAL. The nine motion floats and one more (m_gameSpeakTalkRestInterval)
    sit directly before the length prefix of the m_animationConfigFile string:
    the run starts exactly 40 bytes before it on all 126 character copies
    surveyed (2026-09-13). The previous SIGNATURE search accepted only plausible
    values - mass <= 20000, turn speed 10..2000 - so a user's own edit could hide
    the block: the landmine saved with mass 1,000,000 lost its whole BODY section.
    Values are only required to be finite here; they are the user's to choose.
    """
    if C is None:
        return None
    for L in range(2, 201):
        s = C - L - 4
        if s < 40:
            break
        if struct.unpack_from("<I", b, s)[0] == L and all(32 <= c < 127 for c in b[s + 4:C]):
            vals = struct.unpack_from("<10f", b, s - 40)
            return s - 40 if all(x == x and x not in (float("inf"), float("-inf")) for x in vals) else None
    return None

# (An earlier note here said m_bountyAmmoBoost and m_bountyEnduranceBoost were
# too unconfirmed to include. That was superseded on 2026-09-12 by the
# behavioural signature recorded beside them in FIELDS above - wolvarks,
# shocktank and MovieBoss, exactly the set the player named from play.)


def _basename(q):
    return q.replace("/", BS).split(BS)[-1]


def _chardir(q):
    """The /characters/<X>/ directory of an asset path, or None."""
    s = q.lower().replace(BS, "/")
    return s.split("/characters/")[1].split("/")[0] if "/characters/" in s else None


def load():
    """(names, rs, weap, by, h2p, where) - everything read from disk, once."""
    names, how, rs, weap, by = at3names.build()
    h2p = {}
    for q in RA.harvest():
        h2p.setdefault(game_hash(q), q)
    # at3names indexes data/bundles/*/*/*.smb. Animation configs and other
    # referenced records live outside that shape (data/global, deeper paths),
    # so widen the index or every config resolves as "missing".
    by = dict(by)
    where = collections.defaultdict(list)
    for p in glob.glob(os.path.join(ROOT, "data", "**", "*.smb"), recursive=True):
        if os.path.basename(p).count(".") > 1:
            continue
        try:
            recs = RB.parse(open(p, "rb").read())[1]
        except (Exception, SystemExit):
            continue
        rel = os.path.relpath(p, ROOT)
        for r in recs:
            by.setdefault(r["hash"], r)
            where[r["hash"]].append(rel)
    return names, rs, weap, by, h2p, where


def config_path(b):
    """The full m_animationConfigFile string, or None."""
    o = 0
    while o < len(b) - 4:
        n = struct.unpack_from("<I", b, o)[0]
        if 2 <= n <= 200 and o + 4 + n <= len(b):
            s = b[o + 4:o + 4 + n]
            if all(32 <= c < 127 for c in s):
                if b"MotionAnimConfig" in s:
                    return s.decode()
                o += 4 + n
                continue
        o += 1
    return None


def config_clips(cpath, by, h2p):
    """(skeleton, {family: count}, total clips) for one animation config."""
    ch = game_hash(cpath)
    if ch not in by:
        return None, {}, 0
    d = by[ch]["desc"]
    dirs, clips = collections.Counter(), set()
    for k in range(len(d) - 4):
        q = h2p.get(struct.unpack_from("<I", d, k)[0])
        if q and q.lower().endswith(".gr2"):
            x = _chardir(q)
            if x:
                dirs[x] += 1
                clips.add(_basename(q).lower())
    if not dirs:
        return None, {}, 0
    fams = {f: sum(1 for c in clips if any(k in c for k in keys))
            for f, keys in FAMILIES.items()}
    return dirs.most_common(1)[0][0], fams, len(clips)


def weapon_kind(h, weap, by, h2p):
    """What KIND of weapon this record is, in the terms a user thinks in.

    A ranged weapon's kind is its projectile mesh - that is the distinction
    the size class throws away (see the module docstring). A melee weapon has
    no projectile, so it falls back to the size class, which for melee is
    actually meaningful: Club / Shock / Gloktigi are different things.
    """
    if h not in weap:
        return "%08X" % h
    cls = at3names.wtype(weap[h]["desc"])
    ep = struct.unpack_from("<I", weap[h]["desc"], 12)[0]
    if ep in by:
        g = struct.unpack_from("<I", by[ep]["desc"], 8)[0]
        q = h2p.get(g)
        if q:
            return _basename(q)
    return cls or "%08X" % h


def origin_of(paths, h, custom):
    if h in custom:
        return "custom"
    if any(("%sbundles%s" % (BS, BS)) + r + BS in (p + BS) or
           (BS + r + BS) in p for p in paths for r in SHIPPED):
        return "stock"
    return "workspace"


def custom_hashes():
    r"""Hashes this project minted - the Hash column AND the ones named in Notes.

    A custom character drags dependencies with it: the killer clakker's row
    names its weapon, anim config, effects, edited clip and its moolah spawner
    E94574EE in prose. Only the Hash column was being read, so E94574EE - a
    record built for this project - was reported as `stock` and offered in the
    Rewards tab as though the game shipped it. It lives in region_01's tgl, so
    the region-path test cannot catch it either; that is the "not airtight"
    limitation of provenance-by-location, biting exactly where predicted.

    Hex tokens in Notes are therefore treated as custom dependencies, minus
    anything in ClonedFrom - those are the VANILLA donors and must not be
    relabelled as ours.
    """
    import csv, re
    p = os.path.join(ROOT, "StrangerAT3", "CustomHashes.csv")
    out, donors = set(), set()
    if not os.path.exists(p):
        return out
    with io.open(p, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            try:
                out.add(int((r.get("Hash") or "0"), 16))
            except ValueError:
                pass
            for tok in re.findall(r"\b[0-9A-Fa-f]{8}\b", r.get("ClonedFrom") or ""):
                donors.add(int(tok, 16))
            for tok in re.findall(r"\b[0-9A-F]{8}\b", r.get("Notes") or ""):
                out.add(int(tok, 16))
    return out - donors


def regions_of(paths):
    r"""Which shipped regions (plus the workspaces) hold a record.

    This is what the Residency tab runs on: a character can only be spawned
    where every asset it references already lives, because a copied record
    brings no geometry with it. Moolah_Large is native to region_02 and
    crashes on death anywhere else even after its prefs record is copied in.
    """
    out = set()
    for p in paths:
        q = BS + p + BS
        for r in SHIPPED:
            if (BS + r + BS) in q:
                out.add(r.replace("region_", ""))
        # utility only - emptygulch's copies exist on disk but are never loaded,
        # so reporting a record as "resident" there would be false.
        for w in ("utility",):
            if (BS + w + BS) in q:
                out.add(w)
    return sorted(out)


def build(loaded=None):
    """The graph: skeleton -> templates -> geometries, weapons, characters."""
    names, rs, weap, by, h2p, where = loaded or load()
    custom = custom_hashes()
    cfg_cache = {}
    known_all = set(by)
    import char_fields as CF   # lazy: char_fields imports this module
    skels = collections.defaultdict(
        lambda: {"templates": {}, "geometries": {}, "characters": 0, "worn": collections.Counter()})

    for h, (nm, C, A, b) in rs.items():
        # Skip the "stub" shape. char_anchor.anchor() returns None for the 15
        # records that carry a MotionAnimConfig but stop before the audioName
        # block - the live ammo and its effects (ArmadilloWeapon, FuzzleWeapon,
        # SquirrelWeapon, steef...). They have no health, no attachments and no
        # weapon slots, so they are not characters anyone can build. Leaving
        # them in put a `critters` skeleton with 17 "characters" at the top of
        # the studio's first dropdown. at3catalogue.py drops them for the same
        # reason.
        if A is None:
            continue
        cp = config_path(b)
        if not cp:
            continue
        if cp not in cfg_cache:
            cfg_cache[cp] = config_clips(cp, by, h2p)
        skel, fams, nclips = cfg_cache[cp]
        if skel is None:
            continue
        S = skels[skel]
        S["characters"] += 1
        T = S["templates"].setdefault(nm or "?", {
            "config": cp, "clips": nclips, "families": fams,
            "characters": [], "melee": collections.Counter(),
            "ranged": collections.Counter(), "melee_stock": collections.Counter(),
            "ranged_stock": collections.Counter()})

        org = origin_of(where.get(h, []), h, custom)
        # the body mesh: the one /characters/*.geo this record references
        geos = {}
        for k in range(len(b) - 4):
            v = struct.unpack_from("<I", b, k)[0]
            q = h2p.get(v)
            if q and q.lower().endswith(".geo") and _chardir(q):
                geos[_basename(q)] = v
        for g, gh in geos.items():
            # hash and residency travel with the mesh: choosing a mesh from a
            # sibling template means porting it if the target region lacks it
            S["geometries"].setdefault(g, {"origin": org, "templates": set(),
                                           "hash": "%08X" % gh,
                                           "regions": regions_of(where.get(gh, []))})
            S["geometries"][g]["templates"].add(nm or "?")
            if "bones" not in S["geometries"][g]:
                S["geometries"][g]["rig"], S["geometries"][g]["bones"] = rig_of(gh, by)

        rec = {"hash": "%08X" % h, "name": names.get(h, nm or "?"),
               "origin": org, "geometry": sorted(geos),
               "regions": regions_of(where.get(h, []))}
        # every asset this character needs, with where each one already lives.
        deps = []
        cfgh = game_hash(cp)
        deps.append({"what": "anim config", "hash": "%08X" % cfgh,
                     "name": _basename(cp),
                     "regions": regions_of(where.get(cfgh, []))})
        for k in range(max(0, len(b) - 4)):
            v = struct.unpack_from("<I", b, k)[0]
            q = h2p.get(v)
            if q and q.lower().endswith(".geo") and _chardir(q):
                deps.append({"what": "geometry", "hash": "%08X" % v,
                             "name": _basename(q),
                             "regions": regions_of(where.get(v, []))})
        if A is not None:
            for off, slot in ((54, "melee weapon"), (58, "ranged weapon")):
                if A + off + 4 > len(b):
                    continue
                w = struct.unpack_from("<I", b, A + off)[0]
                if w in (NULL, 0):
                    continue
                deps.append({"what": slot, "hash": "%08X" % w,
                             "name": str(names.get(w, "%08X" % w))[:40],
                             "regions": regions_of(where.get(w, []))})
        seen_dep = set()
        rec["deps"] = [d for d in deps
                       if not (d["hash"] in seen_dep or seen_dep.add(d["hash"]))]
        # The base's REAL field values, read through the same locators the
        # build writes through - so the Character Creator opens on what this
        # record actually carries instead of hardcoded placeholders, and knows
        # which fields cannot be located on it.
        fv, fwhy, floc = CF.read_values(b, known_all, h2p)
        rec["values"] = fv
        rec["unwritable"] = {k: v for k, v in fwhy.items() if v}
        rec["layout"] = floc["layout"]
        if org == "stock":
            for e in (fv.get("m_defaultAttachments") or []):
                S["worn"][e["bone"]] += 1
        # m_affList, named. Every entry is one of the player's ammo prefs;
        # the Immunities section shows the list read-only.
        rec["afflist"] = [{"hash": "%08X" % x,
                           "name": CF.AMMO_NAMES.get(x) or (_basename(h2p[x]).rsplit(".", 1)[0] if x in h2p
                                                            else "unnamed %08X" % x)}
                          for x in (floc["afflist"] or [])]
        if A is not None:
            sp = struct.unpack_from("<I", b, 12)[0] if len(b) >= 16 else 0
            nmsp, host = SPECIES.get(sp, ("", None))
            rec["species"] = nmsp
            rec["hostile"] = host
            for off, slot in ((54, "melee"), (58, "ranged")):
                if A + off + 4 > len(b):
                    continue
                w = struct.unpack_from("<I", b, A + off)[0]
                kind = "(none)" if w in (NULL, 0) else weapon_kind(w, weap, by, h2p)
                rec[slot] = kind
                T[slot][kind] += 1
                if org == "stock":
                    T[slot + "_stock"][kind] += 1
        T["characters"].append(rec)
    return skels, names


def weapons_catalogue(loaded):
    r"""The Weapon Creator's lists, and the Character Creator's weapon slots.

    Every weapon record with its REAL field values, read through
    weapon_fields.py - the locators build_weapon.py writes through - plus the
    three asset pickers (projectile mesh, impact sound set, impact effect set).
    Those offer exactly what shipped weapons use: an asset no weapon fires has
    no evidence it works as one.

    Which weapon TYPES belong in which character slot is also derived, from
    what stock characters actually carry - melee holds Club / Jump /
    gloktigimelee, ranged holds Firearm, BomberBomb, SpawnGun, Shock, Sekto and
    gloktigiranged. Turret is in neither: no character carries one, which is
    why the Weapon Creator offers the proven Turret -> Firearm conversion.
    """
    import weapon_fields as WF
    names, rs, weap, by, h2p, where = loaded
    custom = custom_hashes()
    desc_of = lambda h: by[h]["desc"] if h in by else None

    def is_global(h):
        return any(p.lower().startswith("data" + BS + "global" + BS) for p in where.get(h, []))

    slot_types = {"melee": collections.Counter(), "ranged": collections.Counter()}
    carried = collections.defaultdict(list)
    for h, (nm, C, A, b) in rs.items():
        if A is None:
            continue
        stock = origin_of(where.get(h, []), h, custom) == "stock"
        for off, slot in ((54, "melee"), (58, "ranged")):
            if A + off + 4 > len(b):
                continue
            w = struct.unpack_from("<I", b, A + off)[0]
            t = WF.weapon_type(weap[w]["desc"]) if w in weap else None
            if not t:
                continue
            if stock:
                slot_types[slot][t] += 1
            carried[w].append((str(names.get(h, nm or "?")), stock))

    assets = {"projectiles": {}, "impact_sounds": {}, "impact_effects": {}}
    slot_asset = (("fx_projectile", "projectiles"), ("fx_impactSounds", "impact_sounds"),
                  ("fx_impactEffects", "impact_effects"))
    out = []
    for h in sorted(weap):
        vals, why, info = WF.read_values(weap[h]["desc"], desc_of, h2p)
        if not info["ok"]:
            continue
        t = info["type"]
        for n, key in slot_asset:
            v = vals.get(n)
            if not v or why.get(n):
                continue
            a = assets[key].setdefault(v, {
                "hash": v, "label": WF.asset_label(int(v, 16), desc_of, h2p),
                "regions": regions_of(where.get(int(v, 16), [])),
                "global": is_global(int(v, 16)), "used_by": 0})
            a["used_by"] += 1
        ep = vals.get("m_effectPref")
        proj = vals.get("fx_projectile")
        out.append({
            "hash": "%08X" % h, "name": str(names.get(h, "%08X" % h)), "type": t,
            "slot": ("melee" if t in slot_types["melee"] else
                     "ranged" if t in slot_types["ranged"] else None),
            "origin": origin_of(where.get(h, []), h, custom),
            "regions": regions_of(where.get(h, [])),
            "effect": ep,
            "effect_regions": regions_of(where.get(int(ep, 16), [])) if ep else [],
            "projectile": WF.asset_label(int(proj, 16), desc_of, h2p) if proj else None,
            "carried_by": sorted({n for n, s in carried[h] if s})[:6],
            "carried_by_custom": sorted({n for n, s in carried[h] if not s})[:6],
            "values": vals,
            "unwritable": {k: v for k, v in why.items() if v}})
    return {"weapons": out,
            "weapon_assets": {k: sorted(v.values(), key=lambda x: x["label"].lower())
                              for k, v in assets.items()},
            "weapon_slots": {k: sorted(v) for k, v in slot_types.items()}}


def geometry_catalog(loaded):
    r"""Every NAMED geometry record - the Weapon Creator's "Choose other Geometry" list.

    Written as GeometryCatalog.csv beside CharacterModel.json rather than into
    it: 3,420 rows would slow every creator open for a list one window reads,
    and only when asked. Names come from the same path harvest everything else
    uses; the folder is kept because 458 file names repeat across folders
    (barrel_explosive.geo lives in several instance sets).
    """
    names, rs, weap, by, h2p, where = loaded
    rows = []
    for h, q in h2p.items():
        r = by.get(h)
        if not r or r["kind"] != 0 or not q.lower().endswith(".geo"):
            continue
        p = q.replace("/", BS)
        parts = [x for x in p.split(BS) if x]
        folder = BS.join(parts[1:-1] if parts and parts[0].lower() == "data" else parts[:-1])
        ps = where.get(h, [])
        rows.append({"Name": parts[-1], "Folder": folder, "Hash": "%08X" % h,
                     "Regions": ",".join(regions_of(ps)),
                     "Global": "1" if any(x.lower().startswith("data" + BS + "global") for x in ps) else "0",
                     "KB": (len(r["desc"]) + len(r["s2"]) + len(r["s3"]) + 1023) // 1024,
                     "Path": p})
    rows.sort(key=lambda x: (x["Name"].lower(), x["Folder"].lower()))
    return rows


def rig_of(gh, by):
    """(rig record hash, bone names) of a body mesh, or (None, []).

    Every character mesh references exactly ONE kind-20 skeleton record (56/56,
    2026-09-13). An attachment names a bone from it; a bone the rig lacks renders
    nothing, silently - so the Attachments tab offers this list, not a guess.
    """
    import rig_bones as RBN
    r = by.get(gh)
    if not r:
        return None, []
    d = r["desc"]
    hits = {v for v in (struct.unpack_from("<I", d, k)[0] for k in range(len(d) - 3))
            if v in by and by[v]["kind"] == 20}
    if len(hits) != 1:
        return None, []
    x = hits.pop()
    return "%08X" % x, RBN.bones_of(by[x]["desc"])[1]


def attachment_catalogue(loaded, skels):
    r"""The Attachments tab's typical meshes.

    Every mesh under \data\geometry\attachments\ - the ones authored to be worn -
    plus any other mesh a character already wears (the Killer Clakker's shovel).
    `worn_by` names who wears it; the tab's "Choose other Geometry..." reaches
    the rest of GeometryCatalog.csv.
    """
    names, rs, weap, by, h2p, where = loaded
    worn = {}
    for S in skels.values():
        for T in S["templates"].values():
            for c in T["characters"]:
                for e in ((c.get("values") or {}).get("m_defaultAttachments") or []):
                    w = worn.setdefault(int(e["geo"], 16), {"by": [], "stock": 0, "bones": set()})
                    if c["name"] not in w["by"]:
                        w["by"].append(c["name"])
                    w["stock"] += 1 if c.get("origin") == "stock" else 0
                    w["bones"].add(e["bone"])
    out = []
    for h, q in h2p.items():
        r = by.get(h)
        if not r or r["kind"] != 0 or not q.lower().endswith(".geo"):
            continue
        p = q.replace("/", BS)
        if (BS + "attachments" + BS) not in p.lower() and h not in worn:
            continue
        parts = [x for x in p.split(BS) if x]
        folder = BS.join(parts[1:-1] if parts and parts[0].lower() == "data" else parts[:-1])
        ps = where.get(h, [])
        w = worn.get(h, {"by": [], "stock": 0, "bones": set()})
        out.append({"hash": "%08X" % h, "name": parts[-1], "folder": folder, "path": p,
                    "regions": regions_of(ps),
                    "global": any(x.lower().startswith("data" + BS + "global") for x in ps),
                    "worn_by": sorted(w["by"]), "worn_stock": w["stock"], "bones": sorted(w["bones"])})
    out.sort(key=lambda x: (x["folder"].lower(), x["name"].lower()))
    return out


def aff_options(skels, where):
    """The Immunities section's m_affList checklist: every player ammo pref.

    `listed_on` counts the STOCK characters whose list carries it - evidence
    for what the list does, shown beside each box.
    """
    import char_fields as CF
    listed = collections.Counter()
    for S in skels.values():
        for T in S["templates"].values():
            for c in T["characters"]:
                if c.get("origin") == "stock":
                    for hx in {a["hash"] for a in c.get("afflist", [])}:
                        listed[hx] += 1
    out = []
    for h, nm in sorted(CF.AMMO_NAMES.items(), key=lambda kv: kv[1].lower()):
        ps = where.get(h, [])
        if not ps:
            continue
        out.append({"hash": "%08X" % h, "name": nm, "listed_on": listed.get("%08X" % h, 0),
                    "global": any(p.lower().startswith("data" + BS + "global") for p in ps),
                    "regions": regions_of(ps)})
    return out


def spawners_and_icons():
    r"""The Rewards tab's two pickers, both derived.

    COLLECTABLE SPAWNERS. A 43-byte kind-7 record: +12 the collectable it
    spawns, +16 how many. There are 19 in the game and only TWO are wired to a
    character - both dropping Moolah_Small, 3 and 8 (the 8 is the killer
    clakker).

    The other seventeen belong to AMMO CRATES:

        \data\geometry\decorators\animatedDestructibles\ammoCrate_fuzzle_10\
        \data\geometry\decorators\animatedDestructibles\ammoCrate_stingbee_10\
        \data\geometry\decorators\animatedDestructibles\ammoCrate_armadillo_10\
        ...one directory per ammo type, each holding shake.gr2 - the crate's
        wobble animation when it is hit.

    (An earlier version of this comment called those "shakeable bushes". That
    was invented from the clip's filename and is wrong - bush ammo in retail
    is a different system. The owners are kind-7, 125-byte animatedDestructible
    records: crates you break open, spraying ammo the way a townsfolk sprays
    moolah.)

    That is what matters here: a crate sprays ammo through the SAME spawner
    record a character uses for moolah. So making a character drop ammo needs
    no new record and no new mechanism - only a different hash in the slot.

    RESIDENCY STILL APPLIES. The collectable's GEOMETRY must already live in
    the region or the drop crashes on spawn - Moolah_Large is native to
    region_02 and crashes elsewhere even when the prefs record is copied in.
    So each spawner is reported with the regions its geometry is resident in,
    and the UI must not offer one outside them without a port.

    ICONS. The bounty store is Flash (`\\data\\ui\\bounty-store.swf`) with
    numbered bitmap textures, so the name it shows is rendered art, not a
    string in the data. What a character record actually chooses is `m_icon`,
    one of the 29 shipped `character/icons/*.tga`. That IS the bounty
    category as far as the data is concerned.
    """
    names, rs, weap, by, h2p, where = load()
    customh = custom_hashes()
    region_of = {}
    for h, paths in where.items():
        rs_ = set()
        for p in paths:
            for r in SHIPPED:
                if (BS + r + BS) in (p + BS):
                    rs_.add(r.replace("region_", ""))
        if rs_:
            region_of[h] = rs_

    AMMO = ("fuzzle", "bee", "thudslug", "chipmunk", "boombat", "boom_bat",
            "spider", "skunk", "sniper", "slug", "bat", "wasp", "stingbee")
    out = []
    for h, r in by.items():
        if r["kind"] != 7 or len(r["desc"]) != 43:
            continue
        d = r["desc"]
        pref = struct.unpack_from("<I", d, 12)[0]
        cnt = struct.unpack_from("<I", d, 16)[0]
        # 43 bytes and kind 7 is NOT sufficient - other record types share the
        # shape. C7F0C08E matched with count 544,498,034 and a +12 that
        # resolves to nothing. A real spawner points at a record that exists
        # and spawns a plausible number of things.
        tr = by.get(pref)
        if tr is None or not (1 <= cnt <= 100):
            continue
        # what the target points at names it: a .geo and usually an icon
        geo, assets = None, []
        if tr:
            for k in range(max(0, len(tr["desc"]) - 4)):
                q = h2p.get(struct.unpack_from("<I", tr["desc"], k)[0])
                if q:
                    assets.append(q)
                    if q.lower().endswith(".geo") and geo is None:
                        geo = q
        label = _basename(h2p.get(pref) or geo or "%08X" % pref)
        low = (label + " " + " ".join(_basename(a) for a in assets)).lower()
        if "moolah" in low:
            kind = "moolah"
        elif any(k in low for k in AMMO):
            kind = "ammo"
        else:
            kind = "treasure"
        gh = game_hash(geo) if geo else None
        # The spray parameters. +12 and +16 are confirmed (every tool here
        # uses them); the rest are UNNAMED and that is deliberate - the player
        # tunes them in game rather than having them guessed at. Reported raw.
        #
        # The three parameter sets vanilla actually ships, which are what the
        # designer offers as presets:
        #   ammo crate   f20 0  f27 1     f31 0.5   f35 2    f39 0.5
        #   townsfolk    f20 3  f27 6     f31 0.25  f35 1.5  f39 0.3
        #   violent      f20 3  f27 9     f31 0.25  f35 5    f39 0.5
        #
        # E94574EE (the killer clakker's x8) is byte-identical to 47DB9BA7,
        # the Moolah_Large x30, apart from count and collectable - it was
        # cloned from the most violent spray in the game, which is why it
        # sprays hard. Two variables moved at once, so do not read that as
        # proof of what any single float does.
        ff = lambda o: round(struct.unpack_from("<f", d, o)[0], 6)
        # A Spray Designer record is content-addressed, so it identifies
        # itself - a Save-path spray has no CustomHashes row to say so.
        import spray as SP
        org = "custom" if SP.hash_of(bytes(d)) == h else origin_of(where.get(h, []), h, customh)
        out.append({"hash": "%08X" % h, "collectable": "%08X" % pref,
                    "label": label.replace(".geo", "").replace(".txt", ""),
                    "count": cnt, "kind": kind,
                    "origin": org,
                    "geometry": _basename(geo) if geo else None,
                    "regions": sorted(region_of.get(gh, [])) if gh else [],
                    "params": {"f20": ff(20), "b24": d[24], "b25": d[25],
                               "b26": d[26], "f27": ff(27), "f31": ff(31),
                               "f35": ff(35), "f39": ff(39)}})
    out.sort(key=lambda x: (x["kind"], -x["count"], x["label"]))

    # The collectables a custom spray can be pointed at.
    #
    # DERIVED FROM THE SPAWNERS, not from a path filter. An earlier version
    # collected records referencing `\data\geometry\Collectables\*.geo`, which
    # finds moolah, crystal, the chests and the idol - and NO AMMO AT ALL.
    # Ammo collectables point at meshes that live with their weapons
    # (fuzzle.geo, bee.geo, thudslug.geo, stingbee) and at a prefs .txt, not
    # at anything under \Collectables\. The designer therefore offered seven
    # options, none of which was ammo, on a tab whose whole point was ammo.
    #
    # Anything a shipping spawner spawns IS a collectable, by definition. That
    # is the derivation; the path filter was a guess about where they live.
    seen = {}
    for s in out:
        seen[int(s["collectable"], 16)] = None
    for h, r in by.items():                       # plus any unspawned ones
        if r["kind"] == 7 and len(r["desc"]) in (56, 95):
            for k in range(max(0, len(r["desc"]) - 4)):
                q = h2p.get(struct.unpack_from("<I", r["desc"], k)[0])
                if q and "/collectables/" in q.lower().replace(BS, "/") \
                        and q.lower().endswith(".geo"):
                    seen.setdefault(h, None)
                    break
    colls = []
    for h in seen:
        r = by.get(h)
        if r is None:
            continue
        geo = icon = pref = None
        for k in range(max(0, len(r["desc"]) - 4)):
            q = h2p.get(struct.unpack_from("<I", r["desc"], k)[0])
            if not q:
                continue
            low = q.lower()
            if low.endswith(".geo") and geo is None:
                geo = q
            elif low.endswith(".tga") and icon is None:
                icon = q
            elif low.endswith(".txt") and pref is None:
                pref = q
        label = _basename(geo or pref or "%08X" % h)
        for ext in (".geo", ".txt"):
            label = label.replace(ext, "")
        # Kind comes from the spawners that already spray it, not from another
        # keyword guess - the spawner classification is the one that was
        # checked against the crates.
        kind = next((s["kind"] for s in out if int(s["collectable"], 16) == h), None)
        if kind is None:
            kind = "moolah" if "moolah" in label.lower() else "treasure"
        colls.append({"hash": "%08X" % h, "label": label, "kind": kind,
                      "geometry": _basename(geo) if geo else None,
                      "icon": _basename(icon) if icon else None,
                      "prefs": _basename(pref) if pref else None,
                      "regions": sorted(region_of.get(game_hash(geo), [])) if geo else []})
    colls.sort(key=lambda x: x["label"].lower())

    icons = []
    for h, q in h2p.items():
        s = q.lower().replace(BS, "/")
        if "/character/icons/" in s and s.endswith(".tga"):
            icons.append({"hash": "%08X" % h, "name": _basename(q),
                          "label": _basename(q).replace(".tga", "").replace("_", " ")})
    icons.sort(key=lambda x: x["label"].lower())
    return out, icons, colls


def _kinds(counter, drop_none=True):
    return sorted(k for k in counter if not (drop_none and k == "(none)"))


def to_json(skels, spawners=None, icons=None, collectables=None, weapons=None, aff=None, attach=None):
    out = {"skeletons": {}, "spawners": spawners or [], "icons": icons or [],
           "weapons": [], "weapon_assets": {}, "weapon_slots": {}, "aff_options": aff or [],
           "attachment_geos": attach or [],
           "collectables": collectables or [],
           "regions": [{"key": r.replace("region_", ""), "label": r} for r in SHIPPED]
                      # emptygulch is deliberately absent. Its 175 bundles are byte copies
                      # of region_01 that the engine never reads - its blockmap names
                      # region_01 paths - so porting "into" it edits dead files and grows a
                      # blockmap that then points at the wrong bundle. That crashed it twice
                      # (2026-09-08, 2026-09-12). No player has it either.
                      + [{"key": "utility", "label": "utility (debug room)"}],
           "species": [
        {"name": n, "hash": "%08X" % h, "hostile": ho}
        for h, (n, ho) in sorted(SPECIES.items(), key=lambda kv: kv[1][0])],
        "fields": [{"name": n, "anchor": "ANC", "offset": o, "width": w, "type": t}
                   for n, o, w, t in FIELDS] +
                  [{"name": n, "anchor": "ABS", "offset": o, "width": w, "type": t}
                   for n, o, w, t in ABS_FIELDS] +
                  [{"name": n, "anchor": "MOTION", "offset": o, "width": w, "type": t}
                   for n, o, w, t in MOTION_FIELDS],
        "inert_fields": [{"name": n, "anchor": "CFG", "offset": o}
                         for n, o in INERT_CFG_FIELDS]}
    for sk, S in sorted(skels.items()):
        tt = {}
        for nm, T in sorted(S["templates"].items()):
            tt[nm] = {
                "config": T["config"], "clips": T["clips"],
                "families": T["families"],
                "melee_kinds": _kinds(T["melee"]),
                "ranged_kinds": _kinds(T["ranged"]),
                "melee_kinds_stock": _kinds(T["melee_stock"]),
                "ranged_kinds_stock": _kinds(T["ranged_stock"]),
                # the UI greys the ranged slot when NO stock character using
                # this template carries one - pointless, not dangerous
                "ranged_ever_stock": bool(_kinds(T["ranged_stock"])),
                "characters": T["characters"],
            }
        geoms = {g: {"origin": v["origin"],
                     "templates": sorted(v["templates"]),
                     "hash": v.get("hash"), "regions": v.get("regions", []),
                     # the bones an attachment on THIS mesh can name
                     "rig": v.get("rig"), "bones": v.get("bones", [])}
                 for g, v in sorted(S["geometries"].items())}
        union = []
        for v in geoms.values():
            for x in v["bones"]:
                if x not in union:
                    union.append(x)
        out["skeletons"][sk] = {
            "characters": S["characters"], "templates": tt, "geometries": geoms,
            "bones": union, "worn_bones": dict(S["worn"])}
    # Every voice string a character actually carries - the Voice dropdown
    # offers exactly these, so a base like joMomma ('outlawr') is never
    # silently switched to 'outlaw' just by opening the form.
    out["voices"] = sorted({c["values"].get("m_audioName")
                            for S in out["skeletons"].values()
                            for T in S["templates"].values()
                            for c in T["characters"]
                            if c.get("values", {}).get("m_audioName")})
    if weapons:
        out.update(weapons)
    return out


def unknowns():
    """Varying byte positions with no confirmed field - the Experimental tab.

    Restricted to the 'full' record shape (ANC-CFG == 362) that validates,
    because comparing across shapes produces nonsense - char_anchor.py says so
    and it is the reason every earlier survey failed.
    """
    rs, known = CA.roster()
    full = [(nm, h, C, A, b) for h, (nm, C, A, b) in rs.items()
            if A is not None and A - C == 362 and CA.validate(b, A, known) is None]
    LOW, HIGH = -360, 181
    vals = {}
    for off in range(LOW, HIGH):
        s = set()
        for nm, h, C, A, b in full:
            k = A + off
            if 0 <= k < len(b):
                s.add(b[k])
        vals[off] = s
    named = set()
    for n, o, w, t in FIELDS:
        for k in range(o, o + w):
            named.add(k)
    varying = {o for o in vals if len(vals[o]) > 1}
    unk = sorted(varying - named)
    runs, s, p = [], None, None
    for o in unk:
        if s is None:
            s = p = o
        elif o == p + 1:
            p = o
        else:
            runs.append((s, p))
            s = p = o
    if s is not None:
        runs.append((s, p))
    return full, vals, varying, named, runs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", help="write the graph to this path")
    ap.add_argument("--why", help="explain one skeleton's options")
    ap.add_argument("--unknowns", action="store_true",
                    help="candidate dials for the Experimental tab")
    a = ap.parse_args()

    if a.unknowns:
        full, vals, varying, named, runs = unknowns()
        print("%d full-shape, anchor-validated records compared" % len(full))
        print("   %d byte positions vary between characters" % len(varying))
        print("   %d of those are covered by a confirmed field" % len(varying & named))
        print("   %d vary and are UNNAMED" % len(varying - named))
        print("\nNOTE: the four m_sight* blocks are documented CFG-relative in")
        print("CHARACTER_DIALS.md and are not in this ANC-relative table, so")
        print("they are counted as unnamed here. The 32-byte stride below is")
        print("them - do not treat the raw total as unexplored space.\n")
        print("%d contiguous unnamed runs; widest 20:" % len(runs))
        for lo, hi in sorted(runs, key=lambda r: -(r[1] - r[0]))[:20]:
            print("   ANC%+d .. ANC%+d   (%d bytes)" % (lo, hi, hi - lo + 1))
        return

    loaded = load()
    skels, names = build(loaded)

    if a.json:
        sp, ic, co = spawners_and_icons()
        wc = weapons_catalogue(loaded)
        af = aff_options(skels, loaded[5])
        ac = attachment_catalogue(loaded, skels)
        # The catalogue first: CharacterModel.json's timestamp is what the
        # launcher compares against the game data, so it must be written last.
        import csv
        gc = geometry_catalog(loaded)
        gpath = os.path.join(os.path.dirname(os.path.abspath(a.json)), "GeometryCatalog.csv")
        with io.open(gpath, "w", encoding="utf-8", newline="") as f:
            wr = csv.DictWriter(f, fieldnames=["Name", "Folder", "Regions", "Global", "KB", "Hash", "Path"])
            wr.writeheader()
            wr.writerows(gc)
        print("wrote %s: %d named geometries" % (os.path.relpath(gpath, ROOT), len(gc)))
        with io.open(a.json, "w", encoding="utf-8") as f:
            json.dump(to_json(skels, sp, ic, co, wc, af, ac), f, indent=1, sort_keys=True)
        n = sum(len(S["templates"]) for S in skels.values())
        print("wrote %s: %d skeletons, %d templates, %d spawners (%d ammo), "
              "%d collectables, %d icons, %d weapons"
              % (os.path.relpath(a.json, ROOT), len(skels), n, len(sp),
                 sum(1 for s in sp if s["kind"] == "ammo"), len(co), len(ic), len(wc["weapons"])))
        return

    if a.why:
        S = skels.get(a.why)
        if not S:
            print("no such skeleton. known: %s" % ", ".join(sorted(skels)))
            return
        print("=== skeleton %s - %d character records ===" % (a.why, S["characters"]))
        for nm, T in sorted(S["templates"].items()):
            print("\n  template %s   (%s, %d clips)"
                  % (nm, _basename(T["config"]), T["clips"]))
            ms, rsk = _kinds(T["melee_stock"]), _kinds(T["ranged_stock"])
            print("     melee kinds  : %s" % (", ".join(ms) or "none in stock data"))
            if rsk:
                print("     ranged kinds : %s" % ", ".join(rsk))
            else:
                print("     ranged kinds : NONE - no shipped character using this")
                print("                    template carries a ranged weapon, so the")
                print("                    slot is offered greyed: harmless, pointless")
            miss = [f for f, n in T["families"].items() if not n]
            if miss:
                print("     no clips for : %s (will T-pose - not a fault)"
                      % ", ".join(sorted(miss)))
            for c in T["characters"]:
                tag = "" if c["origin"] == "stock" else "  [%s]" % c["origin"]
                print("     %s  %-34s %s%s" % (c["hash"], c["name"],
                                               ",".join(c["geometry"]) or "-", tag))
        print("\n  geometries on this skeleton:")
        for g, v in sorted(S["geometries"].items()):
            tag = "" if v["origin"] == "stock" else "  [%s]" % v["origin"]
            print("     %-34s via %s%s" % (g, ", ".join(v["templates"]), tag))
        return

    print("%d skeletons\n" % len(skels))
    print("%-20s %5s %5s  %s" % ("SKELETON", "chars", "geos", "templates"))
    for sk, S in sorted(skels.items(), key=lambda kv: -kv[1]["characters"]):
        print("%-20s %5d %5d  %s" % (sk, S["characters"], len(S["geometries"]),
                                     ", ".join(sorted(S["templates"]))[:70]))


if __name__ == "__main__":
    main()
