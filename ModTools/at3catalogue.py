r"""Regenerate GlobalCatalogue.csv and catalogue_<region>.csv from live files.

These fed the Character Studio panel AND `apply_spawns.py`'s safe_donor
faction check - and were a hand-built snapshot from 2026-08-31 that nothing
ever refreshed. It did not know about killer clakker, jailbreak_blisterz or
outlaw_artillery, all built after that date. For those three, `safe_donor`'s
`fac.get(want_type)` silently returned None, which is low-risk for a hostile
target (both donor factions work against one) but is exactly the failure mode
that already cost launches once - a friendly custom character with an unknown
faction can draw a hostile donor, the one combination proven to never appear.

Faction is not stored anywhere and is not literally a field - `m_species`
(absolute +12, confirmed) is. Hostility is a property of the SPECIES, tested
empirically per CHARACTER_DIALS.md, not of the character - five species, not
per-character data:

    outlaw, wolvark, slog   -> hostile
    native, townsfolk       -> not hostile

That table is the only hardcoded fact in this script. Everything else - name,
HP, which regions carry the hash, how many spawns reference it - is read from
the files every run.

    python at3catalogue.py --build
    python at3catalogue.py --check      report only, write nothing
    python at3catalogue.py --build --force   rebuild even when current

FRESHNESS. A full build costs ~13 s (at3names re-anchors every record), and
the launcher used to pay it on every start. --build now fingerprints its
inputs - every live .smb/.smh/.lvl under data/ (count, total size, newest
mtime) plus CustomHashes.csv and this script - and skips the build when the
fingerprint matches the last one written. Backups (a second dot after the
extension, e.g. .smb.buildbak_X) are not inputs.
"""
import argparse, csv, glob, io, json, os, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import char_anchor as CA
from gamehash import game_hash
from spawn_prop import walk, u32
from spawn_char import spawn_records
import at3names

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGIONDATA = os.path.join(ROOT, "StrangerAT3", "RegionData")
REGIONS = ["00", "01", "02", "02a", "03", "04", "05", "06"]
REGION_LABEL = {
    "00": "Tutorial", "01": "Gizzard Gulch", "02": "Buzzardton", "02a": "Buzzardton",
    "03": "Mongo Valley", "04": "Wolvark Docks", "05": "Last Legs", "06": "Sekto Springs Dam",
}
SPECIES = {game_hash("outlaw"): "outlaw", game_hash("wolvark"): "wolvark",
           game_hash("slog"): "slog", game_hash("native"): "native",
           game_hash("townsfolk"): "townsfolk"}
HOSTILE = {"outlaw", "wolvark", "slog"}


def region_regions_of(h, by_region_hashes):
    return [REGION_LABEL.get(r, r) for r in REGIONS if h in by_region_hashes.get(r, set())]


def spawn_counts():
    """hash -> total spawn count across every region's .lvl."""
    out = {}
    for r in REGIONS:
        p = os.path.join(ROOT, "data", "bundles", "region_%s" % r, "lm_level_%s.lvl" % r)
        if not os.path.exists(p):
            continue
        d = open(p, "rb").read()
        try:
            recs, end = walk(d)
        except Exception:
            continue
        for s, ln, t, job in spawn_records(d, recs):
            out[t] = out.get(t, 0) + 1
    return out


def region_hash_sets():
    out = {}
    for r in REGIONS:
        d = os.path.join(ROOT, "data", "bundles", "region_%s" % r, "lm_level_%s" % r)
        s = set()
        for p in glob.glob(os.path.join(d, "*.smb")):
            if os.path.basename(p).count(".") > 1:
                continue
            try:
                import rebuild_bundle as RB
                for rec in RB.parse(open(p, "rb").read())[1]:
                    s.add(rec["hash"])
            except (Exception, SystemExit):
                pass
        out[r] = s
    return out


