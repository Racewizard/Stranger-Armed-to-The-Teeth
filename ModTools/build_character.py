r"""Build a new character: a clone of a donor, under its OWN hash, with edits.

WHAT "BUILD" DOES

    name  ->  stem  ->  hash         "Test Palooka" -> AT3_test_palooka ->
                                     game_hash("\data\prefs\Characters\<stem>Prefs.txt")
    edits applied                    --edits <json>: field -> value, written
                                     into the clone through char_fields.py
                                     (which refuses any field it cannot locate
                                     on this donor, and verifies every edited
                                     field reads back and nothing else moved)
    closure made resident            the donor's mesh, textures, weapons and
                                     animation config - PLUS any newly chosen
                                     mesh, bounty icon, collectable spawner or
                                     weapon, ported from whichever region holds
                                     it. Walked with weapon_fields.needs(), so a
                                     weapon's per-surface impact records - named
                                     only by strings, never by a dword - travel too
    record appended                  at the END of the target tgl
    blockmap indexed                 blockmap_add.py, then VERIFIED: the .smh
                                     entry must equal the edited record byte
                                     for byte
    registered                       one CustomHashes.csv row per region

It does NOT place a spawn instance - that is the Spawns Editor's job.

WHY A CLONE UNDER A NEW HASH IS VALID

Bundle rule 3 is `game_hash(the path embedded in a record) == that record's
hash`. Character records embed NO path of their own - checked on Outlaw
Artillery, Killer Clakker and the vanilla Outlaw Cutter. The only path string
inside is m_animationConfigFile, which names a different record.

WHY THE ANIMATION CONFIG IS PASSED EXPLICITLY

`closure()` follows dwords. The animation config is referenced BY PATH, so a
dword closure never reaches it; its hash is computed from the path and added
to the port by hand.

WHAT IT REFUSES

  * a name with no letters or digits
  * a hash that already exists anywhere in the install, or a name already in
    CustomHashes.csv
  * an edit char_fields cannot write on this donor (it names the reason)
  * a newly chosen asset that is in no numbered region
  * a target whose blockmap is not `consistent` BEFORE the write
  * a target tgl that does not round-trip byte-identically
  * emptygulch - port_to_utility refuses it; its bundles are never loaded

BACKUPS AND REVERT - BYTE-EXACT

Before the first write to a region, its tgl and blockmap are copied to
`<file>.buildbak_<HASH>`; before the name is registered, CustomHashes.csv is
copied to `CustomHashes.csv.buildbak_<HASH>_<REGION>` (per region - a
two-region build registers twice). Any failure restores what was touched, and
`--revert` restores the same files by COPY. blockmap_add's own `.bmaddbak` is
deliberately NOT used: it is made once and never refreshed.

    python build_character.py 35179A52 --from 02 --name "Tiny Momma" --to 01 --edits edits.json --dry-run
    python build_character.py 35179A52 --from 02 --name "Tiny Momma" --to 01 --edits edits.json
    python build_character.py --revert 1A2B3C4D --to 01
"""
import argparse, csv, datetime, glob, io, json, os, re, shutil, struct, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rebuild_bundle as RB
import blockmap_add as BA
import port_to_utility as PT
import char_model as CM
import char_fields as CF
import weapon_fields as WF
import spray as SP
from ensure_asset import region_index, closure
from gamehash import game_hash

ROOT = os.path.dirname(HERE)
BS = chr(92)
CUSTOM = os.path.join(ROOT, "StrangerAT3", "CustomHashes.csv")
FIELDS = ["Name", "Hash", "Region", "ClonedFrom", "Notes"]
NUMBERED = ("00", "01", "02", "02a", "03", "04", "05", "06")
_IDX = {}


def idx_of(region):
    if region not in _IDX:
        _IDX[region] = region_index(region)
    return _IDX[region]


def stem_of(name):
    """Same rule as the launcher's ConvertTo-AT3Stem - they must agree."""
    s = re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")
    return ("AT3_" + s) if s else None


def stem_hash(stem):
    return game_hash(BS + "data" + BS + "prefs" + BS + "Characters" + BS + stem + "Prefs.txt")


def live_hashes(where="**"):
    """Every record hash on disk under data/ (or data/<where>)."""
    out = set()
    for p in glob.glob(os.path.join(ROOT, "data", where, "*.smb"), recursive=True):
        if os.path.basename(p).count(".") > 1:
            continue
        try:
            for r in RB.parse(open(p, "rb").read())[1]:
                out.add(r["hash"])
        except (Exception, SystemExit):
            continue
    return out


