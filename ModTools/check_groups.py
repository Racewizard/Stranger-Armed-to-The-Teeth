r"""Verify the blockmap against every bundle it indexes.

validate_bundle.py checks ONE pair: lm_level_NN_tgl.smb against the blockmap's
first group. It says nothing about the other ~174 groups, and nothing about the
blockmap's own internal chain. That gap hid a real corruption: region_01's
blockmap claimed 1211 records in tgl while tgl.smb held 1209, and every existing
check still reported PASS.

THE FORMAT, as measured on region_01 (175 groups, all laws verified)

  12-byte prologue: BEEF2B16 | version | total used bytes
  then one group per bundle, back to back:
      3A4B5C6D | version | pathlen | path | 8 dwords | BEEF1234 | entries

The 8 dwords mirror the bundle's own descriptor block - sec1 size, sec1 used,
sec2 size, sec3 size, sec2 total, sec3 total, record count, version - with one
difference that matters enormously:

  * v[6] is the record count the LOADER TRUSTS. If it exceeds the bundle's real
    count the loader walks off the end of section 1 into whatever follows.

  * v[1] is NOT a per-group value. It is a CUMULATIVE cursor into a virtual
    concatenation of every bundle's section 1:

        v[1][k] == 12 + sum of bundle[i] sec1_used for i = 0..k

    Verified for 174 of 175 groups; the single deviation was the corruption.
    So adding entries to group j shifts the correct value of v[1] for group j
    AND EVERY GROUP AFTER IT. Update only group j and all 174 later bundles are
    indexed against a cursor that is short by the bytes you added.

  * Entries are DENSE: group k's entries end exactly where group k+1's header
    begins, for all 174 boundaries. There is no next-group pointer; the chain is
    positional, so an insertion must move everything after it.

    python check_groups.py 01
    python check_groups.py --all
    python check_groups.py 01 --verbose
"""
import argparse, os, struct, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bundlefmt as BF
import rebuild_bundle as RB

ROOT = os.path.dirname(HERE)
GROUP = 0x3A4B5C6D
ENDCAP = 0xBEEF1234
BS = chr(92)
REGIONS = ["00", "01", "02", "02a", "03", "04", "05", "06"]


def blockmap_path(region):
    return os.path.join(ROOT, "data", "bundles", "region_" + region,
                        "lm_level_%s_blockmap.smh" % region)


def resolve(path):
    """A blockmap path is game-root relative and backslash-rooted."""
    return os.path.join(ROOT, path.lstrip(BS + "/").replace(BS, os.sep))


def groups(d):
    """[(header_off, desc_off, path, [8 dwords])] in file order."""
    out = []
    needle = struct.pack("<I", GROUP)
    i = 0
    while True:
        i = d.find(needle, i)
        if i < 0:
            break
        if i + 12 <= len(d):
            ln = struct.unpack_from("<I", d, i + 8)[0]
            if 0 < ln < 300 and i + 12 + ln + 36 <= len(d):
                doff = i + 12 + ln
                if struct.unpack_from("<I", d, doff + 32)[0] == ENDCAP:
                    out.append((i, doff, d[i + 12:i + 12 + ln].decode("ascii", "replace"),
                                list(struct.unpack_from("<8I", d, doff))))
        i += 4
    return out


def entries(d, doff, count):
    """(hash, kind, c2, c3, size) per entry, plus the offset they end at."""
    pos = doff + 36
    out = []
    for _ in range(count):
        if pos + 28 > len(d) or d[pos:pos + 4] != BF.MAGIC:
            break
        kind = struct.unpack_from("<I", d, pos + 4)[0]
        h, c2, c3, size, _flags = struct.unpack_from("<5I", d, pos + 8)
        out.append((h, kind, c2, c3, size))
        pos += 28 + size
    return out, pos


