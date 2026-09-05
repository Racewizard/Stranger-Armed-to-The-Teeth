"""Add records to a bundle's group in the region blockmap, keeping it coherent.

The blockmap .smh is a chain of PER-BUNDLE groups. Each group is

    3A4B5C6D | version | pathlen | path | <8 dwords> | BEEF1234 | records...

and the 8 dwords are

    [0] sec1_size   [1] OFFSET OF THE NEXT GROUP HEADER   (absolute, verified:
                        every group's [1] equals the next header's offset, and
                        the last group's [1] equals the file's content field)
    [2] sec2_size   [3] sec3_size
    [4] sec2_size   [5] sec3_size   (repeated, NOT used-counts)
    [6] record count for THIS group
    [7] 2

A record present in two bundles gets one entry per group, each carrying that
bundle's own cursors - so the blockmap, not the bundle header, is what supplies
cursors at load time.

Inserting entries therefore means: fix this group's count and section figures,
and push field [1] of THIS group and EVERY LATER group forward by the inserted
size. Skipping that last step corrupts every group downstream, which shows up
as unrelated damage - garbled hats, broken collision - rather than a missing
model.

    python blockmap_add.py 06 npc_14.smb 1E3C8910 E080E830
    python blockmap_add.py 06 --revert
"""
import argparse, os, shutil, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bundlefmt as BF
import char_defaults as CD
import rebuild_bundle as RB

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BAK = ".bmaddbak"
GROUP = 0x3A4B5C6D


def bm_path(region):
    return os.path.join(ROOT, "data", "bundles", f"region_{region}",
                        f"lm_level_{region}_blockmap.smh")


def groups(d):
    """[(header_off, desc_off, path, [8 dwords])] for every group."""
    out = []
    needle = struct.pack("<I", GROUP)
    i = 0
    while True:
        i = d.find(needle, i)
        if i < 0:
            break
        ln = struct.unpack_from("<I", d, i + 8)[0]
        if 0 < ln < 300 and i + 12 + ln + 36 <= len(d):
            doff = i + 12 + ln
            if struct.unpack_from("<I", d, doff + 32)[0] == 0xBEEF1234:
                out.append((i, doff, d[i + 12:i + 12 + ln].decode("ascii", "replace"),
                            list(struct.unpack_from("<8I", d, doff))))
        i += 4
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("region")
    ap.add_argument("bundle", nargs="?")
    ap.add_argument("hashes", nargs="*")
    ap.add_argument("--revert", action="store_true")
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args()
    bm = bm_path(a.region)

    if a.revert:
        if os.path.exists(bm + BAK):
            shutil.copy2(bm + BAK, bm)
            print("blockmap reverted")
        else:
            print("no backup")
        return

    d = bytearray(open(bm, "rb").read())
    gs = groups(bytes(d))
    gi = next((k for k, g in enumerate(gs) if g[2].endswith(a.bundle)), None)
    if gi is None:
        sys.exit(f"no group for {a.bundle}")
    hoff, doff, path, dv = gs[gi]
    print(f"{a.bundle}: group @{hoff}, ends {dv[1]}, {dv[6]} records")

    if a.status:
        return

    # the bundle as it stands now, for cursors and section figures
    src = RB.find_bundle(a.region, a.bundle)
    d0 = open(src, "rb").read()
    boff, _is, bv = BF.read_desc(d0)
    live = {}
    for s, _e in CD.records(d0):
        if s + 20 > len(d0):
            continue
        h, c2, c3, sz, fl = struct.unpack_from("<5I", d0, s)
        live[h] = (struct.unpack_from("<I", d0, s - 4)[0], c2, c3, sz, fl,
                   d0[s + 20:s + 20 + sz])

    tail = dv[1]                      # entries end exactly where the group does
    if not os.path.exists(bm + BAK):
        shutil.copy2(bm, bm + BAK)

    blob = bytearray()
    for hx in a.hashes:
        h = int(hx, 16)
        if h not in live:
            sys.exit(f"{hx} is not in {a.bundle}")
        kind, c2, c3, sz, fl, desc = live[h]
        blob += BF.MAGIC + struct.pack("<I", kind)
        blob += struct.pack("<5I", h, c2, c3, sz, fl) + desc
        print(f"   entry {h:08X}: size={sz} cur=({c2},{c3})")
    n = len(blob)

    d[tail:tail] = blob

    # this group: new counts and the bundle's real section figures
    dv[1] += n
    # [0] is sec1_size and section 2's base is derived from it - forgetting it
    # makes every record in the bundle read its geometry from the wrong offset,
    # which made the whole wolvark vanish once section 1 grew a block.
    dv[0] = bv[0]
    # [4]/[5] are NOT used-counts: every vanilla group has [4]==[2] and
    # [5]==[3], i.e. the blockmap records section SIZES twice and never tracks
    # how much of each section is occupied.
    dv[2], dv[3] = bv[2], bv[3]
    dv[4], dv[5] = bv[2], bv[3]
    dv[6] += len(a.hashes)
    struct.pack_into("<8I", d, doff, *dv)
    print(f"   group now ends {dv[1]}, {dv[6]} records, sec1 {dv[0]}, "
          f"sec2 {dv[4]}/{dv[2]}, sec3 {dv[5]}/{dv[3]}")

    # every LATER group's next-header offset shifts by the inserted size
    moved = 0
    for k in range(gi + 1, len(gs)):
        _h2, doff2, _p2, dv2 = gs[k]
        doff2 += n if doff2 >= tail else 0
        dv2[1] += n
        struct.pack_into("<8I", d, doff2, *dv2)
        moved += 1
    print(f"   {moved} later group(s) shifted by {n}B")

    content = struct.unpack_from("<I", d, 8)[0]
    struct.pack_into("<I", d, 8, content + n)
    term = struct.unpack_from("<I", d, content + n)[0]
    if term != 0xCAFED00D:
        sys.exit(f"terminator landed wrong: {term:08X}")
    d = bytearray(bytes(d).rstrip(b"\x00"))
    d += b"\x00" * ((-len(d)) % BF.BLOCK)
    open(bm, "wb").write(bytes(d))
    print(f"content {content} -> {content+n}; terminator OK; file {len(d)}B")


if __name__ == "__main__":
    main()
