"""Rebuild a bundle from its records, recomputing every cursor exactly.

In-place patching kept producing subtly wrong bundles. A record's data length
in sections 2 and 3 is NOT stored anywhere - it is implied by the NEXT record's
cursor. So writing a smaller slice into a larger slot leaves the loader reading
the slot's full width: the new mesh followed by leftover bytes of the old one.
That is exactly what "holding something strange and broken" looks like.

The same applies to the descriptor: padding a short descriptor out to the old
record size leaves trailing zeros inside the record.

Rebuilding sidesteps all of it. Extract every record as
(kind, hash, flags, descriptor, sec2 slice, sec3 slice), substitute the one
being replaced, then lay the whole file out again with cursors recomputed from
the actual slice lengths. Nothing is implied by leftover state.

Self-test: rebuilding with no substitution must reproduce a byte-identical
file. If it does not, the layout model is wrong and nothing else should be
trusted.

    python rebuild_bundle.py 06 npc_14.smb --check
    python rebuild_bundle.py 06 npc_14.smb --replace A036CC27 \
        --from-bundle zonebundle_74.smb --from 1E3C8910
"""
import argparse, os, shutil, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bundlefmt as BF
import char_defaults as CD

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BAK = ".rbbak"


def find_bundle(region, name):
    base = os.path.join(ROOT, "data", "bundles", f"region_{region}")
    for dp, _, fns in os.walk(base):
        if name in fns:
            return os.path.join(dp, name)
    sys.exit(f"{name} not found in region_{region}")


def parse(d):
    """(header_bytes, [record dicts], desc_values, desc_off)."""
    off, is_smh, v = BF.read_desc(d)
    hdr_end = off + 32 + 4          # descriptor block then the trailing magic
    recs = []
    pos = hdr_end
    while pos < v[1]:
        if d[pos:pos + 4] != BF.MAGIC:
            sys.exit(f"no record magic at {pos}")
        kind = struct.unpack_from("<I", d, pos + 4)[0]
        h, c2, c3, size, flags = struct.unpack_from("<5I", d, pos + 8)
        payload = d[pos + 28:pos + 8 + 20 + size]
        recs.append(dict(kind=kind, hash=h, c2=c2, c3=c3, flags=flags,
                         desc=payload))
        pos = pos + 8 + 20 + size
    # slices come from the cursors of the following record
    b2, b3 = v[0], v[0] + v[2]
    for i, r in enumerate(recs):
        n2 = recs[i + 1]["c2"] if i + 1 < len(recs) else v[4]
        n3 = recs[i + 1]["c3"] if i + 1 < len(recs) else v[5]
        r["s2"] = d[b2 + r["c2"]:b2 + n2]
        r["s3"] = d[b3 + r["c3"]:b3 + n3]
    return d[:hdr_end], recs, v, off


