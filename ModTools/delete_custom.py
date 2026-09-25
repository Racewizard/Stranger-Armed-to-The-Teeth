r"""Delete a custom character or weapon: its record, and its library entry.

The Character Library's Custom Hashes tab calls this. It is the inverse of
build_character.py / build_weapon.py, and it REFUSES rather than leave the game
pointing at something that is gone:

    a placed spawn     a spawn of it in the region's .lvl
    a queued spawn     a row for it in the Spawns Editor's spawns_<region>.csv,
                       which the next Apply Changes would place
    a reference        any other record in the region whose descriptor holds the
                       hash - a character carrying the weapon, m_onGibSpawnNPC ...

WHAT IT REMOVES, for every region CustomHashes.csv lists for the hash
    the record         taken out of every bundle in the region that holds it;
                       each bundle is rebuilt with its cursors recomputed and the
                       region blockmap regenerated from its bundles (refused
                       unless the blockmap is consistent beforehand)
    its effect pref    for a weapon: the "Own effect pref XXXXXXXX" its Notes name,
                       unless something else in the region references it
    the entry          every CustomHashes.csv row for the hash, removed line by
                       line - every other byte of the file is kept
A row whose record is no longer in its region loses only the library entry.

It leaves the meshes, textures and other assets the build copied in: other
records may use them, and an unused asset costs nothing.

BACKUPS: <file>.deletebak_<HASH> for each bundle and blockmap touched, and
CustomHashes.csv.deletebak_<HASH>. --revert restores them by copy.

Removing a record is the mirror of appending one and is verified the same way -
absent from the bundle and the blockmap, check_groups consistent. It has not
been flown in game.

    python delete_custom.py 338A7633 --dry-run
    python delete_custom.py 338A7633
    python delete_custom.py --revert 338A7633
"""
import argparse, csv, glob, io, os, re, shutil, struct, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rebuild_bundle as RB
import blockmap_add as BA
import check_groups as CG
import build_character as BC
from ensure_asset import region_index, bundle_dir
from spawn_prop import walk
from spawn_char import spawn_records

ROOT = os.path.dirname(HERE)
PROPDIR = os.path.join(ROOT, "StrangerAT3", "PropPlacements")
CATALOGUE = os.path.join(ROOT, "StrangerAT3", "RegionData", "GlobalCatalogue.csv")


