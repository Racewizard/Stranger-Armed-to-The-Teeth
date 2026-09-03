r"""Make one asset resident in one zone, on demand.

THE IDEA (much better than bulk consolidation)

A prop only renders where its geometry is loaded. The brute-force answer was to
copy EVERY zone-bundle record into the region's `normal:` bundle so everything
is resident everywhere - but that crashes regions 02, 03 and 04 past some limit
nobody has identified, and it costs 65 MB of always-resident memory per region
to make a handful of props placeable.

Instead: when a placement lands in a zone that cannot load its geometry, copy
just THAT record into a bundle THAT zone already loads. One record, one bundle,
only for props actually used. No bulk edit, so no crash limit to hit.

CHOOSING THE TARGET BUNDLE

`zonedep` in the blockmap lists which bundles each zone depends on. The runtime
never parses those lines - the string is absent from stranger.exe - but they
describe accurately what the level builder packed where, which is why the reach
model built from them matched reality for 271 props with zero contradictions.

Among the bundles a zone loads, this picks the one the FEWEST other zones share.
Region_02 zone 5 loads 29 bundles and zonebundle_99.smb belongs to that zone
alone, so an edit there cannot affect anything else.

SAFETY

Appending is only safe while a bundle round-trips byte-identically through
rebuild_bundle - that is what guarantees existing cursors do not move out from
under the blockmap index. It is checked before every write and the copy is
abandoned if it ever stops holding.

    python ensure_asset.py 02 24AEBFC4 --zone 5
    python ensure_asset.py 02 --status
    python ensure_asset.py 02 --revert
"""
import argparse, csv, os, shutil, struct, subprocess, sys

_os_exists = os.path.exists

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rebuild_bundle as RB
from place_props import zone_deps

ROOT = os.path.dirname(HERE)
BAK = ".ensurebak"
SKIP = (".knockbak", ".bak", ".at3vanilla", ".injbak", ".attbak", ".rbbak",
        ".presetbak", ".assetbak", ".consolbak", ".ensurebak", ".stage", ".bmaddbak")


def bundle_dir(region):
    return os.path.join(ROOT, "data", "bundles", "region_" + region,
                        "lm_level_" + region)


def normal_name(region):
    return "lm_level_%s_tgl.smb" % region


def ledger_path(region):
    return os.path.join(ROOT, "StrangerAT3", "RegionData", "ensured_%s.csv" % region)


def read_ledger(region):
    p = ledger_path(region)
    out = []
    if os.path.exists(p):
        with open(p, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                out.append((r["Key"], r["Zone"], r["Bundle"]))
    return out


def write_ledger(region, rows):
    p = ledger_path(region)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Key", "Zone", "Bundle"])
        for r in rows:
            w.writerow(r)


def region_index(region):
    """hash -> (bundle, record) for every record in the region."""
    d = bundle_dir(region)
    idx = {}
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".smb") or any(fn.endswith(x) for x in SKIP):
            continue
        try:
            recs = RB.parse(open(os.path.join(d, fn), "rb").read())[1]
        except Exception:
            continue
        for r in recs:
            if r["hash"] in idx:
                idx[r["hash"]][0].append(fn)
            else:
                idx[r["hash"]] = ([fn], r)
    return idx


def closure(key, idx):
    """`key` plus every record it references, transitively.

    Copying the mesh alone is not enough: the geometry record names its
    textures and material by hash, and those are separate records living in
    the same bundle. Copy only the mesh and it draws PURE WHITE - which is
    exactly what regions 00, 02 and 04 showed - or, if a reference dangles,
    takes the game down, which is what region_05 did.

    References are found by scanning the descriptor for dwords that match a
    record hash in this region. A stray dword could match by chance, but the
    candidate set is only a few thousand hashes out of 2^32, and copying one
    record too many is harmless where missing one is not.
    """
    out, todo = [], [key]
    seen = set()
    while todo:
        h = todo.pop()
        if h in seen or h not in idx:
            continue
        seen.add(h)
        _fns, rec = idx[h]
        out.append(h)
        desc = rec["desc"]
        for off in range(0, len(desc) - 3):
            v = struct.unpack_from("<I", desc, off)[0]
            if v in idx and v not in seen:
                todo.append(v)
    return out


