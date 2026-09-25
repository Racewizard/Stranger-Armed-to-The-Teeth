"""Read a character's DEFAULT kit straight out of its own prefs record.

Many spawns set their attachments inline in the .lvl. Many do not, and fall
back to a default tied to their character hash - which is where boss weapons
live. Reading those needs the character's own record, bounded properly.

Proximity does NOT work: Floyd's hash sits 928 bytes before outlaw_shooter's
in region_01's tgl.smb, so a naive window attributes the shooter's rifle and
striped hat to Floyd. Records must be bounded by the container framing:

    4D FA A7 7E   record start magic
    <u32 kind>
    <record>      hash +0x00 ... size +0x0C ... class tag +0x14
    34 12 EF BE   record terminator

so a record runs from its magic to the next magic, and only attachment records
inside those bounds belong to that character.

    python char_defaults.py FF61B694 155A0299 FFFC00CB
"""
import os, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gamehash import game_hash
import resolve_assets as RA
from scan_attachments import scan

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAGIC = struct.pack("<I", 0x4DFAA77E)
BS = chr(92)
SKIP = (".knockbak", ".bak", ".at3bak", ".envbak", ".hatbak")


def records(d):
    """[(record_start, extent)] - record_start is where the hash sits."""
    starts = []
    i = 0
    while True:
        i = d.find(MAGIC, i)
        if i < 0:
            break
        starts.append(i + 8)
        i += 1
    out = []
    for j, s in enumerate(starts):
        end = (starts[j + 1] - 8) if j + 1 < len(starts) else len(d)
        out.append((s, end - s))
    return out


def bundles():
    for dp, _, fns in os.walk(os.path.join(ROOT, "data")):
        for fn in fns:
            if not fn.endswith((".smb", ".smh")) or fn.endswith(SKIP):
                continue
            p = os.path.join(dp, fn)
            try:
                yield p, open(p, "rb").read()
            except OSError:
                continue


def main():
    want = [int(a, 16) for a in sys.argv[1:]]
    if not want:
        sys.exit(__doc__)
    known = {game_hash(p): p for p in RA.harvest() if p.lower().endswith(".geo")}
    allpaths = {game_hash(p): p for p in RA.harvest()}

    def gn(h):
        v = known.get(h)
        return v.split(BS)[-1] if v else f"unknown_{h:08X}"

    found = {h: [] for h in want}
    for path, d in bundles():
        recs = records(d)
        if not recs:
            continue
        for s, ext in recs:
            if s + 4 > len(d):
                continue
            h = struct.unpack_from("<I", d, s)[0]
            if h in found:
                body = d[s:s + ext]
                found[h].append((os.path.relpath(path, ROOT), s, ext, body))

    for h in want:
        print(f"\n=== {h:08X}  {allpaths.get(h, '(path unknown)')} ===")
        hits = found[h]
        if not hits:
            print("   no record in any bundle starts with this hash")
            continue
        for rel, s, ext, body in hits:
            att = scan(body)
            print(f"   {rel}  offset {s}, extent {ext} bytes, "
                  f"{len(att)} attachment record(s)")
            for bone, gh, off in att:
                print(f"        {bone:<24} {gn(gh):<32} (+{off} in record)")
            # any other asset hashes referenced inside the record
            refs = set()
            for k in range(0, max(0, len(body) - 4)):
                v = struct.unpack_from("<I", body, k)[0]
                if v in allpaths and v != h:
                    refs.add(v)
            if refs:
                print(f"        -- other asset references ({len(refs)}) --")
                for v in sorted(refs):
                    print(f"           {v:08X}  {allpaths[v]}")


if __name__ == "__main__":
    main()