def build(header, recs, v, off, orig_len):
    """Lay the file out again, recomputing cursors from real slice lengths."""
    sec1 = bytearray(header)
    c2 = c3 = 0
    body2, body3 = bytearray(), bytearray()
    for r in recs:
        sec1 += BF.MAGIC + struct.pack("<I", r["kind"])
        sec1 += struct.pack("<5I", r["hash"], c2, c3, len(r["desc"]), r["flags"])
        sec1 += r["desc"]
        body2 += r["s2"]
        body3 += r["s3"]
        c2 += len(r["s2"])
        c3 += len(r["s3"])
    used1, used2, used3 = len(sec1), len(body2), len(body3)

    size1, size2, size3 = v[0], v[2], v[3]
    while used1 > size1:
        size1 += BF.SECT_ALIGN
    while used2 > size2:
        size2 += BF.SECT_ALIGN
    while used3 > size3:
        size3 += BF.SECT_ALIGN

    out = bytearray(sec1) + b"\x00" * (size1 - used1)
    out += body2 + b"\x00" * (size2 - used2)
    out += body3 + b"\x00" * (size3 - used3)

    nv = list(v)
    nv[0], nv[1] = size1, used1
    nv[2], nv[3] = size2, size3
    nv[4], nv[5] = used2, used3
    nv[6] = len(recs)
    BF.write_desc(out, off, nv)
    if nv[0] + nv[2] + nv[3] != len(out):
        sys.exit(f"section sum {nv[0]+nv[2]+nv[3]} != file {len(out)}")
    return bytes(out), nv


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("region")
    ap.add_argument("bundle")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--replace")
    ap.add_argument("--add")
    ap.add_argument("--at-end", action="store_true")
    ap.add_argument("--from-bundle")
    ap.add_argument("--from-region",
                    help="source region if different, e.g. importing a region_06 prop")
    ap.add_argument("--from", dest="src")
    ap.add_argument("--revert", action="store_true")
    a = ap.parse_args()

    p = find_bundle(a.region, a.bundle)
    if a.revert:
        if os.path.exists(p + BAK):
            shutil.copy2(p + BAK, p)
            print(f"reverted {a.bundle}")
        else:
            print("no backup")
        return

    d = open(p, "rb").read()
    header, recs, v, off = parse(d)
    print(f"{a.bundle}: {len(recs)} records, file {len(d)}B")
    print(f"   sec1 {v[1]}/{v[0]}  sec2 {v[4]}/{v[2]}  sec3 {v[5]}/{v[3]}")

    if a.check:
        out, nv = build(header, recs, v, off, len(d))
        same = out == d
        print(f"\nno-op rebuild: {'BYTE-IDENTICAL' if same else 'DIFFERS'}")
        if not same:
            print(f"   size {len(out)} vs {len(d)}")
            diffs = [i for i in range(min(len(out), len(d))) if out[i] != d[i]]
            print(f"   {len(diffs)} differing bytes; first at "
                  f"{diffs[0] if diffs else '-'}")
            print(f"   cursors/sizes: {nv[:7]} vs {v[:7]}")
        return

    if a.add:
        # Pull a record in from another bundle. A mesh's texture records are
        # referenced by hash and must be resident in a bundle that loads with
        # the character - gun_01's colormap lives in a zone bundle, so the
        # material never resolved and the mesh drew nothing.
        srcp = find_bundle(a.from_region or a.region, a.from_bundle)
        _sh, srecs, _sv, _so = parse(open(srcp, "rb").read())
        want = int(a.add, 16)
        src = next((r for r in srecs if r["hash"] == want), None)
        if src is None:
            sys.exit(f"{a.add} not found in {a.from_bundle}")
        if any(r["hash"] == want for r in recs):
            sys.exit(f"{a.add} already present in {a.bundle}")
        # Appending leaves every existing record's cursors untouched, which
        # matters because the blockmap stores those cursors per bundle and
        # would otherwise all need rewriting. Hash order is not strict -
        # zonebundle_74 has descents of its own.
        pos = len(recs) if a.at_end else len([r for r in recs if r["hash"] < want])
        recs.insert(pos, src)
        print(f"\nadding {want:08X} from {a.from_bundle} at index {pos} "
              f"(desc {len(src['desc'])}B, sec2 {len(src['s2'])}B, "
              f"sec3 {len(src['s3'])}B)")
        if not os.path.exists(p + BAK):
            shutil.copy2(p, p + BAK)
        out, nv = build(header, recs, v, off, len(d))
        open(p, "wb").write(out)
        print(f"   wrote {len(out)}B  sec1 {nv[1]}/{nv[0]}  "
              f"sec2 {nv[4]}/{nv[2]}  sec3 {nv[5]}/{nv[3]}  records {nv[6]}")
        return

    tgt = int(a.replace, 16)
    srcp = find_bundle(a.region, a.from_bundle)
    _sh, srecs, _sv, _so = parse(open(srcp, "rb").read())
    src = next((r for r in srecs if r["hash"] == int(a.src, 16)), None)
    if src is None:
        sys.exit(f"source {a.src} not found in {a.from_bundle}")
    hit = next((r for r in recs if r["hash"] == tgt), None)
    if hit is None:
        sys.exit(f"target {a.replace} not in {a.bundle}")
    print(f"\nreplacing {tgt:08X} "
          f"(desc {len(hit['desc'])}B, sec2 {len(hit['s2'])}B, sec3 {len(hit['s3'])}B)")
    print(f"     with {src['hash']:08X} "
          f"(desc {len(src['desc'])}B, sec2 {len(src['s2'])}B, sec3 {len(src['s3'])}B)")
    hit["desc"], hit["s2"], hit["s3"] = src["desc"], src["s2"], src["s3"]

    if not os.path.exists(p + BAK):
        shutil.copy2(p, p + BAK)
    out, nv = build(header, recs, v, off, len(d))
    open(p, "wb").write(out)
    print(f"   wrote {len(out)}B  sec1 {nv[1]}/{nv[0]}  "
          f"sec2 {nv[4]}/{nv[2]}  sec3 {nv[5]}/{nv[3]}")


if __name__ == "__main__":
    main()
