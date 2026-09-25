r"""Custom characters as RECIPES, not as shipped game files.

A custom character like jailbreak_blisterz is not new art. Every record he needs
is a CLONE of a vanilla one with a handful of bytes changed:

    FFFFDB52  character  <- 155A0299 outlawboss_boilz   121 bytes differ
    FFFFF30A  weapon     <- 5C65959D a Firearm            5 bytes differ
    E44268B9  companion  <- B03EBB79                      0 bytes - verbatim
    015D7FB0  boss job   <- 87C90D1E Boilz's own job     21 bytes differ

plus two records COPIED from elsewhere in the player's own install - Floyd's
rifle mesh out of region_06, and its texture, which region_01 already has.

So the whole character is 147 bytes of patch data and six instructions. The AT3
Official preset used to ship 10.26 MB of modified Oddworld bundles to deliver
that; it now ships the recipe and builds him on the player's machine.

    python character_recipe.py extract <recipe.json> --preset "<preset dir>"
    python character_recipe.py install <recipe.json>
    python character_recipe.py install <recipe.json> --verify-against "<preset dir>"

WHY THIS SHAPE. It generalises: anyone can clone a character, patch a few
fields, and share a JSON of well under a kilobyte. Nothing of the retail game
travels with it, and the launcher needs no knowledge of any particular
character - jailbreak_blisterz is simply the first recipe.

The source record is verified by LENGTH before a patch is applied. Byte offsets
into a clone are only meaningful against the record the recipe was built from;
if another mod got there first the install refuses rather than corrupting it.
"""
import argparse, io, json, os, shutil, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rebuild_bundle as RB
from spawn_prop import ROOT

BUNDLES = os.path.join(ROOT, "data", "bundles")
BAK = ".at3vanilla"


def bundle_path(rel):
    return os.path.join(BUNDLES, rel.replace("/", os.sep))


def read_records(path):
    d = open(path, "rb").read()
    hdr, recs, v, off = RB.parse(d)
    return d, hdr, recs, v, off


def blob(r):
    return r["desc"] + r["s2"] + r["s3"]


def runs_between(new, src):
    """Differing stretches, as (offset, bytes-of-new). Covers a longer new."""
    out = []
    n = max(len(new), len(src))
    i = 0
    while i < n:
        a = new[i] if i < len(new) else None
        b = src[i] if i < len(src) else None
        if a != b:
            j = i
            while j < n and ((new[j] if j < len(new) else None)
                             != (src[j] if j < len(src) else None)):
                j += 1
            out.append([i, new[i:j].hex()])
            i = j
        else:
            i += 1
    return out


def apply_runs(src, runs, total):
    buf = bytearray(src[:total])
    if len(buf) < total:
        buf += b"\x00" * (total - len(buf))
    for off, hx in runs:
        b = bytes.fromhex(hx)
        buf[off:off + len(b)] = b
    return bytes(buf)


# --------------------------------------------------------------------------
# extract
# --------------------------------------------------------------------------
def extract(recipe_path, preset_dir):
    """Diff a preset's modified bundles against vanilla and write the recipe."""
    spec = json.load(io.open(recipe_path, encoding="utf-8-sig"))
    for rec in spec["Records"]:
        tgt = bundle_path(rec["Bundle"])
        van = tgt + BAK
        if not os.path.exists(van):
            sys.exit("no %s - cannot tell what is vanilla" % os.path.basename(van))
        modified = os.path.join(preset_dir, os.path.basename(rec["Bundle"]))
        newmap = {r["hash"]: r for r in read_records(modified)[2]}
        vanmap = {r["hash"]: r for r in read_records(van)[2]}
        nh = int(rec["New"], 16)
        sh = int(rec["CloneOf"], 16)
        if nh not in newmap:
            sys.exit("%08X is not in %s" % (nh, modified))
        if sh not in vanmap:
            sys.exit("%08X is not in vanilla %s" % (sh, rec["Bundle"]))
        n, s = newmap[nh], vanmap[sh]
        nb, sb = blob(n), blob(s)
        rec["Kind"] = n["kind"]
        rec["Flags"] = n["flags"]
        rec["SrcLen"] = len(sb)
        rec["Lens"] = [len(n["desc"]), len(n["s2"]), len(n["s3"])]
        rec["Patch"] = runs_between(nb, sb)
    io.open(recipe_path, "w", encoding="utf-8").write(json.dumps(spec, indent=2))
    nb = sum(sum(len(bytes.fromhex(p[1])) for p in r["Patch"]) for r in spec["Records"])
    print("recipe written: %d record(s), %d byte(s) of patch data, %d copy instruction(s)"
          % (len(spec["Records"]), nb, len(spec.get("Copy", []))))