def build(quiet=False):
    names, how, rs, weap, by = at3names.build()
    spawns = spawn_counts()
    byregion = region_hash_sets()

    rows = []
    for h, (nm, C, A, b) in rs.items():
        if not nm:
            continue
        if A is None:
            # "stub" shape - a MotionAnimConfig with no audioName block. Per
            # char_anchor.py these are live ammo and its effects (ArmadilloWeapon,
            # BeeGunWeapon, FuzzleAttack, steef, ...), not placeable characters -
            # they have no health, no attachments, nothing safe_donor or a spawn
            # UI needs. Including them was pure noise: 15 stub names, several
            # sharing a cfg name, drowned every real duplicate in "(N bytes,
            # weapon 00000000)" clutter.
            continue
        sp = struct.unpack_from("<I", b, 12)[0] if len(b) >= 16 else 0
        species = SPECIES.get(sp, "")
        hp = ""
        if A is not None and A + 20 <= len(b):
            hp = struct.unpack_from("<f", b, A + 16)[0]
            hp = int(hp) if hp == int(hp) else round(hp, 1)
        regs = region_regions_of(h, byregion)
        rows.append({
            "Hash": "%08X" % h,
            "Name": names.get(h, nm),
            "HP": hp,
            "Faction": ("hostile" if species in HOSTILE else "friendly") if species else "",
            "Spawns": spawns.get(h, 0),
            "Regions": ", ".join(sorted(set(regs))),
            "_region_set": set(r for r in REGIONS if h in byregion.get(r, set())),
        })

    if quiet:
        return rows

    out = os.path.join(REGIONDATA, "GlobalCatalogue.csv")
    with io.open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Hash", "Name", "HP", "Faction", "Spawns", "Regions"])
        for r in sorted(rows, key=lambda x: x["Name"]):
            w.writerow([r["Hash"], r["Name"], r["HP"], r["Faction"], r["Spawns"], r["Regions"]])
    print("GlobalCatalogue.csv: %d character(s)" % len(rows))

    for reg in REGIONS:
        sub = [r for r in rows if reg in r["_region_set"]]
        if not sub:
            continue
        p = os.path.join(REGIONDATA, "catalogue_%s.csv" % reg)
        with io.open(p, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["Hash", "Name", "HP", "Faction", "Spawns", "Slots"])
            for r in sorted(sub, key=lambda x: x["Name"]):
                w.writerow([r["Hash"], r["Name"], r["HP"], r["Faction"],
                           r["Spawns"], r["Regions"]])
        print("catalogue_%s.csv: %d character(s)" % (reg, len(sub)))
    return rows


STATE = os.path.join(REGIONDATA, "catalogue_state.json")


def fingerprint():
    n, size, newest = 0, 0, 0
    for dp, dn, fn in os.walk(os.path.join(ROOT, "data")):
        for f in fn:
            parts = f.lower().split(".")
            if len(parts) != 2 or parts[1] not in ("smb", "smh", "lvl"):
                continue
            st = os.stat(os.path.join(dp, f))
            n += 1
            size += st.st_size
            newest = max(newest, st.st_mtime_ns)
    extra = []
    for q in (os.path.join(ROOT, "StrangerAT3", "CustomHashes.csv"), os.path.abspath(__file__)):
        extra.append(os.stat(q).st_mtime_ns if os.path.exists(q) else 0)
    return {"files": n, "bytes": size, "newest": newest, "extra": extra}


def is_current(fp):
    if not os.path.exists(os.path.join(REGIONDATA, "GlobalCatalogue.csv")):
        return False
    try:
        return json.load(open(STATE)) == fp
    except (OSError, ValueError):
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    fp = None
    if a.build and not a.check:
        fp = fingerprint()
        if not a.force and is_current(fp):
            print("catalogue current - no game file changed since the last build")
            return
    rows = build(quiet=a.check)
    if fp is not None:
        # Re-fingerprint AFTER: a file written during the build must invalidate.
        json.dump(fingerprint() if fingerprint() == fp else {}, open(STATE, "w"))
    if a.check:
        print("%d character(s) would be written" % len(rows))
        unclassified = [r for r in rows if not r["Faction"]]
        if unclassified:
            print("no species match (Faction blank): %s"
                  % ", ".join(r["Hash"] for r in unclassified[:10]))


if __name__ == "__main__":
    main()
