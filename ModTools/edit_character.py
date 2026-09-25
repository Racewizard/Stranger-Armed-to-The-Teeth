r"""Edit an EXISTING character record in place - vanilla or custom - in the regions chosen.

build_character.py makes a NEW record under a new hash. This changes the record
that is already there and keeps its hash, so every spawn that uses it changes
too: give the Outlaw Shooter a new weapon here and every outlaw shooter in the
chosen regions carries it.

WHAT IT DOES, PER REGION
    locate      the character's one copy in the region tgl (every character
                surveyed has exactly one copy per region, in the tgl, with one
                blockmap entry - a character anywhere else is refused)
    edit        char_fields.apply on THAT region's copy. Regions hold their own
                copies, so each is edited and verified separately
    port        any newly chosen mesh, icon, weapon, spawner or ammo pref the
                region lacks, walked with weapon_fields.needs()
    rewrite     the tgl rebuilt with the edited descriptor - rebuild_bundle lays
                every cursor out again, so a length change (voice, m_affList) is
                fine - then the region blockmap regenerated from its bundles
                (check_groups.rebuild)
    verify      the tgl record and the .smh entry both byte-identical to the
                edited descriptor; check_groups consistent

WHY REGENERATING THE BLOCKMAP IS SAFE HERE. It refuses unless the region's
blockmap is `consistent` BEFORE anything is written, so the regenerated file
differs from the old one only by this edit. The .smh holds the copy the game
loads - an in-place edit that skipped it would change nothing in game.

BACKUPS. tgl and blockmap are copied to <file>.editbak_<HASH>_<stamp> before the
first write and restored on any failure. --revert restores the newest pair for
that hash, refuses if a later build, edit or delete touched the files, and
removes the pair it consumed so a second revert reaches the edit before it.

It does not rename a character or change its skeleton or template. Attachments
are edited like any other field; a newly worn mesh is ported with its textures.

    python edit_character.py FFFC00CB --to 00 --to 01 --edits e.json --dry-run
    python edit_character.py FFFC00CB --to 01 --edits e.json
    python edit_character.py --revert FFFC00CB --to 01
"""
import argparse, datetime, glob, io, json, os, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rebuild_bundle as RB
import blockmap_add as BA
import port_to_utility as PT
import check_groups as CG
import build_character as BC
import char_fields as CF
import weapon_fields as WF
import spray as SP
from build_weapon import smh_holds
from ensure_asset import region_index
from gamehash import game_hash

WEAPON_SLOTS = ("m_meleeWeapon", "m_rangedWeapon")


def chosen_assets(changes):
    """(field, hash) for every record an edit newly points at."""
    chosen = {n: nv for n, old, nv in changes}
    out = []
    for n in ["m_geometry", "m_icon", "m_onGibSpawnNPC", "m_gibEffect"] + list(WEAPON_SLOTS) + [t[0] for t in CF.TAIL if t[2] == "h"]:
        if chosen.get(n):
            out.append((n, int(chosen[n], 16)))
    for x in (chosen.get("m_affList") or []):
        out.append(("m_affList", int(x, 16)))
    for e in (chosen.get("m_defaultAttachments") or []):
        out.append(("attachment", int(e["geo"], 16)))
    return out


