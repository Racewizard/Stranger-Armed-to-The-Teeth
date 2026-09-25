r"""Edit an EXISTING weapon in place - vanilla or custom - in the regions chosen.

build_weapon.py makes a NEW weapon under a new hash. This changes the weapon that
is already there and keeps its hash, so every character carrying it changes too:
give a rifle a bigger clip and every character armed with it, in the regions
saved to, gets the bigger clip.

PER REGION
    locate    the weapon's one copy in the region tgl - all 167 weapon copies
              surveyed (2026-09-13) sit in the tgl, one per region
    weapon    weapon_fields.apply on THAT region's copy
    effects   a projectile / sound / impact edit, or "effect_from", changes the
              weapon's EFFECT pref (+12). 46 of the 167 region copies share
              theirs with another weapon, so
                used by nothing else in the region  -> edited in place
                shared                              -> this weapon gets its own
                  copy, game_hash("\data\prefs\Weapons\NPC\Effects\AT3_edit_<HASH>.txt"),
                  and +12 is pointed at it; the other users keep theirs untouched
    port      anything the edited effect pref points at that the region lacks,
              walked with weapon_fields.needs() - per-surface impact records too
    rewrite   the tgl rebuilt, the blockmap regenerated from its bundles (refused
              unless it was consistent first), and every written record verified
              byte for byte in the .smh the game reads

The edits file is build_weapon.py's.

BACKUPS AND REVERT are edit_character.py's: <file>.editbak_<HASH>_<stamp> on the
tgl and blockmap; --revert restores the newest pair for the weapon, refuses if a
later build, edit or delete touched the files, and consumes the pair.

    python edit_weapon.py F0DF813D --to 01 --edits e.json --dry-run
    python edit_weapon.py F0DF813D --to 01 --to 02 --edits e.json
    python edit_weapon.py --revert F0DF813D --to 01
"""
import argparse, datetime, io, json, os, shutil, struct, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rebuild_bundle as RB
import blockmap_add as BA
import port_to_utility as PT
import check_groups as CG
import build_character as BC
import weapon_fields as WF
from build_weapon import FX, FX_OFF, smh_holds, global_index, desc_lookup, effect_hash
from edit_character import revert
from ensure_asset import region_index
from gamehash import game_hash


def _u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def own_effect_hash(h):
    """The effect pref a shared-effect weapon gets when its effects are edited."""
    return effect_hash("AT3_edit_%08X" % h)


def referrers(idx, h, skip):
    """Records in a region whose descriptor holds hash `h` - its other users."""
    key = struct.pack("<I", h)
    return [x for x, (fns, rec) in idx.items() if x not in skip and key in rec["desc"]]


