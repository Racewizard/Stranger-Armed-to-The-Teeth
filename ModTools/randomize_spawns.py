r"""Spawn Randomizer - retype spawns to random characters. EXPERIMENTAL.

Runs AFTER apply_spawns, and only ever overwrites the 4-byte character hash at
+128 of records that already exist. It never inserts or removes a record, which
is what makes it safe to re-run: apply_spawns rebuilds the level from its own
base every time, so each Apply Changes re-randomizes from a clean slate rather
than compounding.

    python randomize_spawns.py 01 --config ..\StrangerAT3\RandomizerConfig.csv
    python randomize_spawns.py --all --config <cfg>
    python randomize_spawns.py 01 --config <cfg> --dry-run

TWO INDEPENDENT SETS, which is the whole design:

  ROSTER          what a spawn may be turned INTO   (Hostiles/Friendlies/Bosses)
  RANDOMIZE INTO  which spawns are eligible to BE changed
                  (friendly / hostile / boss / progression-necessary)

A CHARACTER CAN ONLY REPLACE A SPAWN IN A REGION THAT ALREADY LOADS IT.
`swse/research/NPC_SPAWNING.md`: "Forcing a foreign type CRASHES the level - the
hash resolves but its assets are not in the bundle." So the roster is built from
that region's OWN catalogue_<region>.csv, never the global one. This is also why
cross-region randomization is not offered.

Progression-necessary characters are a category of their own and are governed
SOLELY by their own checkbox - a clakker_clerk is not randomized just because
"friendly" is enabled, because losing one can strand the player.

THE TWO QUESTIONS HAVE DIFFERENT PRECEDENCE, and castaraider is why:

    may this spawn BE CHANGED?   progression > boss > faction
    may this character be a TARGET?   boss > progression > faction

He is quest-critical in both 02a and 03, so his own spawns are protected by the
progression box - but he is also a boss enemy, so he can still be rolled into
other spawns when Bosses is on the roster.

sektoboss is a both-category too, but he is additionally in ROSTER_NEVER and is
never rolled into anything. His weapon and tiny are each opt-in via their own
checkbox - they are risks the player chooses, not things the tool decides.
"""
import argparse, csv, io, os, random, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from whose_attachment import spawn_table
from spawn_prop import ROOT, lvl_path, u32

TYPE_OFF = 128
CAT_DIR = os.path.join(ROOT, "StrangerAT3", "RegionData")

# Bosses. The `outlawboss_*` five, gloktigi and armoredgloktigi, Sekto and his
# deathray, shocktanks, castaraider, and the bounty uniques.
#
# NOT included, and still undecided: the `jailed_*` boss copies (jailed_blisterz,
# jailed_floydd, jailed_lootenduke) - captured, scripted, friendly-faction
# versions of bosses that already appear in this list under their own hashes.
BOSSES = {
    0x155A0299: "outlawboss_boilz",
    0xB53065FF: "outlawboss_elbowz",
    0xFF61B694: "outlawboss_floydd",
    0x4312CE47: "outlawboss_lootenduke",
    0xE2B247BD: "outlawboss_blisterz",
    0x450E9598: "gloktigi",
    0x300596C6: "armoredgloktigi",
    0x97C44232: "sektoboss",
    0xCAB666AF: "sektosdeathray",
    0x151F4B4E: "shocktank",
    0xC9F81B7E: "dcasteraider",
    0x35179A52: "jomama",
    0xB28A48AA: "meaglymcgraw",
    0x2B6A3743: "patrackpalooka",
    0x4E169515: "lefty_lugnutz",
    0x57009F0C: "fattymcboomboom",
    0x0BB34EB7: "xplosivesmcgee",
    0x4D82B2A2: "tiny",
}

# Losing one of these can strand the player. Each was checked against the
# per-region catalogues and appears in exactly the regions listed.
PROGRESSION = {
    0xE2B247BD: "outlawboss_blisterz (00)",
    0xC387D977: "vykkerdoc (01)",
    0x214F50C8: "grubb_injured / native rebel hurt (04)",
    0xE7EBC893: "grubb_leader / native rebel leader (04, 05)",
    0xBAF35C16: "clakker_clerk (01, 02, 03)",
    0x97C44232: "sektoboss (06)",
    0xCAB666AF: "sektosdeathray (06)",
    0xAB444625: "sewerworker (02)",
    0xECF8307A: "skycart_joe (03)",
    0x3670CD9C: "clakker_sleghunter (03)",
    0x3E4F6569: "bargekeeper / clakker bargekeeper (03)",
    # castaraider is BOTH. Every instance of him is progression-necessary, so
    # his SPAWNS are protected by the progression box - but he is a boss too,
    # so he may still be rolled INTO other spawns when Bosses is on the roster.
    0xC9F81B7E: "dcasteraider / castaraider (02a, 03)",
}