def custom_rows():
    if not os.path.exists(CUSTOM):
        return []
    with io.open(CUSTOM, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def append_custom_row(row):
    """Append ONE row as raw bytes - every existing byte of the file is kept."""
    raw = open(CUSTOM, "rb").read() if os.path.exists(CUSTOM) else b""
    eol = "\r\n" if (not raw or b"\r\n" in raw) else "\n"
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=FIELDS, lineterminator=eol, extrasaction="ignore")
    if not raw:
        w.writeheader()
    w.writerow({k: row.get(k, "") for k in FIELDS})
    add = buf.getvalue().encode("utf-8")
    if raw and not raw.endswith(eol.encode()):
        add = eol.encode() + add
    with open(CUSTOM, "ab") as f:
        f.write(add)


def backups_of(live):
    """Every per-hash backup a build, edit or delete left beside `live`."""
    return [p for sfx in (".buildbak_*", ".editbak_*", ".deletebak_*")
            for p in glob.glob(glob.escape(live) + sfx)]


def blockmap_consistent(region):
    rc = subprocess.run([sys.executable, os.path.join(HERE, "check_groups.py"), region],
                        capture_output=True, text=True)
    tail = (rc.stdout + rc.stderr).strip().splitlines()
    return "consistent" in rc.stdout, (tail[-1] if tail else "")


def find_source(h):
    for r in NUMBERED:
        try:
            if h in idx_of(r):
                return r
        except (Exception, SystemExit):
            continue
    return None


def existing_desc(h):
    """The desc of `h` wherever a numbered region holds it, else None."""
    r = find_source(h)
    return idx_of(r)[h][1]["desc"] if r else None


def fresh_sprays(sprays):
    """The custom sprays no numbered region holds yet - these get appended.
    One that already exists somewhere is an ordinary asset and is ported."""
    return {h: s for h, s in sprays.items() if find_source(h) is None}