def edit_one(h, region, edits, known, h2p, global_h, dry, sprays=None):
    print("=== region %s ===" % region)
    if region not in BC.NUMBERED:
        print("   REFUSED: %s is not a shipped region - only those can be edited in place" % region)
        return False
    dest, dreg, dname = PT.dest_for(region)
    bm = BA.bm_path(dreg)
    raw = open(dest, "rb").read()
    hdr, recs, v, off = RB.parse(raw)
    if RB.build(hdr, recs, v, off, len(raw))[0] != raw:
        print("   REFUSED: %s does not round-trip byte-identically" % dname)
        return False
    mine = [r for r in recs if r["hash"] == h]
    if len(mine) != 1:
        ridx = BC.idx_of(region)
        if h in ridx:
            print("   REFUSED: %08X lives in %s, not %s - editing a character outside the region tgl is not supported"
                  % (h, ", ".join(ridx[h][0]), dname))
        else:
            print("   REFUSED: %08X is not in region %s" % (h, region))
        return False
    notes = []
    try:
        new_desc, changes = CF.apply(mine[0]["desc"], edits, known, h2p, warnings=notes)
    except CF.FieldError as e:
        print("   REFUSED: %s" % e)
        return False
    for n_ in notes:
        print("   NOTE: %s" % n_)
    for n, old, nv in changes:
        print("   edit     %-44s %s -> %s" % (n, CF.describe(n, old), CF.describe(n, nv)))
    if not changes:
        print("   UNCHANGED %08X in region %s - this region's copy already has every value" % (h, region))
        return True
    ok, why = BC.blockmap_consistent(dreg)
    if not ok:
        print("   REFUSED: region %s blockmap is not consistent BEFORE the write: %s" % (region, why))
        return False

    ridx = BC.idx_of(region)
    fresh = BC.fresh_sprays(sprays or {})
    plan = {}
    for n, x in chosen_assets(changes):
        # A spray minted by this save exists nowhere to port FROM - it is
        # appended below. What must be resident is what it drops.
        if x in fresh:
            n, x = "spray collectable", fresh[x][2]
        if n == "m_onGibSpawnNPC":
            gr = region if x in ridx else BC.find_source(x)
            if gr is None or not CF.is_character(BC.idx_of(gr)[x][1]["desc"]):
                print("   REFUSED: m_onGibSpawnNPC %08X is not a character record" % x)
                return False
        if x in global_h or x in ridx:
            continue
        src = BC.find_source(x)
        if src is None:
            print("   REFUSED: %s %08X is in no numbered region and not in data/global" % (n, x))
            return False
        if n in WEAPON_SLOTS and not WF.is_weapon(BC.idx_of(src)[x][1]):
            print("   REFUSED: %s %08X is not a weapon record" % (n, x))
            return False
        for y in WF.needs(x, BC.idx_of(src)):
            if y not in global_h and y not in ridx:
                plan.setdefault(src, [])
                if y not in plan[src]:
                    plan[src].append(y)
    for src, hs in plan.items():
        print("   port     %d asset(s) from region %s" % (len(hs), src))
    print("   edits    %d field(s) changed" % len(changes))
    for x, (f, d, c) in fresh.items():
        print("   spray    %08X %-40s %s  (new)" % (x, f, SP.describe(d)))
    if dry:
        for src, hs in plan.items():
            PT.port(src, hs, dry=True, lean=True, to=region)
        print("   (dry run - nothing written)")
        return True

    # Microseconds: two saves in the same second must not share a backup name.
    bk = ".editbak_%08X_%s" % (h, datetime.datetime.now().strftime("%Y%m%d%H%M%S%f"))
    for f in (dest, bm):
        shutil.copy2(f, f + bk)

    def restore(reason):
        print("   FAILED: %s" % reason)
        for f in (dest, bm):
            shutil.copy2(f + bk, f)
        print("   region %s restored from %s - nothing was left behind" % (region, bk))
        return False

    for src, hs in plan.items():
        PT.port(src, hs, dry=False, lean=True, to=region)
    if plan:
        t_idx = region_index(region)
        missing = [y for hs in plan.values() for y in hs if y not in t_idx]
        if missing:
            return restore("still not resident after the port: %s" % " ".join("%08X" % y for y in missing[:8]))

    raw = open(dest, "rb").read()
    hdr, recs, v, off = RB.parse(raw)
    if RB.build(hdr, recs, v, off, len(raw))[0] != raw:
        return restore("%s stopped round-tripping after the port" % dname)
    out = []
    for r in recs:
        if r["hash"] == h:
            r = dict(r)
            r["desc"] = new_desc
        out.append(r)
    have = {r["hash"] for r in recs}
    minted = [SP.record(x, d) for x, (f, d, c) in fresh.items() if x not in have]
    out = out + minted
    new, _ = RB.build(hdr, out, v, off, len(raw))
    open(dest, "wb").write(new)
    try:
        smh, used = CG.rebuild(dreg)
    except RuntimeError as e:
        return restore("the blockmap could not be regenerated: %s" % e)
    open(bm, "wb").write(smh)

    # verify - against the file the GAME reads, the .smh, not just the .smb
    live = [r for r in RB.parse(open(dest, "rb").read())[1] if r["hash"] == h]
    if len(live) != 1 or live[0]["desc"] != new_desc:
        return restore("the tgl record is not the edited record after write")
    if not smh_holds(open(bm, "rb").read(), h, new_desc):
        return restore("the blockmap entry is not the edited record byte for byte")
    smh_now = open(bm, "rb").read()
    for m in minted:
        if not smh_holds(smh_now, m["hash"], m["desc"]):
            return restore("the blockmap entry for spray %08X is not the record byte for byte" % m["hash"])
    ok, why = BC.blockmap_consistent(dreg)
    if not ok:
        return restore("region %s blockmap not consistent after the write: %s" % (region, why))
    print("   EDITED %08X in region %s with %d edit(s)" % (h, region, len(changes)))
    return True