# NEVER a randomization TARGET, whatever the roster says.
#
# Sekto is the endgame encounter, wired to his own scripted setup and far too
# strange to drop into an ordinary spawn slot. He stays in BOSSES so his own
# spawns are still classified; nothing is ever turned INTO him.
#
# jailbreak_blisterz is a CUSTOM character this mod created - a new hash, not a
# shipped one - and he lives in catalogue_01 like any other, so without this he
# would quietly be rolled in as an ordinary region_01 friendly.
ROSTER_NEVER = {
    0x97C44232: "sektoboss",
    0xFFFFDB52: "jailbreak_blisterz (custom)",
}

# Sekto's deathray is opt-in through its own checkbox rather than the Bosses
# one, because it is a 5000 HP stationary emplacement - a real challenge to meet
# in an ordinary spawn slot, and a bad surprise if it arrived unasked. The
# checkbox is independent: tick it and the deathray joins the roster whether or
# not Bosses is ticked.
DEATHRAY = 0xCAB666AF

# FACTION FIXES. The catalogue's Faction column was derived from HP - every
# friendly the game ships has 100000 HP - which is right for invulnerable
# townsfolk and WRONG for an ally who fights beside you and can die.
# grubbsoldier has 100 HP and is marked hostile; he is the Grubb resistance at
# the dam, and region_06's catalogue lists no friendly at all as a result.
# Confirmed in game: the randomizer was rolling him in as an enemy.
FACTION_OVERRIDE = {
    0xB42B865B: "friendly",   # grubbsoldier - the winter grubb, region_06
}

# LEFT ALONE ENTIRELY - not randomized, and never a roster target.
#
# The Grubb resistance at the dam. Retyping their spawns produced radar dots
# with no visible character in game, and they are not wanted in the pool either.
# All 17 are null-job, so the usual "waiting on a trigger" explanation does NOT
# apply and the cause is unknown - but they are simply excluded rather than
# worked around.
FROZEN = {
    0xB42B865B: "grubbsoldier - the Grubb resistance, region_06",
    # A FAN-MADE CHARACTER - we made him. He is not part of the game's cast and
    # has no business turning up as a random spawn, in either direction: he is
    # never rolled into another spawn (ROSTER_NEVER) and his own spawn is never
    # randomized away (here). Without this second half, the AT3 Official preset
    # placed him and the randomizer immediately retyped him into a wolvark.
    0xFFFFDB52: "jailbreak_blisterz - fan-made, region_01",
}

# OPT-IN, one checkbox each. Neither is in the roster unless asked for.
#
# tiny is a very expensive model - high poly, high bone count - and is known to
# crash the level when enough instances of him are called. Region_02 crashed on
# load with 22 of him in it, though a later roll of the SAME settings loaded
# fine, so it is a threshold effect rather than a certainty. Rather than cap the
# randomizer and take the choice away, he is offered as a risk the player can
# accept: the checkbox says what can happen, and a crashing roll can be escaped
# by changing the seed.
TINY = 0x4D82B2A2

# The jailed_* boss copies (jailed_blisterz, jailed_floydd, jailed_lootenduke)
# are deliberately in NEITHER list. They are captured, scripted, friendly-faction
# characters and they stay ordinary friendlies - they appear in the roster only
# when Friendlies is ticked, and their spawns are randomized only by the friendly
# box.

DEFAULTS = {
    "Enabled": "0",
    "RosterHostiles": "1", "RosterFriendlies": "0", "RosterBosses": "0",
    "RosterDeathray": "0", "RosterTiny": "0",
    "IntoHostile": "1", "IntoFriendly": "0", "IntoBosses": "0", "IntoProgression": "0",
    "Seed": "",
}


def read_config(path):
    cfg = dict(DEFAULTS)
    if path and os.path.exists(path):
        with io.open(path, encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh):
                k = (r.get("Key") or "").strip()
                if k in cfg:
                    cfg[k] = (r.get("Value") or "").strip()
    return cfg


def on(cfg, key):
    return str(cfg.get(key, "0")).strip().lower() in ("1", "true", "yes", "y", "on")



