"""Resolve asset hashes to file paths by harvesting every path in the bundles.

Weapon and hat references are stored as PATH HASHES, never as raw names, so a
byte search for a known hash finds nothing. But the `.smh` index files contain
every asset path as a literal string - harvest those, hash each one, and the
mapping falls out. This replaces guessing candidate filenames.

GOTCHA that cost a whole pass: inside a regex character class a lone backslash
escapes the next character, so `[\\/]` collapses to just `/`. Written that way
the harvest picked up only the forward-slash paths - 2301 instead of 13812 -
and every hash came back unresolved. The class needs TWO backslashes.

    python resolve_assets.py                 # summary of asset families
    python resolve_assets.py C8F313D2 ...    # resolve specific hashes
    python resolve_assets.py --like weapons  # list paths containing a word
"""
import os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gamehash import game_hash

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BSL = bytes([0x5C])
PAT = re.compile(b"[" + BSL + BSL + b"/]data[" + BSL + BSL + b"/][ -~]{4,140}")
EXTS = (".txt", ".geo", ".tga", ".bmp", ".smb", ".smh", ".lvl", ".swf", ".xwb", ".foo", ".gr2", ".dds")


def harvest():
    paths = set()
    for dp, _, fns in os.walk(os.path.join(ROOT, "data")):
        for fn in fns:
            if not fn.endswith((".smh", ".smb", ".lvl")) or fn.endswith((".knockbak", ".bak", ".at3bak", ".envbak")):
                continue
            try:
                d = open(os.path.join(dp, fn), "rb").read()
            except OSError:
                continue      # the running game holds locks on some bundles
            for m in PAT.finditer(d):
                s = m.group().decode("latin1")
                # The match runs on past the end of the stored string into
                # whatever follows (often script source), so cut at the first
                # known extension. Without this, a path and the same path plus
                # a trailing script fragment hash to different values and the
                # real one can be missed.
                cut = -1
                for ext in EXTS:
                    j = s.lower().find(ext)
                    if j >= 0 and (cut < 0 or j < cut):
                        cut = j + len(ext)
                if cut > 0:
                    s = s[:cut]
                if len(s) > 6:
                    paths.add(s)
    return paths


def build_map(paths):
    h = {}
    for p in paths:
        h.setdefault(game_hash(p), p)
    return h


def main():
    paths = harvest()
    H = build_map(paths)
    args = sys.argv[1:]

    if args and args[0] == "--like":
        needle = args[1].lower()
        hits = sorted(p for p in paths if needle in p.lower())
        for p in hits:
            print(f"  {game_hash(p):08X}  {p}")
        print(f"({len(hits)} of {len(paths)} paths)")
        return

    if args:
        print(f"{len(paths)} paths harvested\n")
        for a in args:
            v = int(a, 16)
            print(f"  {v:08X}  ->  {H.get(v, '*** unresolved ***')}")
        return

    print(f"{len(paths)} distinct asset paths harvested\n")
    fam = {}
    for p in paths:
        parts = p.replace("/", "\\").strip("\\").split("\\")
        key = "\\".join(parts[:3]) if len(parts) >= 3 else "\\".join(parts)
        fam[key] = fam.get(key, 0) + 1
    for k, n in sorted(fam.items(), key=lambda kv: -kv[1])[:28]:
        print(f"  {n:6}  {k}")


if __name__ == "__main__":
    main()
