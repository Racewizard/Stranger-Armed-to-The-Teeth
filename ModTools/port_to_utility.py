r"""Copy a retail record (plus what it needs to render) into the debug room.

`ensure_asset.py` solves the same problem but is scoped to ONE region: it
indexes `region_NN/lm_level_NN/*.smb` and writes into that region's tgl. The
debug room lives at `utility/empty/empty_tag.smb` with its own blockmap, so
bringing region_02's spikes or region_03's barge in there needs a source region
and a destination that ensure_asset cannot name.

Everything else is deliberately identical to ensure_asset, because those rules
were paid for in failed launches:

  * take the record's reference closure, not just the record;
  * carry every non-kind-0 record from the source bundle - the lighting and
    texture data a mesh depends on is not named by any dword in its descriptor;
  * prefer a source bundle that HAS a kind-3 lightmap, or the import renders
    impossibly bright;
  * refuse to write unless the destination round-trips byte-identically first;
  * append only, then fix the blockmap through blockmap_add.py.

    python port_to_utility.py 03 EE55DBAC --dry-run
    python port_to_utility.py 03 EE55DBAC
    python port_to_utility.py --revert
"""
import argparse, os, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rebuild_bundle as RB
from ensure_asset import region_index, closure

ROOT = os.path.dirname(HERE)
DEST = os.path.join(ROOT, "data", "bundles", "utility", "empty", "empty_tag.smb")


def dest_for(region):
    """utility by default; --to <region> sends it to that region's tgl instead."""
    if region in (None, "utility"):
        return DEST, "utility", "empty_tag.smb"
    if region == "emptygulch":
        # REFUSED, not routed. emptygulch's bundles are byte copies of region_01
        # that the engine never reads: its blockmap group paths name region_01,
        # and the game follows them. Writing here edits dead files and grows a
        # blockmap that now describes a bundle it does not point at - the region
        # crashed on load on 2026-09-08 and again on 2026-09-12 from exactly
        # this. A character that must appear in emptygulch has to be made
        # resident in region_01, whose bundles emptygulch actually loads.
        sys.exit("REFUSED: emptygulch's bundles are never loaded - its blockmap "
                 "points at region_01. Port into 01 instead.")
    name = "lm_level_%s_tgl.smb" % region
    return (os.path.join(ROOT, "data", "bundles", "region_" + region,
                         "lm_level_" + region, name), region, name)
BAK = ".portbak"


def has_k3(region, fn):
    d = os.path.join(ROOT, "data", "bundles", "region_" + region, "lm_level_" + region)
    try:
        return any(r["kind"] == 3 for r in RB.parse(open(os.path.join(d, fn), "rb").read())[1])
    except Exception:
        return False


def port(region, keys, dry=False, lean=False, to=None):
    """`lean` copies the reference closure only - mesh plus its textures.

    The "carry every non-kind-0 record" rule exists because an imported PROP
    renders impossibly bright without its source bundle's lighting records. An
    ATTACHMENT is lit as part of the character wearing it, not as a placement,
    which is why the helmet and hammer already in empty_tag.smb render correctly
    with no lighting data of their own. Use lean for attachments; leave it off
    for anything that becomes a placement in the world.
    """
    idx = region_index(region)
    missing = [k for k in keys if k not in idx]
    if missing:
        print("   not in region_%s: %s" % (region, " ".join("%08X" % k for k in missing)))
        return False

    dest, dreg, dname = dest_for(to)
    raw = open(dest, "rb").read()
    hdr, recs, v, off = RB.parse(raw)
    probe, _ = RB.build(hdr, recs, v, off, len(raw))
    if probe != raw:
        print("   REFUSED: %s does not round-trip byte-identically" % dname)
        return False
    have = set(r["hash"] for r in recs)

    want, src_of = [], {}
    for key in keys:
        for h in closure(key, idx):
            if h not in want:
                want.append(h)
        holders = list(idx[key][0])
        src = next((b for b in holders if has_k3(region, b)), holders[0])
        src_of[key] = (src, has_k3(region, src))
        if lean:
            continue
        d = os.path.join(ROOT, "data", "bundles", "region_" + region, "lm_level_" + region)
        for r in RB.parse(open(os.path.join(d, src), "rb").read())[1]:
            if r["kind"] != 0 and r["hash"] not in want:
                want.append(r["hash"])
                idx.setdefault(r["hash"], ([src], r))

    add = [idx[h][1] for h in want if h not in have]
    for key in keys:
        src, k3 = src_of[key]
        note = "" if (k3 or lean) else "   (NO kind-3 - a PLACEMENT would render bright)"
        print("   %08X from %s%s" % (key, src, note))
    tot = sum(len(r["desc"]) + len(r["s2"]) + len(r["s3"]) for r in add)
    kinds = {}
    for r in add:
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
    print("   %d record(s), %d B, kinds %s" % (len(add), tot,
          " ".join("%d:%d" % (k, n) for k, n in sorted(kinds.items()))))
    if not add:
        print("   nothing to do - already resident")
        return False
    if dry:
        print("   (dry run - nothing written)")
        return True

    if not os.path.exists(dest + BAK):
        shutil.copy2(dest, dest + BAK)
    out, _ = RB.build(hdr, recs + add, v, off, len(raw))
    open(dest, "wb").write(out)

    args = [sys.executable, os.path.join(HERE, "blockmap_add.py"), dreg, dname]
    args += ["%08X" % r["hash"] for r in add]
    rc = subprocess.run(args, capture_output=True, text=True)
    if rc.returncode != 0:
        sys.stdout.write(rc.stdout[-900:] + rc.stderr[-900:])
        # Restore the file we actually wrote. This said DEST, the utility
        # bundle, which with --to meant the real destination was left half
        # edited and an untouched utility bundle got clobbered instead.
        print("   blockmap update FAILED - restoring %s" % dname)
        shutil.copy2(dest + BAK, dest)
        return False
    print("   written and indexed")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("region", nargs="?")
    ap.add_argument("keys", nargs="*")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--to", help="destination region id; default utility")
    ap.add_argument("--lean", action="store_true",
                    help="closure only - correct for attachments, not placements")
    ap.add_argument("--revert", action="store_true")
    a = ap.parse_args()
    if a.revert:
        if os.path.exists(DEST + BAK):
            shutil.copy2(DEST + BAK, DEST)
            print("empty_tag.smb restored from %s" % BAK)
        else:
            print("no %s to restore" % BAK)
        return
    port(a.region, [int(k, 16) for k in a.keys], a.dry_run, a.lean, a.to)


if __name__ == "__main__":
    main()
