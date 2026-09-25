r"""Index the game's own files, so AT3 stops guessing what vanilla looks like.

THE PROBLEM THIS REPLACES. AT3 works by storing how the game differs from
vanilla - but it only has a vanilla reference for 4 of 1148 bundles (0.3%).
Two consequences, both of which have already cost real work:

  * presets store a FILE OFFSET (`RecOff`) for every field they patch. The
    moment a bundle is rebuilt, every record after the insertion point moves
    and the offset is wrong. `AT3 Official.json` still names RecOff 449935 for
    a record whose descriptor now starts at 231493 - that entry silently does
    nothing. The launcher re-checks the hash before writing, so it fails safe,
    but it also fails.
  * Apply Changes restores `.at3vanilla` backups without knowing what those
    bundles now contain. That is how jailbreak_blisterz lost his cloned boss
    job and his weapon geometry: they lived in npc_19 and npc_23, two of the
    only four files AT3 had a reference for.

THE FIX. Do not store offsets and do not guess. Scan the files and look
everything up at apply time. A full parse of all 1052 MB takes ~1.2 s warm and
~3 s cold, which is cheap enough to do on every save, preset load and apply -
so the index is never stale by construction.

    RecOff is the file offset of a record's HASH field, which is the record
    magic + 8. Descriptor bytes start 20 further on, so a preset's `Off` is
    descriptor offset + 20. Verified by reading known values back.

    python at3index.py --build             scan and cache
    python at3index.py --find C8F313D2     where does this record live
    python at3index.py --bundle lm_level_01_tgl.smb
    python at3index.py --baseline-capture  record what the install looks like now
    python at3index.py --modified          what differs from the baseline
"""
import argparse, glob, hashlib, json, os, struct, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rebuild_bundle as RB
import bundlefmt as BF

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "StrangerAT3", "index_cache.json")
BASELINE = os.path.join(ROOT, "StrangerAT3", "vanilla_baseline.json")
SKIP = (".at3vanilla", ".bak", ".syncbak", ".prewrite", ".charbak", ".prestrip",
        ".selfknockbak", ".dualwpnbak", ".artillerybak", ".bisectbak", ".arcbak")


def live_files():
    out = []
    for pat in ("data/bundles/*/*/*.smb", "data/global/*.smb"):
        for p in glob.glob(os.path.join(ROOT, pat.replace("/", os.sep))):
            base = os.path.basename(p)
            if base.endswith(".smb") and base.count(".") == 1:
                out.append(p)
    return sorted(out)


def digest(b):
    return hashlib.blake2b(b, digest_size=8).hexdigest()


def scan_bundle(path):
    """[(hash, kind, desclen, recoff, digest)] - recoff is the HASH field's file offset."""
    raw = open(path, "rb").read()
    try:
        hdr, recs, v, off = RB.parse(raw)
    except (Exception, SystemExit):
        return None
    out, pos = [], len(hdr)
    for r in recs:
        # locate this record's magic to get a real file offset
        key = BF.MAGIC + struct.pack("<II", r["kind"], r["hash"])
        i = raw.find(key, pos)
        if i < 0:
            i = raw.find(key)
        recoff = i + 8 if i >= 0 else -1
        if i >= 0:
            pos = i + 4
        out.append((r["hash"], r["kind"], len(r["desc"]), recoff,
                    digest(r["desc"] + (r["s2"] or b"") + (r["s3"] or b""))))
    return out


def build(quiet=False):
    files = live_files()
    cache = {}
    if os.path.exists(CACHE):
        try:
            cache = json.load(open(CACHE, encoding="utf-8"))
        except Exception:
            cache = {}
    old = cache.get("files", {})
    new, rescanned, reused = {}, 0, 0
    t0 = time.time()
    for p in files:
        rel = os.path.relpath(p, ROOT).replace(os.sep, "/")
        st = os.stat(p)
        key = "%d:%d" % (st.st_size, int(st.st_mtime))
        prev = old.get(rel)
        if prev and prev.get("key") == key:
            new[rel] = prev
            reused += 1
            continue
        recs = scan_bundle(p)
        if recs is None:
            continue
        new[rel] = {"key": key, "records": [[("%08X" % h), k, L, o, d] for h, k, L, o, d in recs]}
        rescanned += 1
    out = {"built": time.strftime("%Y-%m-%dT%H:%M:%S"), "files": new}
    json.dump(out, open(CACHE, "w", encoding="utf-8"))
    if not quiet:
        n = sum(len(v["records"]) for v in new.values())
        print("indexed %d bundles, %d records in %.2f s  (%d rescanned, %d cached)"
              % (len(new), n, time.time() - t0, rescanned, reused))
    return out


def load():
    if not os.path.exists(CACHE):
        return build(quiet=True)
    return json.load(open(CACHE, encoding="utf-8"))


def locate(idx, hexhash):
    hexhash = hexhash.upper()
    hits = []
    for rel, v in idx["files"].items():
        for h, k, L, o, d in v["records"]:
            if h == hexhash:
                hits.append((rel, k, L, o, d))
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--rebuild", action="store_true", help="ignore the cache")
    ap.add_argument("--find")
    ap.add_argument("--bundle")
    ap.add_argument("--baseline-capture", action="store_true")
    ap.add_argument("--modified", action="store_true")
    a = ap.parse_args()

    if a.rebuild and os.path.exists(CACHE):
        os.remove(CACHE)
    if a.build or a.rebuild:
        build()
        return
    idx = load()

    if a.find:
        hits = locate(idx, a.find)
        print("%s: %d copy(ies)" % (a.find.upper(), len(hits)))
        for rel, k, L, o, d in hits:
            print("   %-52s kind=%-2d len=%-6d RecOff=%-9d %s" % (rel, k, L, o, d))
        if hits:
            print("\n   preset Off = descriptor offset + 20 (RecOff points at the hash field)")
        return
    if a.bundle:
        for rel, v in idx["files"].items():
            if rel.endswith("/" + a.bundle):
                print("%s: %d records" % (rel, len(v["records"])))
                return
        print("no such bundle")
        return
    if a.baseline_capture:
        base = {}
        for rel, v in idx["files"].items():
            for h, k, L, o, d in v["records"]:
                base.setdefault(h, d)
        json.dump({"captured": time.strftime("%Y-%m-%dT%H:%M:%S"), "records": base},
                  open(BASELINE, "w", encoding="utf-8"))
        print("baseline captured: %d distinct record hashes -> %s"
              % (len(base), os.path.relpath(BASELINE, ROOT)))
        return
    if a.modified:
        if not os.path.exists(BASELINE):
            sys.exit("no baseline - run --baseline-capture on a clean install first")
        base = json.load(open(BASELINE, encoding="utf-8"))["records"]
        added, changed = [], []
        for rel, v in idx["files"].items():
            for h, k, L, o, d in v["records"]:
                if h not in base:
                    added.append((h, rel))
                elif base[h] != d:
                    changed.append((h, rel))
        print("vs baseline captured %s:" % json.load(open(BASELINE, encoding="utf-8"))["captured"])
        print("   records ADDED since:   %d" % len(added))
        for h, rel in added[:12]:
            print("      %s  %s" % (h, rel))
        print("   records CHANGED since: %d" % len(changed))
        for h, rel in changed[:12]:
            print("      %s  %s" % (h, rel))
        return
    print(__doc__.strip().split("\n\n")[0])


if __name__ == "__main__":
    main()