# --------------------------------------------------------------------------
# install
# --------------------------------------------------------------------------
def install(recipe_path, verify_dir=None, quiet=False):
    spec = json.load(io.open(recipe_path, encoding="utf-8-sig"))
    adds = {}          # target bundle -> [record dicts to append]

    # 1. records copied wholesale out of the player's own bundles
    for c in spec.get("Copy", []):
        src = bundle_path(c["From"])
        dst = bundle_path(c["To"])
        if not os.path.exists(src):
            sys.exit("missing source bundle %s" % c["From"])
        h = int(c["Hash"], 16)
        smap = {r["hash"]: r for r in read_records(src)[2]}
        if h not in smap:
            sys.exit("%08X not found in %s" % (h, c["From"]))
        if h in {r["hash"] for r in read_records(dst)[2]}:
            if not quiet:
                print("   %08X already in %s" % (h, os.path.basename(dst)))
            continue
        adds.setdefault(dst, []).append(dict(smap[h]))
        if not quiet:
            print("   copy %08X  %s -> %s"
                  % (h, os.path.basename(src), os.path.basename(dst)))

    # 2. records cloned from a vanilla one and patched
    for rec in spec["Records"]:
        tgt = bundle_path(rec["Bundle"])
        srcb = bundle_path(rec.get("SourceBundle", rec["Bundle"]))
        nh, sh = int(rec["New"], 16), int(rec["CloneOf"], 16)
        tmap = {r["hash"]: r for r in read_records(tgt)[2]}
        if nh in tmap:
            if not quiet:
                print("   %08X already present in %s" % (nh, os.path.basename(tgt)))
            continue
        smap = {r["hash"]: r for r in read_records(srcb)[2]}
        if sh not in smap:
            sys.exit("clone source %08X not found in %s" % (sh, rec.get("SourceBundle", rec["Bundle"])))
        s = smap[sh]
        sb = blob(s)
        # THE GUARD. Offsets only mean anything against the record this recipe
        # was built from. If something else already changed it, refuse.
        if len(sb) != rec["SrcLen"]:
            sys.exit("clone source %08X is %d bytes, recipe expects %d - refusing "
                     "to patch a record another mod has already changed"
                     % (sh, len(sb), rec["SrcLen"]))
        d1, d2, d3 = rec["Lens"]
        nb = apply_runs(sb, rec["Patch"], d1 + d2 + d3)
        adds.setdefault(tgt, []).append(dict(
            kind=rec["Kind"], hash=nh, flags=rec["Flags"],
            desc=nb[:d1], s2=nb[d1:d1 + d2], s3=nb[d1 + d2:], c2=0, c3=0))
        if not quiet:
            print("   clone %08X <- %08X into %s  (%d byte patch)"
                  % (nh, sh, os.path.basename(tgt),
                     sum(len(bytes.fromhex(p[1])) for p in rec["Patch"])))

    if not adds:
        print("nothing to do - already installed")
        return 0

    # 3. rebuild each touched bundle once
    for path, newrecs in adds.items():
        if not os.path.exists(path + BAK):
            shutil.copy2(path, path + BAK)
        d, hdr, recs, v, off = read_records(path)
        out, nv = RB.build(hdr, recs + newrecs, v, off, len(d))
        open(path, "wb").write(out)
        if not quiet:
            print("   %s: %d -> %d records, %d -> %d bytes"
                  % (os.path.basename(path), len(recs), len(recs) + len(newrecs),
                     len(d), len(out)))

    if verify_dir:
        ok = verify(spec, verify_dir)
        return 0 if ok else 1
    return 0


def verify(spec, ref_dir):
    """Every record the reference bundles hold must now be present and equal."""
    bad = 0
    seen = set()
    for rec in spec["Records"]:
        seen.add(rec["Bundle"])
    for c in spec.get("Copy", []):
        seen.add(c["To"])
    for rel in sorted(seen):
        ref = os.path.join(ref_dir, os.path.basename(rel))
        if not os.path.exists(ref):
            print("   (no reference copy of %s - skipped)" % os.path.basename(rel))
            continue
        live = {r["hash"]: blob(r) for r in read_records(bundle_path(rel))[2]}
        want = {r["hash"]: blob(r) for r in read_records(ref)[2]}
        missing = [h for h in want if h not in live]
        differ = [h for h in want if h in live and live[h] != want[h]]
        print("   verify %-26s %d record(s): %d missing, %d differing"
              % (os.path.basename(rel), len(want), len(missing), len(differ)))
        for h in missing[:5]:
            print("        MISSING %08X" % h)
        for h in differ[:5]:
            print("        DIFFERS %08X" % h)
        bad += len(missing) + len(differ)
    print("   verification: %s" % ("PASS" if bad == 0 else "%d problem(s)" % bad))
    return bad == 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["extract", "install"])
    ap.add_argument("recipe")
    ap.add_argument("--preset", help="extract: folder holding the modified bundles")
    ap.add_argument("--verify-against", dest="verify", help="install: compare against these bundles")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    if a.action == "extract":
        if not a.preset:
            sys.exit("extract needs --preset")
        extract(a.recipe, a.preset)
        return 0
    return install(a.recipe, a.verify, a.quiet)


if __name__ == "__main__":
    sys.exit(main() or 0)