def build_one(donor, src, target, name, stem, new, donor_name, edits, known, h2p, dry, sprays=None):
    print("=== region %s ===" % target)
    dest, dreg, dname = PT.dest_for(target)
    bm = BA.bm_path(dreg)
    src_idx = idx_of(src)
    drec = src_idx[donor][1]
    cp = CM.config_path(drec["desc"])
    if drec["kind"] != 7 or not cp:
        print("   REFUSED: %08X is not a character record (no animation config path)" % donor)
        return False
    cfgh = game_hash(cp)

    # the edited record, built and verified in memory before anything is touched
    clone_desc, changes, notes = drec["desc"], [], []
    if edits:
        try:
            clone_desc, changes = CF.apply(drec["desc"], edits, known, h2p, warnings=notes)
        except CF.FieldError as e:
            print("   REFUSED: %s" % e)
            return False
    for n_ in notes:
        print("   NOTE: %s" % n_)
    chosen = {n: v for n, old, v in changes}
    fresh = fresh_sprays(sprays or {})
    extra = []
    for n in ["m_geometry", "m_icon", "m_meleeWeapon", "m_rangedWeapon", "m_onGibSpawnNPC", "m_gibEffect"] + [t[0] for t in CF.TAIL if t[2] == "h"]:
        if chosen.get(n):
            h = int(chosen[n], 16)
            # A spray minted by this build exists nowhere to port FROM - it is
            # appended below. What must be resident is what it drops.
            if h in fresh:
                extra.append(("spray collectable", fresh[h][2]))
            else:
                extra.append((n, h))
    # m_affList entries are records too - every player ammo pref is global or
    # in every numbered region today, but a list is checked like any asset.
    for x in (chosen.get("m_affList") or []):
        extra.append(("m_affList", int(x, 16)))
    # Attachment meshes: any geometry may be worn, so each one is ported with
    # its textures from wherever it lives.
    for e in (chosen.get("m_defaultAttachments") or []):
        extra.append(("attachment", int(e["geo"], 16)))

    raw = open(dest, "rb").read()
    hdr, recs, v, off = RB.parse(raw)
    if RB.build(hdr, recs, v, off, len(raw))[0] != raw:
        print("   REFUSED: %s does not round-trip byte-identically" % dname)
        return False
    if new in {r["hash"] for r in recs}:
        print("   REFUSED: %08X is already in %s" % (new, dname))
        return False
    ok, why = blockmap_consistent(dreg)
    if not ok:
        print("   REFUSED: region %s blockmap is not consistent BEFORE the write: %s" % (target, why))
        return False

    global_h = live_hashes("global")
    plan = {}                                   # source region -> [hashes to port]
    need = []
    for h in [x for x in WF.needs(donor, src_idx) if x != donor] + [cfgh]:
        if h not in need:
            need.append(h)
        if h in src_idx and h not in global_h:
            plan.setdefault(src, [])
            if h not in plan[src]:
                plan[src].append(h)
    for n, h in extra:
        if n == "m_onGibSpawnNPC":
            # Checked before the residency shortcut: a hash that happens to be
            # resident is still refused unless it really is a character.
            gr = target if h in idx_of(target) else (src if h in src_idx else find_source(h))
            if gr is None or not CF.is_character(idx_of(gr)[h][1]["desc"]):
                print("   REFUSED: m_onGibSpawnNPC %08X is not a character record" % h)
                return False
        if h in global_h:
            continue                  # resident everywhere; nothing to port
        r = src if h in src_idx else find_source(h)
        if r is None:
            print("   REFUSED: newly chosen asset %08X is not in any numbered region" % h)
            return False
        if n in ("m_meleeWeapon", "m_rangedWeapon") and not WF.is_weapon(idx_of(r)[h][1]):
            print("   REFUSED: %s %08X is not a weapon record" % (n, h))
            return False
        for x in WF.needs(h, idx_of(r)):
            if x not in need:
                need.append(x)
            if x not in global_h:
                plan.setdefault(r, [])
                if x not in plan[r]:
                    plan[r].append(x)

    print("   donor    %08X %s  (from region %s)" % (donor, donor_name or "", src))
    print("   new      %08X %s  stem %s" % (new, name, stem))
    print("   config   %08X %s" % (cfgh, cp))
    for n, old, nv in changes:
        print("   edit     %-44s %s -> %s" % (n, CF.describe(n, old), CF.describe(n, nv)))
    print("   edits    %d field(s) changed" % len(changes))
    for h, (f, d, c) in fresh.items():
        print("   spray    %08X %-40s %s  (new)" % (h, f, SP.describe(d)))
    for r, hs in plan.items():
        print("   resident %d asset(s) from region %s%s" % (len(hs), r, "" if r != target else " (already here)"))

    if dry:
        for r, hs in plan.items():
            if r != target:
                PT.port(r, hs, dry=True, lean=True, to=target)
        print("   (dry run - nothing written)")
        return True

    bk = ".buildbak_%08X" % new
    csv_bk = CUSTOM + ".buildbak_%08X_%s" % (new, target)
    for f in (dest, bm):
        shutil.copy2(f, f + bk)

    def restore(reason):
        print("   FAILED: %s" % reason)
        for f in (dest, bm):
            shutil.copy2(f + bk, f)
        if os.path.exists(csv_bk):
            shutil.copy2(csv_bk, CUSTOM)
        print("   region %s restored from %s - nothing was left behind" % (target, bk))
        return False

    # 1. make the closure resident - the donor's and any newly chosen assets'
    for r, hs in plan.items():
        if r != target and hs:
            PT.port(r, hs, dry=False, lean=True, to=target)
    t_idx = region_index(target)
    missing = [h for h in need if h not in t_idx and h not in global_h]
    if missing:
        return restore("still not resident in region %s after the port: %s"
                       % (target, " ".join("%08X" % h for h in missing[:8])))

    # 2. append the (edited) clone
    raw = open(dest, "rb").read()
    hdr, recs, v, off = RB.parse(raw)
    if RB.build(hdr, recs, v, off, len(raw))[0] != raw:
        return restore("%s stopped round-tripping after the port" % dname)
    clone = dict(kind=drec["kind"], hash=new, flags=drec["flags"], desc=clone_desc,
                 s2=drec["s2"], s3=drec["s3"], c2=0, c3=0)
    # Fresh sprays go in BEFORE the character that points at them.
    have = {r["hash"] for r in recs}
    minted = [SP.record(h, d) for h, (f, d, c) in fresh.items() if h not in have]
    out, _ = RB.build(hdr, recs + minted + [clone], v, off, len(raw))
    open(dest, "wb").write(out)

    # 3. index it
    rc = subprocess.run([sys.executable, os.path.join(HERE, "blockmap_add.py"),
                         dreg, dname] + ["%08X" % m["hash"] for m in minted] + ["%08X" % new],
                        capture_output=True, text=True)
    if rc.returncode != 0:
        return restore("blockmap_add failed: %s" % (rc.stdout + rc.stderr).strip()[-300:])

    # 4. verify - against the file the GAME reads, the .smh, not just the .smb
    from build_weapon import smh_holds          # build_weapon imports this module
    live_all = {r["hash"]: r for r in RB.parse(open(dest, "rb").read())[1]}
    smh = open(bm, "rb").read()
    for h, want in [(m["hash"], m["desc"]) for m in minted] + [(new, clone_desc)]:
        live = live_all.get(h)
        if live is None or live["desc"] != want:
            return restore("the tgl record %08X is not the intended record after write" % h)
        # Every occurrence, not the first: the character's own entry contains
        # the spray hash, so a first-match check can land inside it.
        if not smh_holds(smh, h, want):
            return restore("the blockmap entry for %08X is not the record byte for byte" % h)
    ok, why = blockmap_consistent(dreg)
    if not ok:
        return restore("region %s blockmap not consistent after the write: %s" % (target, why))

    # 5. register - this is what puts the name in the spawn library
    note = ("Built by Character Studio %s. Stem %s; the hash IS game_hash of "
            "\\data\\prefs\\Characters\\%sPrefs.txt. " % (datetime.date.today().isoformat(), stem, stem))
    note += ("%d field edit(s): %s." % (len(changes), ", ".join(n for n, o, x in changes))
             if changes else "Verbatim clone of the donor - no field edits.")
    if minted:
        note += " Custom spray(s) minted here: %s." % ", ".join(
            "%08X (%s) %s" % (m["hash"], fresh[m["hash"]][0], SP.describe(m["desc"])) for m in minted)
    try:
        if os.path.exists(CUSTOM):
            shutil.copy2(CUSTOM, csv_bk)
        append_custom_row({"Name": name, "Hash": "%08X" % new, "Region": target,
                           "ClonedFrom": "%08X %s" % (donor, donor_name or ""), "Notes": note})
    except Exception as e:
        return restore("could not register the name: %s" % e)
    print("   BUILT %08X into region %s with %d edit(s)" % (new, target, len(changes)))
    return True


