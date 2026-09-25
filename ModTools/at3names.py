r"""Give every hash a human name, deriving as much as possible from the files.

AT3 should not ship a table of hashes. Hashes are per-region copies and change
whenever a bundle is rebuilt, so a hash table goes stale exactly the way the
stored `RecOff` values did. Names are derived live instead, and the only
hardcoded data is a small table keyed on INTERNAL NAME - which never changes.

Where names come from, in order of preference:

  1. PATH          the hash IS game_hash(path) for most assets, so harvesting
                   every path string out of the bundles names 62% of all
                   16,924 records for free. resolve_assets.py does the harvest.
  2. CHARACTER     a character record has no path of its own, but it names its
                   MotionAnimConfig - `outlawCutter.txt` - and char_anchor
                   reads it. 88 characters, 46 distinct names.
  3. WEAPON        weapons carry no name at all. 60 of 79 are reachable from a
                   character's melee/ranged slot, so they are named by owner;
                   the other 19 (turrets, sub-weapons) are named by the
                   projectile mesh their effect pref points at.
  4. DISPLAY       DisplayNames.csv maps an internal name to what a player
                   calls it - outlawBoss_BadMortar is "Packrat Palooka", and
                   region_00 is "Tutorial". THIS is the only hardcoded part.

    python at3names.py --of C8F313D2
    python at3names.py --characters
    python at3names.py --weapons
    python at3names.py --emit-template     write DisplayNames.csv to fill in
"""
import argparse, csv, glob, io, os, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rebuild_bundle as RB, char_anchor as CA
import resolve_assets as RA
from gamehash import game_hash

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DISPLAY = os.path.join(ROOT, "StrangerAT3", "DisplayNames.csv")
# Per-HASH manual overrides - the escape hatch for anything derivation cannot
# tell apart. Several stock character hashes share one cfg name (5 hashes are
# all "outlawShooter") but are placed differently in game - one may ride a
# cart, one may stand still - and nothing in the record says so. That is a
# fact about the LEVEL, not the character record, so it cannot be derived; it
# has to be told. HASHNAMES wins over everything else, including CustomHashes.
HASHNAMES = os.path.join(ROOT, "StrangerAT3", "HashNames.csv")
BS = chr(92)
WTYPE = {417: "Club", 418: "Shock", 419: "Turret", 420: "Firearm",
         423: "BomberBomb", 425: "SpawnGun", 426: "Gloktigi", 427: "Gloktigi"}


def wtype(d):
    """The weapon type as the RECORD states it - the length-prefixed string at
    +307. WTYPE guesses from size, and size only tracks the string's length:
    three 417 B records are "Jump", not Club, and one 418 B record is "Sekto".
    """
    if len(d) >= 315:
        n = struct.unpack_from("<I", d, 307)[0]
        s = d[311:311 + n]
        if 3 <= n <= 24 and len(s) == n and all(65 <= c <= 90 or 97 <= c <= 122 for c in s):
            return s.decode()
    return WTYPE.get(len(d), "?")