def edit_one(h, region, edits, h2p, known, dry):
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
    ridx = region_index(region)
    mine = [r for r in recs if r["hash"] == h]
    if len(mine) != 1:
        if h in ridx:
            print("   REFUSED: %08X lives in %s, not %s - editing a weapon outside the region tgl is not supported"
                  % (h, ", ".join(ridx[h][0]), dname))
        else:
            print("   REFUSED: %08X is not in region %s" % (h, region))
        return False
    wrec = mine[0]
    if not WF.is_weapon(wrec):
        print("   REFUSED: %08X is not a weapon record" % h)
        return False
    desc_of = desc_lookup(ridx)
    gidx = global_index()

    wedits = {k: x for k, x in edits.items() if k not in FX and k != "effect_from"}
    fedits = {k: x for k, x in edits.items() if k in FX}
    efrom = str(edits.get("effect_from") or "").strip() or None
    try:
        w_desc, wchanges = WF.apply(wrec["desc"], wedits, desc_of, h2p)
    except WF.FieldError as e:
        print("   REFUSED: %s" % e)
        return False

    # ---- the effect pref: unchanged, edited in place, or copied for this weapon
    old_ep = _u32(wrec["desc"], 12)
    new_ep, eff_mode, eff_desc, eff_base, echanges, others = old_ep, None, None, None, [], []
    if fedits or efrom:
        if old_ep not in ridx:
            print("   REFUSED: this weapon's effect pref %08X is not in region %s, so its projectile and impact "
                  "cannot be changed here" % (old_ep, region))
            return False
        cur = ridx[old_ep][1]
        eff_base = cur
        if efrom:
            fh = int(efrom, 16)
            fr = region if fh in ridx else BC.find_source(fh)
            if fr is None or not WF.is_weapon(BC.idx_of(fr)[fh][1]):
                print("   REFUSED: effects-from %s is not a weapon in any numbered region" % efrom)
                return False
            fe = _u32(BC.idx_of(fr)[fh][1]["desc"], 12)
            if fe not in BC.idx_of(fr):
                print("   REFUSED: effects-from weapon %s points at effect pref %08X, which region %s does not hold"
                      % (efrom, fe, fr))
                return False
            eff_base = BC.idx_of(fr)[fe][1]
            # "Other effects from" means everything EXCEPT the three mapped
            # slots, which stay this weapon's unless they were edited too.
            cv, cwhy = WF.read_effect(cur["desc"], desc_of, h2p)
            for n in FX:
                if n not in fedits and not cwhy.get(n):
                    fedits[n] = cv.get(n)
        try:
            eff_desc, echanges = WF.apply_effect(eff_base["desc"], fedits, desc_of, h2p)
        except WF.FieldError as e:
            print("   REFUSED: %s" % e)
            return False
        if (eff_desc, eff_base["s2"], eff_base["s3"]) == (cur["desc"], cur["s2"], cur["s3"]):
            eff_desc, echanges = None, []          # the effect pref would end up exactly as it is
        else:
            others = referrers(ridx, old_ep, skip={h, old_ep})
            if others:
                new_ep = own_effect_hash(h)
                if new_ep in ridx:
                    print("   REFUSED: %08X (this weapon's own effect copy) is already in region %s, but the weapon "
                          "does not point at it" % (new_ep, region))
                    return False
                eff_mode = "own copy"
            else:
                if old_ep not in {r["hash"] for r in recs}:
                    print("   REFUSED: effect pref %08X lives in %s, not %s" % (old_ep, ", ".join(ridx[old_ep][0]), dname))
                    return False
                eff_mode = "in place"
    if new_ep != old_ep:
        w_desc = w_desc[:12] + struct.pack("<I", new_ep) + w_desc[16:]

    changes = wchanges + echanges
    n_edits = len(changes) + (1 if efrom and eff_desc is not None else 0)
    for n, old, nv in changes:
        print("   edit     %-24s %r -> %r" % (n, old, nv))
    if eff_desc is not None:
        if eff_mode == "in place":
            print("   effect   %08X edited in place - nothing else in region %s uses it" % (old_ep, region))
        else:
            print("   effect   %08X is this weapon's own new copy - %08X stays as it is for %s"
                  % (new_ep, old_ep, " ".join("%08X" % x for x in others[:6])))
        if efrom:
            print("   effect   the rest of its slots from weapon %s" % efrom.upper())
    if not n_edits:
        print("   UNCHANGED %08X in region %s - this region's copy already has every value" % (h, region))
        return True
    ok, why = BC.blockmap_consistent(dreg)
    if not ok:
        print("   REFUSED: region %s blockmap is not consistent BEFORE the write: %s" % (region, why))
        return False

    # ---- what the edited effect pref needs that the region lacks
    plan, need = {}, []

    def take(ref, src):
        for x in WF.needs(ref, BC.idx_of(src)):
            if x in gidx or x in ridx:
                continue
            if x not in need:
                need.append(x)
            plan.setdefault(src, [])
            if x not in plan[src]:
                plan[src].append(x)

    if eff_desc is not None:
        chosen = {FX_OFF[n] for n, o, nv in echanges}
        for o in range(len(eff_desc) - 3):
            ref = _u32(eff_desc, o)
            if ref in (WF.NULL, 0) or ref in gidx or ref not in known:
                continue
            if ref in ridx:
                # Resident, but an impact set's per-surface records are separate
                # records that may not be.
                for c in (WF.composed(ridx[ref][1]["desc"]) if ridx[ref][1]["kind"] == 7 else []):
                    if c not in ridx and c not in gidx:
                        s = BC.find_source(c)
                        if s:
                            take(c, s)
                continue
            src = BC.find_source(ref)
            if src is None:
                if o in chosen:
                    print("   REFUSED: chosen asset %08X is in no numbered region and not in data/global" % ref)
                    return False
                continue
            take(ref, src)
    for src, hs in plan.items():
        print("   port     %d asset(s) from region %s" % (len(hs), src))
    print("   edits    %d field(s) changed" % n_edits)
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
        missing = [y for y in need if y not in t_idx]
        if missing:
            return restore("still not resident after the port: %s" % " ".join("%08X" % y for y in missing[:8]))

    raw = open(dest, "rb").read()
    hdr, recs, v, off = RB.parse(raw)
    if RB.build(hdr, recs, v, off, len(raw))[0] != raw:
        return restore("%s stopped round-tripping after the port" % dname)
    shared_before = {r["hash"]: r["desc"] for r in recs if r["hash"] == old_ep}
    out = []
    for r in recs:
        if r["hash"] == h:
            r = dict(r)
            r["desc"] = w_desc
        elif eff_mode == "in place" and r["hash"] == old_ep:
            r = dict(r)
            r["desc"], r["s2"], r["s3"] = eff_desc, eff_base["s2"], eff_base["s3"]
        out.append(r)
    if eff_mode == "own copy":
        out.append(dict(kind=eff_base["kind"], hash=new_ep, flags=eff_base["flags"], desc=eff_desc,
                        s2=eff_base["s2"], s3=eff_base["s3"], c2=0, c3=0))
    new, _ = RB.build(hdr, out, v, off, len(raw))
    open(dest, "wb").write(new)
    try:
        smh, used = CG.rebuild(dreg)
    except RuntimeError as e:
        return restore("the blockmap could not be regenerated: %s" % e)
    open(bm, "wb").write(smh)

    # ---- verify against the file the GAME reads, the .smh, not just the .smb
    live = {r["hash"]: r for r in RB.parse(open(dest, "rb").read())[1]}
    smh = open(bm, "rb").read()
    for hh, d in [(h, w_desc)] + ([(new_ep, eff_desc)] if eff_desc is not None else []):
        if hh not in live or live[hh]["desc"] != d:
            return restore("the tgl record %08X is not the edited record after write" % hh)
        if not smh_holds(smh, hh, d):
            return restore("the blockmap entry for %08X is not the edited record byte for byte" % hh)
    if eff_mode == "own copy" and old_ep in shared_before and live.get(old_ep, {}).get("desc") != shared_before[old_ep]:
        return restore("the shared effect pref %08X changed - it must stay as it was for its other users" % old_ep)
    ok, why = BC.blockmap_consistent(dreg)
    if not ok:
        return restore("region %s blockmap not consistent after the write: %s" % (region, why))
    print("   EDITED %08X in region %s with %d edit(s)" % (h, region, n_edits))
    return True


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
        sys.exit("need: <weapon hash> --to <region> [--to ...] --edits <json>")
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
    # Every region is attempted: each restores itself on failure, so one refusal
    # does not leave the others unedited without saying so.
    results = [edit_one(h, t, edits, h2p, known, a.dry_run) for t in a.to]
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main() or 0)
