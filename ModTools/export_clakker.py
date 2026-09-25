r"""Freeze the killer clakker to disk so a bundle revert cannot lose it.

Reverting region_01/region_02 through the AT3 launcher restores vanilla bundles,
which deletes the custom records living in them - the zero clakker, its weapon,
the shared anim config, the moolah spawner, the imported attachment meshes. The
debug room (utility) is a separate bundle and survives, but the region copies do
not.

This walks the reference closure from the three character records, writes every
record it finds as a raw file, and records where each one came from plus every
spawn placement in the .lvl chain. Restoring is then: append the records to the
target bundle, register them with blockmap_add.py, and re-place the spawns.

    python export_clakker.py                 -> ModTools/killerclakker_package/
"""
import json, os, struct, sys, glob, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rebuild_bundle as RB
from char_anchor import roster, anchor, cfg
from spawn_prop import lvl_path, walk, TINT, POS
from spawn_char import spawn_records

ROOT = os.path.dirname(HERE)
OUT = os.path.join(HERE, "killerclakker_package")
KC = {0xEDFB19EF: "zero", 0xE25E452F: "close", 0x5EC7002D: "far"}


def index():
    """hash -> (bundle, record), PREFERRING the utility copy.

    The same character hash exists in several bundles and the copies have
    DIVERGED: all the attachment work (clavicle spikes, both turret panels) was
    done in utility only, so the region_01/region_02 copies carry just the helmet
    and shovel. utility is the canonical version and is also the one a region
    revert cannot touch, so it wins.
    """
    idx = {}
    for p in sorted(glob.glob(os.path.join(ROOT, "data", "bundles", "**", "*.smb"), recursive=True)):
        try:
            recs = RB.parse(open(p, "rb").read())[1]
        except (Exception, SystemExit):
            continue
        rel = os.path.relpath(p, ROOT).replace("\\", "/")
        for r in recs:
            if r["hash"] not in idx or ("/utility/" in rel and "/utility/" not in idx[r["hash"]][0]):
                idx[r["hash"]] = (rel, r)
    return idx


def closure(seed, idx):
    """Every record reachable by a dword reference OR BY PATH STRING.

    A dword walk alone is NOT enough and silently loses the two most important
    records: a character names its animation config by PATH, and the config
    names its clips the same way. `game_hash(path)` is the record hash, so the
    reference is real but invisible to a scan for hash-shaped dwords. An export
    built on the dword walk produced a package that looked complete and could
    not actually rebuild the character.
    """
    import re
    from gamehash import game_hash
    PATH = re.compile(rb"[\x5c/][ -~]{6,200}?\.(?:txt|gr2|geo|tga|bmp)", re.I)
    seen, queue = set(), list(seed)
    while queue:
        h = queue.pop(0)
        if h in seen or h not in idx:
            continue
        seen.add(h)
        d = idx[h][1]["desc"]
        for o in range(0, len(d) - 4):
            v = struct.unpack_from("<I", d, o)[0]
            if v in idx and v not in seen:
                queue.append(v)
        for m in PATH.finditer(d):
            v = game_hash(m.group().decode("latin1"))
            if v in idx and v not in seen:
                queue.append(v)
    return seen


def main():
    idx = index()
    keep = closure(list(KC), idx)
    # a character's closure pulls in half the game through shared records;
    # keep only what is plausibly ours plus the small assets we imported
    ours = {h for h in keep if len(idx[h][1]["desc"]) + len(idx[h][1]["s2"]) + len(idx[h][1]["s3"]) < 400000}
    os.makedirs(OUT, exist_ok=True)
    man = {"records": [], "spawns": []}
    for h in sorted(ours):
        src, r = idx[h]
        name = "%08X.rec" % h
        with open(os.path.join(OUT, name), "wb") as f:
            f.write(r["desc"] + r["s2"] + r["s3"])
        man["records"].append({
            # flags is part of the record HEADER and must round-trip - without it
            # rebuild_bundle.build() raises KeyError and the package cannot be
            # reinstalled at all
            "hash": "%08X" % h, "kind": r["kind"], "flags": r["flags"],
            "file": name, "source_bundle": src,
            "desc": len(r["desc"]), "s2": len(r["s2"]), "s3": len(r["s3"]),
            "role": KC.get(h, ""),
        })
    for reg in ("01", "02", "utility"):
        p = lvl_path(reg) if reg != "utility" else os.path.join(ROOT, "data", "bundles", "utility", "empty.lvl")
        if not os.path.exists(p):
            continue
        d = open(p, "rb").read()
        recs, _ = walk(d)
        for off, ln, t, job in spawn_records(d, recs):
            if t not in KC:
                continue
            x, y, z = struct.unpack_from("<3f", d, off + POS)
            man["spawns"].append({
                "region": reg, "character": "%08X" % t, "role": KC[t],
                "pos": [round(x, 3), round(y, 3), round(z, 3)],
                "tint_bgra": d[off + TINT:off + TINT + 4].hex().upper(),
                "lvl": os.path.relpath(p, ROOT).replace("\\", "/"),
            })
    # note every bundle each character record appears in, and whether the copies
    # actually match - a mismatch means that bundle holds an older loadout
    man["divergence"] = []
    for p in sorted(glob.glob(os.path.join(ROOT, "data", "bundles", "**", "*.smb"), recursive=True)):
        try:
            recs = RB.parse(open(p, "rb").read())[1]
        except (Exception, SystemExit):
            continue
        rel = os.path.relpath(p, ROOT).replace("\\", "/")
        for r in recs:
            if r["hash"] in KC:
                man["divergence"].append({
                    "hash": "%08X" % r["hash"], "role": KC[r["hash"]], "bundle": rel,
                    "matches_canonical": r["desc"] == idx[r["hash"]][1]["desc"],
                })
    with open(os.path.join(OUT, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(man, f, indent=2)
    tot = sum(r["desc"] + r["s2"] + r["s3"] for r in man["records"])
    print("%d records (%d B) and %d spawns -> %s"
          % (len(man["records"]), tot, len(man["spawns"]), os.path.relpath(OUT, ROOT)))
    for r in man["records"]:
        if r["role"]:
            print("   %-8s %s kind=%d from %s" % (r["role"], r["hash"], r["kind"], r["source_bundle"]))


if __name__ == "__main__":
    main()