def revert(h, region):
    dest, dreg, dname = PT.dest_for(region)
    bm = BA.bm_path(dreg)
    backs = sorted(glob.glob(glob.escape(dest) + ".editbak_%08X_*" % h))
    if not backs:
        sys.exit("no edit backup of %08X in region %s - nothing to revert" % (h, region))
    back_t = backs[-1]
    stamp = back_t.rsplit("_", 1)[1]
    back_b = bm + ".editbak_%08X_%s" % (h, stamp)
    if not os.path.exists(back_b):
        sys.exit("REFUSED: %s has no matching blockmap backup" % os.path.basename(back_t))
    pairs = [(dest, back_t), (bm, back_b)]
    for live, back in pairs:
        # Refuse if a LATER build, edit or delete touched this file.
        for other in BC.backups_of(live):
            if other != back and os.path.getmtime(other) > os.path.getmtime(back):
                sys.exit("REFUSED: %s was changed again after this edit (%s) - revert that first"
                         % (os.path.basename(live), os.path.basename(other)))
    for live, back in pairs:
        shutil.copy2(back, live)
    for live, back in pairs:
        os.remove(back)
    print("REVERTED edit of %08X in region %s (restored the files from %s)" % (h, region, stamp))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("hash", nargs="?")
    ap.add_argument("--to", action="append", default=[])
    ap.add_argument("--edits", help="JSON file: {field: value}")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--revert")
    a = ap.parse_args()

    if a.revert:
        if len(a.to) != 1:
            sys.exit("--revert needs exactly one --to")
        revert(int(a.revert, 16), a.to[0])
        return 0
    if not a.hash or not a.to or not a.edits:
        sys.exit("need: <hash> --to <region> [--to ...] --edits <json>")
    h = int(a.hash, 16)
    try:
        edits = json.load(io.open(a.edits, encoding="utf-8-sig"))
    except (OSError, ValueError) as e:
        print("REFUSED: could not read edits file: %s" % e)
        return 1
    if not isinstance(edits, dict) or not edits:
        print("REFUSED: the edits file holds no edits")
        return 1
    import resolve_assets as RA
    h2p = {}
    for q in RA.harvest():
        h2p.setdefault(game_hash(q), q)
    known = BC.live_hashes()
    global_h = BC.live_hashes("global")
    try:
        sprays = SP.prepare(edits, known, BC.existing_desc)
    except SP.SprayError as e:
        print("REFUSED: %s" % e)
        return 1
    # Every region is attempted: each one restores itself on failure, so one
    # refusal does not leave the others unedited without saying so.
    results = [edit_one(h, t, edits, known, h2p, global_h, a.dry_run, sprays) for t in a.to]
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main() or 0)
