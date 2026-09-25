r"""Build a new weapon: a clone of a donor weapon, under its OWN hash, with edits.

WHAT "BUILD" DOES

    name  ->  stem  ->  two hashes       "Long Knife" -> AT3_long_knife ->
                                         weapon  game_hash("\data\prefs\Weapons\NPC\<stem>.txt")
                                         effect  game_hash("\data\prefs\Weapons\NPC\Effects\<stem>.txt")
    edits applied                        --edits <json>, through weapon_fields.py, which
                                         refuses a field it cannot locate on this donor
                                         and verifies that every byte outside the edits
                                         is unchanged
    effect pref cloned                   ONLY when a projectile / sound / impact edit or
                                         "effect_from" asks for one. 11 of 59 vanilla
                                         effect prefs are shared between weapons, so one
                                         is never edited in place: the new weapon gets
                                         its own, and its +12 is pointed at it
    closure made resident                everything both records reference, walked with
                                         weapon_fields.needs() - dwords, embedded paths,
                                         AND the per-surface impact records the engine
                                         composes from EffectMixDef names, which no
                                         dword points at
    records appended, indexed            effect pref (if any) then weapon, at the END of
                                         the target tgl; blockmap_add.py; both then
                                         VERIFIED byte for byte in the .smh
    registered                           one CustomHashes.csv row per region

It does NOT arm a character. The Character Creator's weapon slots offer every
weapon this builds.

WHY A CLONE UNDER A NEW HASH IS VALID

Bundle rule 3 is `game_hash(the path embedded in a record) == that record's
hash`. Weapon records embed no path - their only strings are the type name (and
BomberBomb's own name) - and effect prefs embed no strings at all. Same
precedent as the killer clakker's weapon 7E7DA3A9 and effects EF6E5885.

THE EDITS FILE

    {"m_damage": 60, "m_speed": 45,          weapon fields (weapon_fields.FLOATS)
     "m_weaponType": "Firearm",              Turret -> Firearm, nothing else
     "fx_projectile": "B1059BBA",            effect slots: a hash, or "" for none
     "fx_impactSounds": "...", "fx_impactEffects": "...",
     "effect_from": "5D994255"}              the REST of the effect pref from this weapon

With effect_from the projectile, sounds and impact stay the DONOR's unless they
are edited too - "other effects from" means everything except those three.

WHAT IT REFUSES - build_character.py's list (no stem, taken hash or name, target
not consistent or not round-tripping, emptygulch), plus: a donor that is not a
weapon; an effect choice that is not the right kind of record; an asset or
effect_from weapon that no numbered region or data/global holds.

BACKUPS AND REVERT are build_character.py's, byte for byte: `.buildbak_<HASH>`
on the tgl and blockmap, `CustomHashes.csv.buildbak_<HASH>_<REGION>`, restored
by copy, refused when a later build touched the same file.

    python build_weapon.py 5D994255 --name "Slow Mortar" --to 01 --edits e.json --dry-run
    python build_weapon.py 5D994255 --name "Slow Mortar" --to 01 --edits e.json
    python build_weapon.py --revert 1A2B3C4D --to 01
"""
import argparse, datetime, glob, io, json, os, shutil, struct, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rebuild_bundle as RB
import blockmap_add as BA
import port_to_utility as PT
import build_character as BC
import weapon_fields as WF
from ensure_asset import region_index
from gamehash import game_hash

ROOT = os.path.dirname(HERE)
BS = chr(92)
FX = tuple(n for n, o, t in WF.EFFECT)
FX_OFF = {n: o for n, o, t in WF.EFFECT}
_GIDX = None


def weapon_hash(stem):
    return game_hash(BS + "data" + BS + "prefs" + BS + "Weapons" + BS + "NPC" + BS + stem + ".txt")


def effect_hash(stem):
    return game_hash(BS + "data" + BS + "prefs" + BS + "Weapons" + BS + "NPC" + BS +
                     "Effects" + BS + stem + ".txt")


def _u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def global_index():
    """hash -> record for data/global - resident everywhere, never ported."""
    global _GIDX
    if _GIDX is None:
        _GIDX = {}
        for p in glob.glob(os.path.join(ROOT, "data", "global", "*.smb")):
            if os.path.basename(p).count(".") > 1:
                continue
            try:
                for r in RB.parse(open(p, "rb").read())[1]:
                    _GIDX.setdefault(r["hash"], r)
            except (Exception, SystemExit):
                continue
    return _GIDX


