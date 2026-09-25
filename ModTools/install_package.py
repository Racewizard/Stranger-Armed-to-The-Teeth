r"""Install a killerclakker_package into a bundle - the inverse of export_clakker.

The package was built with a PATH-AWARE closure, so it carries the records a
dword walk cannot see: the animation config and every clip it names. Installing
it is therefore just "append what is missing and update the blockmap" - no
re-porting from other regions and no chance of the silently-absent-config bug.

    python install_package.py utility
    python install_package.py 02 --dry-run
"""
import argparse, json, os, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rebuild_bundle as RB

ROOT = os.path.dirname(HERE)
PKG = os.path.join(HERE, "killerclakker_package")
BAK = ".pkgbak"


def dest_for(region):
    if region == "utility":
        return (os.path.join(ROOT, "data", "bundles", "utility", "empty", "empty_tag.smb"),
                "utility", "empty_tag.smb")
    n = "lm_level_%s_tgl.smb" % region
    return os.path.join(ROOT, "data", "bundles", "region_" + region, "lm_level_" + region, n), region, n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("region")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    man = json.load(open(os.path.join(PKG, "manifest.json"), encoding="utf-8"))
    dest, dreg, dname = dest_for(a.region)
    raw = open(dest, "rb").read()
    hdr, recs, v, off = RB.parse(raw)
    if RB.build(hdr, recs, v, off, len(raw))[0] != raw:
        print("REFUSED: %s does not round-trip byte-identically" % dname)
        return
    # REPLACE a record whose content differs; do not skip it. Skipping is what
    # left the debug room with the VANILLA swing clip - same hash, but its
    # damage event is "footstep" instead of "fire", so the clakker swung and
    # dealt nothing. A hash match is not a content match.
    have = {r["hash"]: r for r in recs}
    add, repl = [], {}
    for m in man["records"]:
        h = int(m["hash"], 16)
        if h in have:
            b = open(os.path.join(PKG, m["file"]), "rb").read()
            # compare ALL THREE sections: the swing clip's descriptor is only
            # 113 bytes and its damage event lives in s2/s3, so a desc-only
            # comparison called the vanilla and edited clips identical
            cur = have[h]["desc"] + have[h]["s2"] + have[h]["s3"]
            if cur != b:
                repl[h] = {"hash": h, "kind": m["kind"], "flags": m["flags"],
                           "desc": b[:m["desc"]],
                           "s2": b[m["desc"]:m["desc"] + m["s2"]],
                           "s3": b[m["desc"] + m["s2"]:]}
            continue
        b = open(os.path.join(PKG, m["file"]), "rb").read()
        add.append({"hash": h, "kind": m["kind"], "flags": m["flags"],
                    "desc": b[:m["desc"]],
                    "s2": b[m["desc"]:m["desc"] + m["s2"]],
                    "s3": b[m["desc"] + m["s2"]:]})
    tot = sum(len(r["desc"]) + len(r["s2"]) + len(r["s3"]) for r in add)
    print("%s: %d of %d package records missing, %d B to add"
          % (dname, len(add), len(man["records"]), tot))
    if (not add and not repl) or a.dry_run:
        if a.dry_run:
            print("   (dry run - nothing written)")
        return
    if not os.path.exists(dest + BAK):
        shutil.copy2(dest, dest + BAK)
    recs = [repl.get(r["hash"], r) for r in recs]
    if repl:
        print("   replaced %d record(s) whose content differed: %s"
              % (len(repl), " ".join("%08X" % h for h in repl)))
    out, _ = RB.build(hdr, recs + add, v, off, len(raw))
    open(dest, "wb").write(out)
    rc = subprocess.run([sys.executable, os.path.join(HERE, "blockmap_add.py"), dreg, dname]
                        + ["%08X" % r["hash"] for r in add], capture_output=True, text=True)
    if rc.returncode != 0:
        sys.stdout.write((rc.stdout + rc.stderr)[-600:])
        shutil.copy2(dest + BAK, dest)
        print("   blockmap update FAILED - restored")
        return
    print("   written and indexed")


if __name__ == "__main__":
    main()