def revert(new, target):
    dest, dreg, dname = PT.dest_for(target)
    bm = BA.bm_path(dreg)
    bk = ".buildbak_%08X" % new
    pairs = [(dest, dest + bk), (bm, bm + bk)]
    csv_bk = CUSTOM + ".buildbak_%08X_%s" % (new, target)
    if os.path.exists(csv_bk):
        pairs.append((CUSTOM, csv_bk))
    for live, back in pairs:
        if not os.path.exists(back):
            sys.exit("no %s - nothing to revert" % os.path.basename(back))
        # Refuse if a LATER build, edit or delete touched this file: restoring
        # would erase it.
        for other in backups_of(live):
            if other != back and os.path.getmtime(other) > os.path.getmtime(back):
                sys.exit("REFUSED: %s was changed again after %08X (%s) - revert that first"
                         % (os.path.basename(live), new, os.path.basename(other)))
    for live, back in pairs:
        shutil.copy2(back, live)
    print("REVERTED %08X from region %s (%d file(s) restored by copy)" % (new, target, len(pairs)))


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
        revert(int(a.revert, 16), a.to[0])
        return 0

    if not a.donor or not a.name or not a.to:
        sys.exit("need: <donor hash> --name <name> --to <region> [--to ...]")
    donor = int(a.donor, 16)
    name = a.name.strip()
    stem = stem_of(name)
    if not stem:
        print("REFUSED: '%s' has no letters or digits, so it cannot form a stem" % name)
        return 1
    new = stem_hash(stem)
    known = live_hashes()
    if new in known:
        print("REFUSED: %08X (from '%s') already exists in the install - choose another name" % (new, name))
        return 1
    for r in custom_rows():
        if (r.get("Name") or "").strip().lower() == name.lower():
            print("REFUSED: the name '%s' is already %s in the library" % (name, (r.get("Hash") or "").upper()))
            return 1

    edits, h2p = {}, {}
    if a.edits:
        try:
            edits = json.load(io.open(a.edits, encoding="utf-8-sig"))
        except (OSError, ValueError) as e:
            print("REFUSED: could not read edits file: %s" % e)
            return 1
        import resolve_assets as RA
        for q in RA.harvest():
            h2p.setdefault(game_hash(q), q)

    src = a.src or find_source(donor)
    if not src or donor not in idx_of(src):
        print("REFUSED: donor %08X is not in %s" % (donor, ("region_" + a.src) if a.src else "any numbered region"))
        return 1
    try:
        sprays = SP.prepare(edits, known, existing_desc)
    except SP.SprayError as e:
        print("REFUSED: %s" % e)
        return 1

    results = []
    for t in a.to:
        results.append(build_one(donor, src, t, name, stem, new, a.donor_name, edits, known, h2p, a.dry_run, sprays))
        if not results[-1]:
            break
    return 0 if results and all(results) else 1


if __name__ == "__main__":
    sys.exit(main() or 0)