def desc_lookup(first):
    """hash -> descriptor: `first` region, then data/global, then any numbered region."""
    def f(h):
        if h in first:
            return first[h][1]["desc"]
        g = global_index().get(h)
        if g is not None:
            return g["desc"]
        r = BC.find_source(h)
        return BC.idx_of(r)[h][1]["desc"] if r else None
    return f


def dword_refs(desc, idx, skip=()):
    out = []
    for o in range(len(desc) - 3):
        if o in skip:
            continue
        v = _u32(desc, o)
        if v in idx and v not in out:
            out.append(v)
    return out


def smh_holds(smh, h, desc):
    """True when SOME blockmap entry for `h` carries exactly `desc`.

    Every occurrence is checked, not just the first: the new weapon's own
    descriptor contains the new effect hash at +12, so the first match for the
    effect hash can land inside the weapon's entry.
    """
    key = struct.pack("<I", h)
    i = smh.find(key)
    while i >= 0:
        if i + 20 <= len(smh):
            size = _u32(smh, i + 12)
            if size == len(desc) and smh[i + 20:i + 20 + size] == desc:
                return True
        i = smh.find(key, i + 1)
    return False


def build_one(donor, src, target, name, stem, new_w, new_e, donor_name, edits, h2p, dry):
    print("=== region %s ===" % target)
    dest, dreg, dname = PT.dest_for(target)
    bm = BA.bm_path(dreg)
    sidx = BC.idx_of(src)
    drec = sidx[donor][1]
    info = WF.locate(drec["desc"])
    if drec["kind"] != 7 or not info["ok"]:
        print("   REFUSED: %08X is not a weapon record (%s)" % (donor, info["why"]))
        return False
    desc_of = desc_lookup(sidx)
    gidx = global_index()

    wedits = {k: v for k, v in edits.items() if k not in FX and k != "effect_from"}
    fedits = {k: v for k, v in edits.items() if k in FX}
    efrom = str(edits.get("effect_from") or "").strip() or None

    # ---- the records, built and verified in memory before anything is touched
    old_ep = _u32(drec["desc"], 12)
    clone_fx = bool(fedits or efrom)
    eff_rec, eff_src, eff_desc, echanges = None, None, None, []
    if clone_fx:
        if efrom:
            fh = int(efrom, 16)
            fr = src if fh in sidx else BC.find_source(fh)
            if fr is None or not WF.is_weapon(BC.idx_of(fr)[fh][1]):
                print("   REFUSED: effects-from %s is not a weapon in any numbered region" % efrom)
                return False
            fe = _u32(BC.idx_of(fr)[fh][1]["desc"], 12)
            if fe not in BC.idx_of(fr):
                print("   REFUSED: effects-from weapon %s points at effect pref %08X, which region %s does not hold"
                      % (efrom, fe, fr))
                return False
            eff_rec, eff_src = BC.idx_of(fr)[fe][1], fr
            # Everything EXCEPT the three mapped slots comes from that weapon;
            # the three stay the donor's unless the user changed them.
            if old_ep in sidx:
                dv, dwhy = WF.read_effect(sidx[old_ep][1]["desc"], desc_of, h2p)
                for n in FX:
                    if n not in fedits and not dwhy.get(n):
                        fedits[n] = dv.get(n)
        else:
            if old_ep not in sidx:
                print("   REFUSED: the donor's effect pref %08X is not in region %s" % (old_ep, src))
                return False
            eff_rec, eff_src = sidx[old_ep][1], src
        try:
            eff_desc, echanges = WF.apply_effect(eff_rec["desc"], fedits, desc_of, h2p)
        except WF.FieldError as e:
            print("   REFUSED: %s" % e)
            return False
    try:
        w_desc, wchanges = WF.apply(drec["desc"], wedits, desc_of, h2p)
    except WF.FieldError as e:
        print("   REFUSED: %s" % e)
        return False
    if clone_fx:
        w_desc = w_desc[:12] + struct.pack("<I", new_e) + w_desc[16:]

    # ---- what has to be resident: the weapon's own references (minus the
    # effect pref it no longer uses) and, for a cloned effect pref, its slots -
    # the chosen ones from wherever they live, the rest from its source region
    plan, need = {}, []

    def take(h, r):
        for x in WF.needs(h, BC.idx_of(r)):
            if x in gidx:
                continue
            if x not in need:
                need.append(x)
            plan.setdefault(r, [])
            if x not in plan[r]:
                plan[r].append(x)

    for ref in dword_refs(w_desc, sidx, skip=(12,) if clone_fx else ()):
        if ref != donor:
            take(ref, src)
    if clone_fx:
        eidx = BC.idx_of(eff_src)
        chosen = {FX_OFF[n]: nv for n, old, nv in echanges}
        for o in range(len(eff_desc) - 3):
            ref = _u32(eff_desc, o)
            if o in chosen:
                if chosen[o] is None or ref in gidx:
                    continue
                r = eff_src if ref in eidx else (src if ref in sidx else BC.find_source(ref))
                if r is None:
                    print("   REFUSED: chosen asset %08X is in no numbered region and not in data/global" % ref)
                    return False
                take(ref, r)
            elif ref in eidx:
                take(ref, eff_src)

    raw = open(dest, "rb").read()
    hdr, recs, v, off = RB.parse(raw)
    if RB.build(hdr, recs, v, off, len(raw))[0] != raw:
        print("   REFUSED: %s does not round-trip byte-identically" % dname)
        return False
    have = {r["hash"] for r in recs}
    for hh in [new_w] + ([new_e] if clone_fx else []):
        if hh in have:
            print("   REFUSED: %08X is already in %s" % (hh, dname))
            return False
    ok, why = BC.blockmap_consistent(dreg)
    if not ok:
        print("   REFUSED: region %s blockmap is not consistent BEFORE the write: %s" % (target, why))
        return False

    print("   donor    %08X %s  (%s, from region %s)" % (donor, donor_name or "", info["type"], src))
    print("   new      %08X %s  stem %s" % (new_w, name, stem))
    if clone_fx:
        print("   effect   %08X own effect pref, cloned from %08X (region %s)%s"
              % (new_e, eff_rec["hash"], eff_src, ("  - rest of its slots from weapon " + efrom) if efrom else ""))
    else:
        print("   effect   shares the donor's effect pref")
    for n, old, nv in wchanges + echanges:
        print("   edit     %-24s %r -> %r" % (n, old, nv))
    print("   edits    %d field(s) changed" % len(wchanges + echanges))
    for r, hs in plan.items():
        print("   resident %d asset(s) from region %s%s" % (len(hs), r, "" if r != target else " (already here)"))

    if dry:
        for r, hs in plan.items():
            if r != target:
                PT.port(r, hs, dry=True, lean=True, to=target)
        print("   (dry run - nothing written)")
        return True

    bk = ".buildbak_%08X" % new_w
    csv_bk = BC.CUSTOM + ".buildbak_%08X_%s" % (new_w, target)
    for f in (dest, bm):
        shutil.copy2(f, f + bk)

    def restore(reason):
        print("   FAILED: %s" % reason)
        for f in (dest, bm):
            shutil.copy2(f + bk, f)
        if os.path.exists(csv_bk):
            shutil.copy2(csv_bk, BC.CUSTOM)
        print("   region %s restored from %s - nothing was left behind" % (target, bk))
        return False

    # 1. make everything resident
    for r, hs in plan.items():
        if r != target and hs:
            PT.port(r, hs, dry=False, lean=True, to=target)
    t_idx = region_index(target)
    missing = [h for h in need if h not in t_idx and h not in gidx]
    if missing:
        return restore("still not resident in region %s after the port: %s"
                       % (target, " ".join("%08X" % h for h in missing[:8])))

    # 2. append the effect pref (if any), then the weapon
    raw = open(dest, "rb").read()
    hdr, recs, v, off = RB.parse(raw)
    if RB.build(hdr, recs, v, off, len(raw))[0] != raw:
        return restore("%s stopped round-tripping after the port" % dname)
    add, verify = [], []
    if clone_fx:
        add.append(dict(kind=eff_rec["kind"], hash=new_e, flags=eff_rec["flags"], desc=eff_desc,
                        s2=eff_rec["s2"], s3=eff_rec["s3"], c2=0, c3=0))
        verify.append((new_e, eff_desc))
    add.append(dict(kind=drec["kind"], hash=new_w, flags=drec["flags"], desc=w_desc,
                    s2=drec["s2"], s3=drec["s3"], c2=0, c3=0))
    verify.append((new_w, w_desc))
    out, _ = RB.build(hdr, recs + add, v, off, len(raw))
    open(dest, "wb").write(out)

    # 3. index them
    rc = subprocess.run([sys.executable, os.path.join(HERE, "blockmap_add.py"), dreg, dname] +
                        ["%08X" % r["hash"] for r in add], capture_output=True, text=True)
    if rc.returncode != 0:
        return restore("blockmap_add failed: %s" % (rc.stdout + rc.stderr).strip()[-300:])

    # 4. verify - against the file the GAME reads, the .smh, not just the .smb
    live = {r["hash"]: r for r in RB.parse(open(dest, "rb").read())[1]}
    smh = open(bm, "rb").read()
    for hh, d in verify:
        if hh not in live or live[hh]["desc"] != d:
            return restore("the tgl record %08X is not the intended record after write" % hh)
        if not smh_holds(smh, hh, d):
            return restore("the blockmap entry for %08X is not the intended record byte for byte" % hh)
    ok, why = BC.blockmap_consistent(dreg)
    if not ok:
        return restore("region %s blockmap not consistent after the write: %s" % (target, why))

    # 5. register. The note names only hashes THIS build minted - char_model
    # treats every hex token in Notes as custom, so the donor's shared effect
    # pref must not be mentioned there. Donors go in ClonedFrom.
    ch = wchanges + echanges
    note = ("Built by Weapon Creator %s. Stem %s; the hash IS game_hash of "
            "\\data\\prefs\\Weapons\\NPC\\%s.txt. " % (datetime.date.today().isoformat(), stem, stem))
    note += ("Own effect pref %08X (\\data\\prefs\\Weapons\\NPC\\Effects\\%s.txt). " % (new_e, stem)
             if clone_fx else "Shares the donor's effect pref. ")
    note += ("%d field edit(s): %s." % (len(ch), ", ".join(n for n, o, x in ch))
             if ch else "Verbatim clone of the donor - no field edits.")
    cloned = "%08X %s" % (donor, donor_name or "")
    if efrom:
        cloned += " + effects from %s" % efrom.upper()
    try:
        if os.path.exists(BC.CUSTOM):
            shutil.copy2(BC.CUSTOM, csv_bk)
        BC.append_custom_row({"Name": name, "Hash": "%08X" % new_w, "Region": target,
                              "ClonedFrom": cloned, "Notes": note})
    except Exception as e:
        return restore("could not register the name: %s" % e)
    print("   BUILT %08X into region %s with %d edit(s)" % (new_w, target, len(ch)))
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("donor", nargs="?")
    ap.add_argument("--from", dest="src")
    ap.add_argument("--name")
    ap.add_argument("--donor-name", default="")
    ap.add_argument("--to", action="append", default=[])
    ap.add_argument("--edits", help="JSON file: {field: value}")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--revert")
    a = ap.parse_args()

    if a.revert:
        if len(a.to) != 1:
            sys.exit("--revert needs exactly one --to")
        BC.revert(int(a.revert, 16), a.to[0])
        return 0

    if not a.donor or not a.name or not a.to:
        sys.exit("need: <donor weapon hash> --name <name> --to <region> [--to ...]")
    donor = int(a.donor, 16)
    name = a.name.strip()
    stem = BC.stem_of(name)
    if not stem:
        print("REFUSED: '%s' has no letters or digits, so it cannot form a stem" % name)
        return 1
    new_w, new_e = weapon_hash(stem), effect_hash(stem)
    known = BC.live_hashes()
    for hh, what in ((new_w, "weapon"), (new_e, "effect pref")):
        if hh in known:
            print("REFUSED: %s hash %08X (from '%s') already exists in the install - choose another name"
                  % (what, hh, name))
            return 1
    for r in BC.custom_rows():
        if (r.get("Name") or "").strip().lower() == name.lower():
            print("REFUSED: the name '%s' is already %s in the library" % (name, (r.get("Hash") or "").upper()))
            return 1

    edits = {}
    if a.edits:
        try:
            edits = json.load(io.open(a.edits, encoding="utf-8-sig"))
        except (OSError, ValueError) as e:
            print("REFUSED: could not read edits file: %s" % e)
            return 1
    import resolve_assets as RA
    h2p = {}
    for q in RA.harvest():
        h2p.setdefault(game_hash(q), q)

    src = a.src or BC.find_source(donor)
    if not src or donor not in BC.idx_of(src):
        print("REFUSED: donor %08X is not in %s" % (donor, ("region_" + a.src) if a.src else "any numbered region"))
        return 1

    results = []
    for t in a.to:
        results.append(build_one(donor, src, t, name, stem, new_w, new_e, a.donor_name, edits, h2p, a.dry_run))
        if not results[-1]:
            break
    return 0 if results and all(results) else 1


if __name__ == "__main__":
    sys.exit(main() or 0)