def display_names():
    out = {}
    for p in (CATALOGUE, BC.CUSTOM):
        if not os.path.exists(p):
            continue
        with io.open(p, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                try:
                    out[int(r.get("Hash") or "", 16)] = (r.get("Name") or "").strip()
                except ValueError:
                    pass
    return out


def placed_spawns(region, h):
    p = os.path.join(ROOT, "data", "bundles", "region_%s" % region, "lm_level_%s.lvl" % region)
    if not os.path.exists(p):
        return 0
    d = open(p, "rb").read()
    recs, end = walk(d)
    return sum(1 for s, ln, t, job in spawn_records(d, recs) if t == h)


def queued_spawns(region, h):
    p = os.path.join(PROPDIR, "spawns_%s.csv" % region)
    if not os.path.exists(p):
        return 0
    n = 0
    with io.open(p, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            try:
                if int((r.get("Hash") or "").strip() or "0", 16) == h:
                    n += 1
            except ValueError:
                pass
    return n


def own_effect(row):
    m = re.search(r"Own effect pref ([0-9A-Fa-f]{8})", row.get("Notes") or "")
    return int(m.group(1), 16) if m else None


def plan_region(h, region, extras, names):
    """(files {bundle path: set(hashes)}, refusals, present)."""
    idx = region_index(region)
    if h not in idx:
        return {}, [], False
    refusals = []
    n = placed_spawns(region, h)
    if n:
        refusals.append("%d spawn(s) of it are placed in region %s - remove them in the Spawns Editor and "
                        "apply first" % (n, region))
    q = queued_spawns(region, h)
    if q:
        refusals.append("%d queued Spawns Editor row(s) for region %s use it - remove them first" % (q, region))
    gone = {h} | {e for e in extras if e in idx}
    refs = {x: [] for x in gone}
    for x2, (fns, rec) in idx.items():
        if x2 in gone:
            continue
        for x in gone:
            if struct.pack("<I", x) in rec["desc"]:
                refs[x].append(x2)
    for x2 in refs[h]:
        refusals.append("%08X %s in region %s still points at it - a character carrying it, or another "
                        "reference" % (x2, names.get(x2) or "(unnamed record)", region))
    remove = {h} | {x for x in gone if x != h and not refs[x]}
    files = {}
    for x in remove:
        for fn in idx[x][0]:
            files.setdefault(os.path.join(bundle_dir(region), fn), set()).add(x)
    return files, refusals, True


def delete(h, dry):
    hx = "%08X" % h
    rows = [r for r in BC.custom_rows() if (r.get("Hash") or "").strip().upper() == hx]
    if not rows:
        print("REFUSED: %s is not in CustomHashes.csv - only custom characters and weapons can be deleted" % hx)
        return 1
    print("=== delete %s %s ===" % (hx, (rows[0].get("Name") or "").strip()))
    names = display_names()
    extras = [e for e in (own_effect(r) for r in rows) if e]
    plans, refusals = {}, []
    for reg in dict.fromkeys((r.get("Region") or "").strip() for r in rows):
        if reg not in BC.NUMBERED:
            print("   region %s is not a shipped region - only its library entry is removed" % (reg or "(blank)"))
            continue
        files, ref, present = plan_region(h, reg, extras, names)
        refusals += ref
        if not present:
            print("   region %s: %s is not in its bundles any more - only the library entry is removed" % (reg, hx))
            continue
        plans[reg] = files
        for p, hs in sorted(files.items()):
            print("   region %-3s remove %s from %s" % (reg, " ".join("%08X" % x for x in sorted(hs)),
                                                      os.path.basename(p)))
    if refusals:
        for s in refusals:
            print("   REFUSED: %s" % s)
        return 1
    print("   library  %d CustomHashes.csv row(s)" % len(rows))
    if dry:
        print("   (dry run - nothing written)")
        return 0
    for reg in plans:
        ok, why = BC.blockmap_consistent(reg)
        if not ok:
            print("   REFUSED: region %s blockmap is not consistent BEFORE the write: %s" % (reg, why))
            return 1

    bk = ".deletebak_%s" % hx
    touched = []

    def restore(reason):
        print("   FAILED: %s" % reason)
        for f in touched:
            shutil.copy2(f + bk, f)
        print("   restored %d file(s) from %s - nothing was left behind" % (len(touched), bk))
        return 1

    for reg, files in plans.items():
        bm = BA.bm_path(reg)
        for f in list(files) + [bm]:
            shutil.copy2(f, f + bk)
            touched.append(f)
        for p, hs in files.items():
            raw = open(p, "rb").read()
            hdr, recs, v, off = RB.parse(raw)
            if RB.build(hdr, recs, v, off, len(raw))[0] != raw:
                return restore("%s does not round-trip byte-identically" % os.path.basename(p))
            keep = [r for r in recs if r["hash"] not in hs]
            if len(keep) != len(recs) - len(hs):
                return restore("%s did not hold exactly the records planned" % os.path.basename(p))
            new, _ = RB.build(hdr, keep, v, off, len(raw))
            open(p, "wb").write(new)
        try:
            smh, used = CG.rebuild(reg)
        except RuntimeError as e:
            return restore("region %s blockmap could not be regenerated: %s" % (reg, e))
        open(bm, "wb").write(smh)
        gone = set().union(*files.values())
        for p, hs in files.items():
            if {r["hash"] for r in RB.parse(open(p, "rb").read())[1]} & hs:
                return restore("%s still holds a deleted record" % os.path.basename(p))
        d = open(bm, "rb").read()
        for goff, doff, path, vv in CG.groups(d):
            ents, end = CG.entries(d, doff, vv[6])
            if any(e[0] in gone for e in ents):
                return restore("region %s blockmap still indexes a deleted record" % reg)
        ok, why = BC.blockmap_consistent(reg)
        if not ok:
            return restore("region %s blockmap not consistent after the write: %s" % (reg, why))
        print("   DELETED %s from region %s" % (hx, reg))

    # the library entry - remove whole lines, keep every other byte
    try:
        shutil.copy2(BC.CUSTOM, BC.CUSTOM + bk)
        touched.append(BC.CUSTOM)
        lines = open(BC.CUSTOM, "rb").read().splitlines(keepends=True)
        keep, dropped = lines[:1], 0
        for ln in lines[1:]:
            try:
                row = next(csv.reader([ln.decode("utf-8")]))
            except (StopIteration, UnicodeDecodeError):
                row = []
            if len(row) > 1 and row[1].strip().upper() == hx:
                dropped += 1
                continue
            keep.append(ln)
        open(BC.CUSTOM, "wb").write(b"".join(keep))
    except Exception as e:
        return restore("could not update CustomHashes.csv: %s" % e)
    print("   REMOVED library entry %s (%d row(s))" % (hx, dropped))
    return 0


def revert(h):
    bk = ".deletebak_%08X" % h
    backs = glob.glob(os.path.join(glob.escape(ROOT), "data", "bundles", "**", "*" + bk), recursive=True)
    if os.path.exists(BC.CUSTOM + bk):
        backs.append(BC.CUSTOM + bk)
    if not backs:
        sys.exit("no %s backups - nothing to revert" % bk)
    for back in backs:
        live = back[:-len(bk)]
        for other in BC.backups_of(live):
            if other != back and os.path.getmtime(other) > os.path.getmtime(back):
                sys.exit("REFUSED: %s was changed again after this delete (%s) - revert that first"
                         % (os.path.basename(live), os.path.basename(other)))
    for back in backs:
        shutil.copy2(back, back[:-len(bk)])
    # Consumed: left behind, they would read as a LATER change and block the
    # revert of the build that came before this delete.
    for back in backs:
        os.remove(back)
    print("REVERTED delete of %08X (%d file(s) restored by copy)" % (h, len(backs)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("hash", nargs="?")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--revert")
    a = ap.parse_args()
    if a.revert:
        revert(int(a.revert, 16))
        return 0
    if not a.hash:
        sys.exit("need: <hash> [--dry-run]")
    return delete(int(a.hash, 16), a.dry_run)


if __name__ == "__main__":
    sys.exit(main() or 0)