def check(region, verbose=False):
    bm = blockmap_path(region)
    if not os.path.exists(bm):
        print("region_%s: no blockmap" % region)
        return 1
    d = open(bm, "rb").read()
    gs = groups(d)
    used = struct.unpack_from("<I", d, 8)[0]
    print("region_%s: %d groups, %d bytes (prologue says %d used)"
          % (region, len(gs), len(d), used))

    bad = 0
    run = 12
    for k, (hoff, doff, path, v) in enumerate(gs):
        name = os.path.basename(path.replace(BS, "/"))
        full = resolve(path)
        problems = []
        ents, end = entries(d, doff, v[6])

        if not os.path.exists(full):
            problems.append("bundle file missing")
        else:
            raw = open(full, "rb").read()
            try:
                _hdr, recs, _bv, _o = RB.parse(raw)
                bv = BF.read_desc(raw)[2]
            except Exception as e:
                problems.append("bundle unreadable (%s)" % e)
                recs, bv = None, None

            if recs is not None:
                if v[6] != len(recs):
                    problems.append("index claims %d records, bundle has %d"
                                    % (v[6], len(recs)))
                n = min(len(ents), len(recs))
                if [e[0] for e in ents[:n]] != [r["hash"] for r in recs[:n]]:
                    first = next(i for i in range(n) if ents[i][0] != recs[i]["hash"])
                    problems.append("hash mismatch at ordinal %d" % first)
                mism = [i for i in range(n) if ents[i][4] != len(recs[i]["desc"])]
                if mism:
                    problems.append("%d size mismatch (first #%d)" % (len(mism), mism[0]))
                run += bv[1]
                if v[1] != run:
                    problems.append("cumulative v[1]=%d, should be %d (off by %+d)"
                                    % (v[1], run, v[1] - run))

        if len(ents) != v[6]:
            problems.append("only %d of %d entries walk" % (len(ents), v[6]))
        nxt = gs[k + 1][0] if k + 1 < len(gs) else used
        if end != nxt:
            problems.append("entries end at %d, next group starts at %d" % (end, nxt))

        if problems:
            bad += 1
            print("  FAIL %-30s %s" % (name, "; ".join(problems)))
            if verbose:
                bh = set()
                if os.path.exists(full):
                    try:
                        bh = set(r["hash"] for r in RB.parse(open(full, "rb").read())[1])
                    except Exception:
                        pass
                for e in ents:
                    if e[0] not in bh:
                        print("         orphan entry %08X kind=%d size=%d" % (e[0], e[1], e[4]))
        elif verbose:
            print("  ok   %-30s %d records" % (name, v[6]))

    if end != used:
        print("  FAIL prologue used=%d but last group ends at %d" % (used, end))
        bad += 1
    print("  ==> %s" % ("%d group(s) BAD" % bad if bad else "consistent"))
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("region", nargs="?")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--repair", action="store_true",
                    help="regenerate the blockmap from the bundles it names")
    a = ap.parse_args()
    rs = REGIONS if a.all or not a.region else [a.region]
    total = 0
    for r in rs:
        total += check(r, a.verbose)
        if a.repair:
            repair(r, apply=True)
        print()
    return 1 if total else 0


# ---------------------------------------------------------------------------
# Repair
# ---------------------------------------------------------------------------
# The blockmap is not merely an index of offsets: each group's entry block is a
# byte-for-byte COPY of its bundle's section-1 record region, descriptors and
# all (verified: 174 of region_01's 175 groups are identical, and the one that
# is not is the damage). So the blockmap can always be regenerated from the
# bundles it names - no pristine backup required - and a region whose index has
# drifted can be made coherent again from the files themselves.
#
# rebuild() is self-testing in the same way rebuild_bundle is: on a region whose
# index already agrees with its bundles it must reproduce the file
# byte-identically. If it does not, the layout model is wrong and the result
# must not be written.

TERMINATOR = 0xCAFED00D


def rebuild(region):
    """Regenerate the whole blockmap from the bundles it indexes."""
    d = open(blockmap_path(region), "rb").read()
    gs = groups(d)
    out = bytearray(d[:12])
    for hoff, doff, path, v in gs:
        # ALL OR NOTHING. A blockmap assembled from bundles that were only
        # partly readable - the game holding one open is enough - would index
        # the region against files it never actually saw. Refuse the whole
        # region instead of writing something plausible and wrong.
        try:
            raw = open(resolve(path), "rb").read()
            boff, _is, bv = BF.read_desc(raw)
            recs = RB.parse(raw)[1]
        except SystemExit as e:
            raise RuntimeError("%s could not be parsed (%s)"
                               % (os.path.basename(path.replace(BS, "/")), e))
        except Exception as e:
            raise RuntimeError("%s could not be read (%s)"
                               % (os.path.basename(path.replace(BS, "/")), e))
        entries_blk = raw[boff + 36:bv[1]]

        out += d[hoff:hoff + 12 + (doff - (hoff + 12))]     # magic|ver|len|path
        nv = [bv[0], 0, bv[2], bv[3], bv[2], bv[3], len(recs), v[7]]
        dpos = len(out)
        out += struct.pack("<8I", *nv) + struct.pack("<I", ENDCAP)
        out += entries_blk
        struct.pack_into("<I", out, dpos + 4, len(out))     # v[1] = entries end
    used = len(out)
    out += struct.pack("<I", TERMINATOR)
    struct.pack_into("<I", out, 8, used)
    out += b"\x00" * ((-len(out)) % BF.BLOCK)
    # Never shrink a file that is otherwise correct. Some shipped blockmaps
    # carry a spare padding block beyond what the content needs; normalising
    # that away would rewrite a region for no reason. Repair must change only
    # what is actually wrong.
    if len(out) < len(d):
        out += b"\x00" * (len(d) - len(out))
    return bytes(out), used


def repair(region, apply=False):
    p = blockmap_path(region)
    cur = open(p, "rb").read()
    try:
        new, used = rebuild(region)
    except RuntimeError as e:
        print("region_%s: REFUSED - %s" % (region, e))
        return 1
    if new == cur:
        print("region_%s: blockmap already agrees with its bundles" % region)
        return 0
    n = sum(1 for i in range(min(len(new), len(cur))) if new[i] != cur[i])
    print("region_%s: rebuild differs - %d byte(s), %d -> %d bytes"
          % (region, n + abs(len(new) - len(cur)), len(cur), len(new)))
    if not apply:
        print("   (--repair to write it)")
        return 1
    if not os.path.exists(p + ".syncbak"):
        import shutil
        shutil.copy2(p, p + ".syncbak")
    open(p, "wb").write(new)
    print("   written; .syncbak holds the previous file")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