def bundles_holding(region, key):
    """Every bundle that holds this record, and where it can be read from."""
    d = bundle_dir(region)
    out = []
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".smb") or any(fn.endswith(x) for x in SKIP):
            continue
        try:
            recs = RB.parse(open(os.path.join(d, fn), "rb").read())[1]
        except Exception:
            continue
        if any(r["hash"] == key for r in recs):
            out.append(fn)
    return out


def target_bundle(region, zone, holding):
    """The bundle to copy into: one this zone loads, shared with fewest zones.

    Returns (name, None) if a copy is needed, or (None, reason) if the asset is
    already resident for this zone.
    """
    zones, deps = zone_deps(region)
    if normal_name(region) in holding:
        return None, "already in the normal bundle - resident everywhere"
    if zone >= len(deps):
        return None, "zone %d is outside this region's %d zones" % (zone, len(deps))
    loaded = [zones[i] for i in deps[zone] if i < len(zones)]
    for h in holding:
        if h in loaded:
            return None, "already in %s, which zone %d loads" % (h, zone)
    if not loaded:
        return None, "zone %d loads no bundles" % zone
    share = {}
    for n in loaded:
        idx = zones.index(n)
        share[n] = sum(1 for d in deps if idx in d)
    best = min(share, key=lambda n: (share[n], n))
    return best, None