def catalogue(region):
    """hash -> (name, faction) for characters this region actually bundles."""
    p = os.path.join(CAT_DIR, "catalogue_%s.csv" % region)
    out = {}
    if not os.path.exists(p):
        return out
    with io.open(p, encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            try:
                h = int(r["Hash"], 16)
                fac = FACTION_OVERRIDE.get(h, (r.get("Faction") or "").lower())
                out[h] = (r.get("Name") or "", fac)
            except (ValueError, KeyError, TypeError):
                pass
    return out


def category(h, faction):
    if h in FROZEN:
        return "frozen"
    if h in PROGRESSION:
        return "progression"
    if h in BOSSES:
        return "boss"
    if faction == "friendly":
        return "friendly"
    if faction == "hostile":
        return "hostile"
    return "other"


def roster_for(cfg, cat):
    """Hashes a spawn may be turned INTO, drawn from this region only.

    Note this does NOT use category(): the two questions have different
    precedence, which castaraider is the case that proves.

      being CHANGED   progression wins - all his instances are quest-critical,
                      so his spawns are protected by the progression box
      being a TARGET  boss wins - he is a boss enemy, so he may be rolled into
                      other spawns whenever Bosses is on the roster

    A progression character that is NOT also a boss is never a target:
    duplicating one is harmless in itself, but quietly seeding extra
    quest-critical NPCs across the map is not what "Hostiles" means.

    ROSTER_NEVER and the DEATHRAY opt-in override all of it.
    """
    out = []
    for h, (nm, fac) in cat.items():
        if h in FROZEN or h in ROSTER_NEVER:
            continue
        if h == DEATHRAY:
            if on(cfg, "RosterDeathray"):
                out.append(h)
            continue
        if h == TINY:
            if on(cfg, "RosterTiny"):
                out.append(h)
            continue
        if h in BOSSES:
            if on(cfg, "RosterBosses"):
                out.append(h)
            continue
        if h in PROGRESSION:
            continue
        if fac == "hostile" and on(cfg, "RosterHostiles"):
            out.append(h)
        elif fac == "friendly" and on(cfg, "RosterFriendlies"):
            out.append(h)
    return sorted(out)


def eligible(cfg, c):
    if c == "frozen":
        return False
    if c == "progression":
        return on(cfg, "IntoProgression")
    if c == "boss":
        return on(cfg, "IntoBosses")
    if c == "hostile":
        return on(cfg, "IntoHostile")
    if c == "friendly":
        return on(cfg, "IntoFriendly")
    return False


def run(region, cfg, rng, dry=False):
    p = lvl_path(region)
    if not os.path.exists(p):
        return 0, 0
    cat = catalogue(region)
    pool = roster_for(cfg, cat)
    if not pool:
        print("region_%-4s roster is empty for this region - nothing changed" % region)
        return 0, 0
    d = bytearray(open(p, "rb").read())
    changed = considered = 0
    for off, h in spawn_table(bytes(d)):
        rec = off - TYPE_OFF
        if rec < 0:
            continue
        nm, fac = cat.get(h, ("", ""))
        if not eligible(cfg, category(h, fac)):
            continue
        considered += 1
        choices = [x for x in pool if x != h]
        if not choices:
            continue
        struct.pack_into("<I", d, rec + TYPE_OFF, rng.choice(choices))
        changed += 1
    if changed and not dry:
        open(p, "wb").write(bytes(d))
    print("region_%-4s roster %-3d character(s); %d eligible spawn(s), %d retyped%s"
          % (region, len(pool), considered, changed, "  (dry run)" if dry else ""))
    return considered, changed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("region", nargs="?")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--config")
    ap.add_argument("--dry-run", dest="dry", action="store_true")
    a = ap.parse_args()

    cfg = read_config(a.config)
    if not on(cfg, "Enabled"):
        print("randomizer disabled - nothing done")
        return 0

    # A BLANK SEED STILL GETS A SEED - it is just generated and reported.
    #
    # Blank means "roll something new this time", so it must NOT be written back
    # to the config or every later apply would replay the same roll. But the
    # seed is printed, and the launcher surfaces it, so a run you liked can be
    # written down afterwards and shared. Typing a seed replays it exactly.
    seed = (cfg.get("Seed") or "").strip()
    generated = not seed
    if generated:
        seed = "%08X" % random.SystemRandom().getrandbits(32)
    rng = random.Random(seed)
    print("seed %s%s" % (seed, "  (generated - enter it in the Randomizer to replay this run)"
                         if generated else ""))

    if a.all or not a.region:
        b = os.path.join(ROOT, "data", "bundles")
        regions = sorted(n[len("region_"):] for n in os.listdir(b) if n.startswith("region_"))
    else:
        regions = [a.region]
    tot = 0
    for r in regions:
        tot += run(r, cfg, rng, a.dry)[1]
    print("%d spawn(s) retyped in total" % tot)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