def display_map():
    if not os.path.exists(DISPLAY):
        return {}
    out = {}
    with io.open(DISPLAY, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            k = (r.get("Internal") or "").strip()
            v = (r.get("Display") or "").strip()
            if k and v:
                out[k.lower()] = v
    return out


def hash_overrides():
    if not os.path.exists(HASHNAMES):
        return {}
    out = {}
    with io.open(HASHNAMES, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            try:
                h = int((r.get("Hash") or "0"), 16)
            except ValueError:
                continue
            nm = (r.get("Display") or "").strip()
            if h and nm:
                out[h] = nm
    return out


def build():
    """(names, detail) - hash -> best name, and how it was derived."""
    h2p = {}
    for q in RA.harvest():
        h2p.setdefault(game_hash(q), q)
    by = {}
    for p in glob.glob(os.path.join(ROOT, "data", "bundles", "*", "*", "*.smb")):
        if os.path.basename(p).count(".") > 1:
            continue
        try:
            for r in RB.parse(open(p, "rb").read())[1]:
                by.setdefault(r["hash"], r)
        except (Exception, SystemExit):
            pass
    rs, known = CA.roster()
    disp = display_map()
    names, how = {}, {}

    for h, q in h2p.items():                                   # 1. path
        names[h] = q.replace("/", BS).split(BS)[-1]
        how[h] = "path"
    for h, (nm, C, A, b) in rs.items():                        # 2. character
        if nm:
            names[h] = disp.get(nm.lower(), nm)
            how[h] = "character"
    # 2b. CustomHashes.csv wins over the cfg name. A custom character that
    # borrows another's MotionAnimConfig would otherwise be named after the
    # donor - outlaw_artillery uses outlawBoss_BadMortar.txt and was reported
    # as Packrat, including for the weapon it owns.
    ch = os.path.join(ROOT, "StrangerAT3", "CustomHashes.csv")
    custom = {}
    if os.path.exists(ch):
        with io.open(ch, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                try:
                    custom[int((r.get("Hash") or "0"), 16)] = (r.get("Name") or "").strip()
                except ValueError:
                    pass
    for h, nm in custom.items():
        if nm:
            names[h] = nm
            how[h] = "custom"

    # 2c. DISAMBIGUATE CHARACTERS. Several stock hashes share one cfg name -
    # 5 hashes are all "outlawShooter" - but are placed differently in the
    # level (one may stand on a cart, one on foot) and nothing in the record
    # says so; that is a fact about the LEVEL, not the character, so it
    # cannot be derived. What CAN be derived is enough of a fingerprint that
    # a user who sees "does X in game" can find the right hash to name via
    # HashNames.csv: record length (attachment count differs) plus the
    # ranged weapon it carries, since two different hashes with the same cfg
    # name essentially never carry the same weapon record.
    cfggroups = {}
    for h, (nm, C, A, b) in rs.items():
        if how.get(h) == "custom":
            continue          # never relabel a custom character
        cfggroups.setdefault(nm or "", []).append(h)
    for nm, hs in cfggroups.items():
        if len(hs) < 2:
            continue
        for h in hs:
            nmh, C, A, b = rs[h]
            rg = struct.unpack_from("<I", b, A + 58)[0] if A and A + 62 <= len(b) else 0
            base = disp.get((nm or "").lower(), nm or "?")
            names[h] = "%s (%d bytes, weapon %08X)" % (base, len(b), rg)
            how[h] = "character-ambiguous"

    weap = {h: r for h, r in by.items() if r["kind"] == 7 and len(r["desc"]) in WTYPE}
    # 3a. weapon by owner. STOCK owners go first: a custom character carries its
    # donor's weapons, and whichever owner the dict yielded first used to win -
    # which renamed Jo Momma's club "test_character_02 melee". A weapon with a
    # CustomHashes.csv row of its own (the Weapon Creator's) keeps that name.
    owners = sorted(rs.items(), key=lambda kv: how.get(kv[0]) == "custom")
    for h, (nm, C, A, b) in owners:
        if A is None:
            continue
        for off, slot in ((54, "melee"), (58, "ranged")):
            if A + off + 4 > len(b):
                continue
            w = struct.unpack_from("<I", b, off + A)[0]
            if w in weap and how.get(w) not in ("owner", "custom"):
                base = names.get(h) if how.get(h) in ("custom", "character-ambiguous") else disp.get((nm or "").lower(), nm or "?")
                names[w] = "%s %s (%s)" % (base, slot, wtype(weap[w]["desc"]))
                how[w] = "owner"
    for h, r in weap.items():                                  # 3b. weapon by projectile
        if h in how:
            continue
        ep = struct.unpack_from("<I", r["desc"], 12)[0]
        g = struct.unpack_from("<I", by[ep]["desc"], 8)[0] if ep in by else 0
        mesh = h2p.get(g)
        names[h] = ("%s (%s)" % (mesh.replace("/", BS).split(BS)[-1].replace(".geo", ""),
                                 wtype(r["desc"]))) if mesh else "unnamed %s" % wtype(r["desc"])
        how[h] = "projectile"

    # 3c. DISAMBIGUATE. Five weapons all came out as "Outlaw Shooter ranged
    # (Firearm)" - per-region variants with different stats and no way to tell
    # them apart in a list. Append the projectile mesh, then the hash if that
    # still is not unique.
    def mesh_of(h):
        ep = struct.unpack_from("<I", by[h]["desc"], 12)[0]
        if ep not in by:
            return None
        g = struct.unpack_from("<I", by[ep]["desc"], 8)[0]
        q = h2p.get(g)
        if not q:
            return None
        return q.replace("/", BS).split(BS)[-1].replace(".geo", "")
    dupes = {}
    for h in weap:
        dupes.setdefault(names.get(h, ""), []).append(h)
    for base, hs in dupes.items():
        if len(hs) < 2:
            continue
        # Disambiguate with something a user can act on. The five Outlaw
        # Shooter rifles differ in damage and muzzle speed, so say so - a mesh
        # name and a hex hash tell nobody which one to pick.
        for h in hs:
            d = by[h]["desc"]
            # m_damage is a FLOAT at +93. This read d[93] as a byte - the low
            # byte of a float, 0 for every whole number - so every rifle was
            # labelled "dmg 0" and the label disambiguated nothing.
            dmg = struct.unpack_from("<f", d, 93)[0] if len(d) >= 97 else 0.0
            spd = struct.unpack_from("<f", d, 46)[0] if len(d) > 50 else 0.0
            names[h] = "%s  dmg %g, spd %.0f" % (base, dmg, spd)
        still = {}
        for h in hs:
            still.setdefault(names[h], []).append(h)
        for nm, group in still.items():
            if len(group) > 1:
                for h in group:
                    m = mesh_of(h)
                    names[h] = "%s [%s]" % (nm, m) if m else "%s %08X" % (nm, h)
        still = {}
        for h in hs:
            still.setdefault(names[h], []).append(h)
        for nm, group in still.items():
            if len(group) > 1:
                for h in group:
                    names[h] = "%s %08X" % (nm, h)

    # 4. EFFECTS. An effect pref carries the projectile mesh and the sounds. It
    # has no name of its own, but exactly one weapon points at it, so name it
    # after that weapon - which is how a user thinks of it anyway.
    for h in weap:
        ep = struct.unpack_from("<I", by[h]["desc"], 12)[0]
        if ep in by and ep not in how:
            names[ep] = "%s - effect" % names.get(h, "%08X" % h)
            how[ep] = "effect"

    # 5. MANUAL OVERRIDE. HashNames.csv wins over every derivation above,
    # including CustomHashes.csv - this is the escape hatch for anything
    # that cannot be told apart from the files, filled in by hand as it is
    # identified in game.
    for h, nm in hash_overrides().items():
        names[h] = nm
        how[h] = "manual"
    return names, how, rs, weap, by


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--of")
    ap.add_argument("--characters", action="store_true")
    ap.add_argument("--weapons", action="store_true")
    ap.add_argument("--emit-template", action="store_true")
    a = ap.parse_args()
    names, how, rs, weap, by = build()

    if a.of:
        h = int(a.of, 16)
        print("%08X  %s   (source: %s)" % (h, names.get(h, "UNNAMED"), how.get(h, "-")))
        return
    if a.characters:
        seen = {}
        for h, (nm, C, A, b) in rs.items():
            seen.setdefault(nm or "?", []).append(h)
        print("%d character records, %d distinct cfg names" % (len(rs), len(seen)))
        for nm in sorted(seen):
            hs = sorted(seen[nm])
            if len(hs) == 1:
                print("   %-40s %08X" % (names.get(hs[0], nm), hs[0]))
            else:
                print("   %s  (%d hashes share this cfg name)" % (nm, len(hs)))
                for h in hs:
                    print("      %08X  %s" % (h, names.get(h, nm)))
        return
    if a.weapons:
        print("%d weapon records" % len(weap))
        for h in sorted(weap, key=lambda x: names.get(x, "")):
            print("   %08X  %-10s %s" % (h, wtype(weap[h]["desc"]), names.get(h, "?")))
        return
    if a.emit_template:
        internal = sorted({(nm or "?") for nm, C, A, b in rs.values()})
        regions = ["region_00", "region_01", "region_02", "region_02a",
                   "region_03", "region_04", "region_05", "region_06", "utility"]
        cur = display_map()
        with io.open(DISPLAY, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["Internal", "Display", "Kind", "Note"])
            for r in regions:
                w.writerow([r, cur.get(r.lower(), ""), "region", ""])
            for nm in internal:
                w.writerow([nm, cur.get(nm.lower(), ""), "character", ""])
        print("wrote %s: %d rows (%d regions, %d characters)"
              % (os.path.relpath(DISPLAY, ROOT), len(regions) + len(internal),
                 len(regions), len(internal)))
        print("fill in the Display column - that is the ONLY hardcoded naming data AT3 needs")
        return
    n = len(names)
    print("named %d hashes: %s" % (n, {k: sum(1 for v in how.values() if v == k)
                                       for k in ("path", "character", "owner", "projectile")}))


if __name__ == "__main__":
    main()