def ensure(region, key, zone, quiet=False, into=None):
    """Make `key` AND everything it references renderable in `zone`."""
    idx = region_index(region)
    if key not in idx:
        if not quiet:
            print("   %08X is not a record in any bundle of region_%s" % (key, region))
        return False

    zones, deps = zone_deps(region)
    if zone >= len(deps):
        print("   zone %d is outside region_%s" % (zone, region))
        return False
    loaded = set(zones[i] for i in deps[zone] if i < len(zones))
    loaded.add(normal_name(region))          # never zone-gated

    want = closure(key, idx)

    # CARRY THE SOURCE BUNDLE'S kind-3/9/0xA RECORDS. THIS IS THE LIGHTING.
    #
    # The reference closure is not enough. For the savanna tree it resolves to
    # exactly ONE record - the mesh - because the tree's textures and lighting
    # data are not named by any dword in its descriptor. Copy that alone and you
    # get an unlit mesh, which is precisely what happened when this block was
    # removed: tgl gained two bare kind-0 records and both objects rendered
    # without lighting.
    #
    # Measured across three runs, and BOTH conditions are required:
    #
    #     destination   carried 3/9/0xA   result
    #     tgl           yes               LIT
    #     tgl           no                unlit
    #     zone bundle   yes               unlit
    #
    # This block was deleted once on a shape argument - carrying a kind-3 into
    # zonebundle_87 gave it two, a form only one vanilla bundle in the region
    # has. That reasoning holds for a ZONE BUNDLE destination and was wrongly
    # applied to tgl, which ships with no kind-3 at all, so adding them creates
    # no such conflict. Do not remove it again without testing the tgl path.
    # PREFER A SOURCE BUNDLE THAT HAS A kind-3 LIGHTMAP.
    #
    # An import lights if and only if its source bundle contains a kind-3
    # record - measured 7 for 7 across every region: the four imports that
    # carried one rendered lit, the three that did not rendered impossibly
    # bright. Only 26 of region_01's 124 zone bundles have a kind-3 at all, so
    # a record present in several bundles can easily be read from one with no
    # lighting data to bring.
    #
    # When the same record lives in more than one bundle, take the one that has
    # a lightmap. Costs nothing when there is only one choice.
    def _has_k3(fn):
        try:
            return any(r["kind"] == 3 for r in RB.parse(
                open(os.path.join(bundle_dir(region), fn), "rb").read())[1])
        except Exception:
            return False

    holders = list(idx[key][0])
    src_bundle = next((b for b in holders if _has_k3(b)), holders[0])
    try:
        for r in RB.parse(open(os.path.join(bundle_dir(region), src_bundle),
                               "rb").read())[1]:
            # EVERYTHING THAT IS NOT ANOTHER OBJECT'S MESH.
            #
            # Carrying only kinds 3/9/0xA lit the savanna tree and left the
            # moolah barrel dark. That was luck: the tree's home bundle holds 8
            # records, so 3/9/0xA was nearly all of it, while the barrel's holds
            # 87 and the same filter took 14 - leaving 23 kind-1 textures and 15
            # kind-6 records behind. kind-6 does not appear in the tree's bundle
            # at all, which is why the narrow filter never showed the gap.
            #
            # kind-0 is excluded because those are OTHER objects' meshes and
            # copying them would drag in the whole bundle's geometry. Everything
            # else is shared or per-bundle data the mesh may depend on.
            if r["kind"] != 0 and r["hash"] not in want:
                want.append(r["hash"])
                idx.setdefault(r["hash"], ([src_bundle], r))
    except Exception:
        pass

    # WHAT IS MISSING, relative to what this zone can already reach.
    if into:
        need = [h for h in want if into not in idx[h][0]]
    else:
        need = [h for h in want if not (set(idx[h][0]) & loaded)]
    if not need:
        if not quiet:
            print("   %08X and its dependencies are already resident in zone %d"
                  % (key, zone))
        return False

    # NATIVE FIRST, TGL ONLY AS THE FALLBACK.
    #
    # Two paths, decided by the check above:
    #
    #   native    the geometry already lives in a bundle this zone loads, so
    #             `need` is empty and we returned without touching a file. This
    #             is the good path - the object renders with its correct baked
    #             lighting and no bundle is modified at all. Four dumpsters were
    #             placed in the town this way with every bundle left vanilla and
    #             they lit correctly. 142 of region_01's objects are reachable
    #             from zone 2 this way.
    #
    #   imported  the geometry is not reachable from this zone. Copying into a
    #             zone bundle gets geometry and texture but NO lighting - the
    #             mesh renders impossibly bright - and nothing we tried fixed
    #             it: not the reference closure, not the source bundle's entire
    #             contents including its kind-3, not the per-placement tint
    #             (which only ever colours debris and drops).
    #
    #             tgl gives uniform fallback lighting instead. It is not
    #             location-correct - six savanna trees copied there all came out
    #             with the same bake - but it is a lit object rather than a
    #             glowing one.
    #
    # So tgl is used ONLY for objects placed outside the zones that can already
    # reach them. Its growth is proportional to actual out-of-zone use, not to
    # the size of the library, which is what made bulk consolidation untenable.
    tgt = into or normal_name(region)
    d = bundle_dir(region)
    path = os.path.join(d, tgt)
    raw = open(path, "rb").read()
    hdr, recs, v, off = RB.parse(raw)
    probe, _ = RB.build(hdr, recs, v, off, len(raw))
    if probe != raw:
        print("   REFUSED: %s does not round-trip byte-identically" % tgt)
        return False

    have = set(r["hash"] for r in recs)
    add = [idx[h][1] for h in need if h not in have]
    if not add:
        if not quiet:
            print("   %08X: everything needed is already in %s" % (key, tgt))
        return False

    if not os.path.exists(path + BAK):
        shutil.copy2(path, path + BAK)
    out, _nv = RB.build(hdr, recs + add, v, off, len(raw))
    with open(path, "wb") as f:
        f.write(out)

    args = [sys.executable, os.path.join(HERE, "blockmap_add.py"), region, tgt]
    args += ["%08X" % r["hash"] for r in add]
    rc = subprocess.run(args, capture_output=True, text=True)
    if rc.returncode != 0:
        sys.stdout.write(rc.stdout[-800:] + rc.stderr[-800:])
        print("   blockmap update FAILED - restoring %s" % tgt)
        shutil.copy2(path + BAK, path)
        return False

    rows = read_ledger(region)
    for r in add:
        rows.append(("%08X" % r["hash"], str(zone), tgt))
    write_ledger(region, rows)
    if not quiet:
        tot = sum(len(r["desc"]) + len(r["s2"]) + len(r["s3"]) for r in add)
        print("   %08X + deps -> %s for zone %d: %d record(s), %d B"
              % (key, tgt, zone, len(add), tot))
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("region")
    ap.add_argument("key", nargs="?")
    ap.add_argument("--zone", type=int)
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--revert", action="store_true")
    ap.add_argument("--into", help="force the destination bundle")
    ap.add_argument("--csv", help="ensure every placement in a props CSV")
    ap.add_argument("--from-level", dest="from_level", action="store_true",
                    help="ensure every placement the level gained over its .bak")
    a = ap.parse_args()

    if a.revert:
        d = bundle_dir(a.region)
        n = 0
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(BAK):
                continue
            tgt = os.path.join(d, fn[:-len(BAK)])
            shutil.copy2(os.path.join(d, fn), tgt)
            os.remove(os.path.join(d, fn))
            n += 1
        subprocess.run([sys.executable, os.path.join(HERE, "blockmap_add.py"),
                        a.region, "--revert"], capture_output=True)
        p = ledger_path(a.region)
        if os.path.exists(p):
            os.remove(p)
        print("restored %d bundle(s); all on-demand copies cleared" % n)
        return 0

    if a.from_level:
        # DERIVE THE WORK FROM THE LEVEL, NOT FROM THE CSV.
        #
        # The CSV is not a reliable carrier: the launcher's Prop Editor rewrites
        # props_NN.csv as `Prop,X,Y,Z,Yaw,Pitch,Roll` and DROPS the Zone column
        # every time it saves. Zone is the field that decides whether an object
        # is culled at all, so a CSV round-trip through the editor silently
        # discards it.
        #
        # The level, by contrast, already holds every placement with its zone
        # resolved - place_props wrote it there. Diffing against the pristine
        # .bak gives exactly the records this run added, with the zone the game
        # will actually use.
        import place_props as PP
        from spawn_prop import lvl_path, u32, walk, pos_of
        cur = open(lvl_path(a.region), "rb").read()
        bak = lvl_path(a.region) + ".bak"
        if not _os_exists(bak):
            print("no pristine level backup for region_%s" % a.region)
            return 1
        van = open(bak, "rb").read()
        base = set()
        for s2 in walk(van)[0]:
            q = pos_of(van, s2)
            if q:
                base.add((round(q[0], 2), round(q[1], 2), round(q[2], 2), u32(van, s2 + 104)))
        todo, done = [], 0
        for s2 in walk(cur)[0]:
            q = pos_of(cur, s2)
            if not q:
                continue
            k = u32(cur, s2 + 104)
            if (round(q[0], 2), round(q[1], 2), round(q[2], 2), k) in base:
                continue
            todo.append((k, u32(cur, s2 + 20)))
        # Report which path each placement took - native is the good one and
        # the user should be able to see how many got it.
        idx = region_index(a.region)
        zones_, deps_ = zone_deps(a.region)
        native = imported = failed = 0
        for k, z in todo:
            # TRUE native means a ZONE BUNDLE this zone loads already holds
            # the geometry. Counting tgl as native would relabel everything we
            # imported on a previous pass as "native (no edit)" the next time
            # Apply Changes runs, which reads as though nothing was ever copied.
            zb = set()
            if z < len(deps_):
                zb = set(zones_[i] for i in deps_[z] if i < len(zones_))
            holders = set(idx[k][0]) if k in idx else set()
            if holders & zb:
                native += 1
                continue
            if normal_name(a.region) in holders:
                imported += 1          # already in tgl from an earlier pass
                continue
            if ensure(a.region, k, z, quiet=True, into=a.into):
                imported += 1
            else:
                failed += 1
        bits = ["%d placement(s)" % len(todo),
                "%d native (no edit)" % native,
                "%d imported into tgl" % imported]
        if failed:
            bits.append("%d could not be resolved" % failed)
        print("region_%s: %s" % (a.region, ", ".join(bits)))
        return 0

    if a.csv:
        import csv as _csv
        rows = list(_csv.DictReader(open(a.csv, encoding="utf-8-sig")))
        done = 0
        for r in rows:
            k = (r.get("Prop") or "").strip()
            if not k:
                continue
            try:
                key = int(k, 16)
            except ValueError:
                continue          # a catalogue name, resolved by place_props
            z = (r.get("Zone") or "").strip()
            if not z:
                continue
            if ensure(a.region, key, int(z), quiet=True, into=a.into):
                done += 1
        print("ensured %d of %d placement(s) in region_%s" % (done, len(rows), a.region))
        return 0

    if a.status or not a.key:
        rows = read_ledger(a.region)
        print("region_%s: %d asset(s) made resident on demand" % (a.region, len(rows)))
        for k, z, b in rows:
            print("   %s -> zone %s via %s" % (k, z, b))
        return 0


    if a.zone is None:
        print("need --zone")
        return 1
    return 0 if ensure(a.region, int(a.key, 16), a.zone, into=a.into) else 1


if __name__ == "__main__":
    sys.exit(main() or 0)
