r"""Carry AT3-built records inside a preset, and rebuild them on another install.

A preset used to hold only the Global Rules and Ammo tables; a character built
in the Character Creator, a weapon from the Weapon Creator, a custom spray or a
Save-in-place edit of a stock character existed only in the author's bundles.
Sharing the preset shared none of it, and the spawns pointing at those hashes
pointed at nothing on the recipient's machine.

    python preset_customs.py capture  <out.json>     what this install has built
    python preset_customs.py install  <preset.json>  rebuild it here
    python preset_customs.py install  <preset.json> --dry-run
    python preset_customs.py revert   <stamp>        undo one install

WHAT IS CAPTURED - no retail data, only differences (the recipe principle):

  clone   every AT3-minted record in a numbered region's tgl (CustomHashes.csv
          hashes and the hashes its Notes name, plus self-identifying custom
          sprays), stored as a byte patch against the most similar RETAIL
          record of the same type. The donor's length and CRC travel with it,
          so a recipient whose donor differs is refused, not corrupted.
  raw     the rare record no retail record resembles (patch over 60% of it) -
          stored whole.
  edit    a stock record changed in place (Save in the Character or Weapon
          Creator), as a patch against its FIRST .editbak_ copy - the value it
          had before AT3 touched it. Applied only where the recipient's record
          still matches that baseline.

Meshes, textures, animation configs and every other retail asset a custom
record points at are NOT captured. Install re-ports them from the recipient's
own install - the same closure walk the build tools use.

INSTALL SAFETY is build_character's: each touched region's tgl and blockmap are
backed up once per install (`.presetbak_<stamp>`), the blockmap is regenerated
and every written record verified in the .smh, and a region that fails any
check is restored from its backup.
"""
import argparse, csv, datetime, glob, io, json, os, re, shutil, struct, sys, zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rebuild_bundle as RB
import port_to_utility as PT
import blockmap_add as BA
import check_groups as CG
import build_character as BC
import char_model as CM
import weapon_fields as WF
import spray as SP
from ensure_asset import region_index
from gamehash import game_hash

ROOT = os.path.dirname(HERE)
NUMBERED = BC.NUMBERED
RAW_RATIO = 0.6


def crc(b):
    return "%08X" % (zlib.crc32(b) & 0xFFFFFFFF)


def blob(r):
    return r["desc"] + r["s2"] + r["s3"]


def runs_between(new, src):
    out, n, i = [], max(len(new), len(src)), 0
    while i < n:
        a = new[i] if i < len(new) else None
        b = src[i] if i < len(src) else None
        if a != b:
            j = i
            while j < n and ((new[j] if j < len(new) else None) != (src[j] if j < len(src) else None)):
                j += 1
            out.append([i, new[i:j].hex()])
            i = j
        else:
            i += 1
    return out


def patch_size(runs):
    return sum(len(h) // 2 for _o, h in runs)


def apply_runs(src, runs, total):
    buf = bytearray(src[:total])
    if len(buf) < total:
        buf += b"\x00" * (total - len(buf))
    for off, hx in runs:
        b = bytes.fromhex(hx)
        buf[off:off + len(b)] = b
    return bytes(buf[:total])


def tgl_records(region):
    dest, _r, _n = PT.dest_for(region)
    return RB.parse(open(dest, "rb").read())[1]


def custom_set():
    # CM.custom_hashes() drops every ClonedFrom hash - right for labelling
    # vanilla donors, wrong here: huge_clakker was cloned FROM the Killer
    # Clakker, which is itself custom. Every Hash-column entry is ours.
    out = set(CM.custom_hashes())
    for row in registry_rows():
        try:
            out.add(int(row.get("Hash") or "", 16))
        except ValueError:
            pass
    for r in NUMBERED:
        for rec in tgl_records(r):
            if rec["kind"] == 7 and len(rec["desc"]) == 43 and SP.hash_of(bytes(rec["desc"])) == rec["hash"]:
                out.add(rec["hash"])
    return out


def registry_rows():
    p = BC.CUSTOM
    if not os.path.exists(p):
        return []
    with io.open(p, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def first_editbak(dest, h):
    """The record `h` as it was before AT3's first in-place edit of it."""
    backs = sorted(glob.glob(glob.escape(dest) + ".editbak_%08X_*" % h))
    for b in backs:
        try:
            for r in RB.parse(open(b, "rb").read())[1]:
                if r["hash"] == h:
                    return r
        except Exception:
            continue
    return None


# --------------------------------------------------------------------------
# capture
# --------------------------------------------------------------------------
def apply_ops(src, ops):
    """Ops are [i1, i2, hex]: replace src[i1:i2] with the bytes, ascending."""
    out, pos = bytearray(), 0
    for i1, i2, hx in ops:
        out += src[pos:i1] + bytes.fromhex(hx)
        pos = i2
    return bytes(out + src[pos:])


def ops_between(new, src):
    import difflib
    sm = difflib.SequenceMatcher(None, src, new, autojunk=False)
    return [[i1, i2, new[j1:j2].hex()] for tag, i1, i2, j1, j2 in sm.get_opcodes() if tag != "equal"]


def ops_cost(ops):
    return sum(len(h) // 2 for _a, _b, h in ops) + 2 * len(ops)


def capture():
    customs = custom_set()
    reg = registry_rows()
    donor_hint = {}
    for row in reg:
        m = re.match(r"\s*([0-9A-Fa-f]{8})", row.get("ClonedFrom") or "")
        if m:
            donor_hint[int(row["Hash"], 16)] = int(m.group(1), 16)

    # Candidates by record type, across every numbered region.
    pool, mine = {}, {}
    for r in NUMBERED:
        for h, (_fns, rec) in BC.idx_of(r).items():
            key = (rec["kind"], bytes(rec["desc"][:8]))
            pool.setdefault(key, {}).setdefault(h, rec)

    def choose(h, rec, allow):
        """((cost, form, data), donor, donor bytes) or None. Positional patches
        against the 40 nearest candidates first - cheap; the insertion-aware
        diff only for the 5 nearest by length, and only if that failed."""
        b = blob(rec)
        limit = RAW_RATIO * max(1, len(b))
        cands = {dh: d for dh, d in pool.get((rec["kind"], bytes(rec["desc"][:8])), {}).items()
                 if dh != h and allow(dh)}
        near = sorted(cands, key=lambda dh: (dh != donor_hint.get(h), abs(len(blob(cands[dh])) - len(b))))
        best = None
        for dh in near[:40]:
            db = blob(cands[dh])
            if abs(len(db) - len(b)) > 512:
                continue
            runs = runs_between(b, db)
            sz = patch_size(runs)
            if best is None or sz < best[0][0]:
                best = ((sz, "Patch", runs), dh, db)
                if sz == 0:
                    return best
        if best and best[0][0] <= limit:
            return best
        if len(b) <= 16384:
            for dh in near[:5]:
                db = blob(cands[dh])
                if abs(len(db) - len(b)) > 512:
                    continue
                ops = ops_between(b, db)
                c = ops_cost(ops)
                if best is None or c < best[0][0]:
                    best = ((c, "Ops", ops), dh, db)
        return best

    entries, notes, donor_of = [], [], {}
    edits = []
    for r in NUMBERED:
        dest, _dr, _dn = PT.dest_for(r)
        for rec in tgl_records(r):
            h = rec["hash"]
            b = blob(rec)
            base = {"Region": r, "Hash": "%08X" % h, "Kind": rec["kind"], "Flags": rec["flags"],
                    "Lens": [len(rec["desc"]), len(rec["s2"]), len(rec["s3"])]}
            if h in customs:
                mine[h] = (rec, base)
            else:
                orig = first_editbak(dest, h)
                if orig is None or blob(orig) == b:
                    continue
                ob = blob(orig)
                edits.append(dict(base, Mode="edit", BaseLen=len(ob), BaseCrc=crc(ob),
                                  Patch=runs_between(b, ob)))

    # Pass 1: retail donors only. Pass 2: a record still too far from any
    # retail one may clone ANOTHER custom record (huge_clakker <- Killer
    # Clakker), provided that does not make a cycle.
    chosen = {}
    for h, (rec, base) in mine.items():
        chosen[h] = choose(h, rec, lambda dh: dh not in customs)

    def chain(h):
        seen = []
        while h in donor_of:
            h = donor_of[h]
            if h in seen:
                break
            seen.append(h)
        return seen

    for h, (rec, base) in mine.items():
        c = chosen[h]
        if c and c[0][0] <= RAW_RATIO * max(1, len(blob(rec))):
            continue
        c2 = choose(h, rec, lambda dh: dh in mine and h not in chain(dh))
        if c2 and (not c or c2[0][0] < c[0][0]):
            chosen[h] = c2
            donor_of[h] = c2[1]

    for h, (rec, base) in mine.items():
        b = blob(rec)
        c = chosen[h]
        if c and c[0][0] <= RAW_RATIO * max(1, len(b)):
            (_sz, form, data), dh, db = c
            e = dict(base, Mode="clone", CloneOf="%08X" % dh, SrcLen=len(db), SrcCrc=crc(db))
            e[form] = data
        else:
            e = dict(base, Mode="raw", Hex=b.hex())
            notes.append("%08X in region %s stored whole - no similar record" % (h, base["Region"]))
        e["Registry"] = [x for x in reg if (x.get("Hash") or "").upper() == "%08X" % h
                         and (x.get("Region") or "") == base["Region"]]
        entries.append(e)

    # Donors before the records cloned from them.
    depth = {}
    def dep(h):
        if h not in depth:
            depth[h] = 0
            depth[h] = (dep(donor_of[h]) + 1) if h in donor_of else 0
        return depth[h]
    entries.sort(key=lambda e: dep(int(e["Hash"], 16)))
    return {"Records": entries + edits, "Notes": notes}


# --------------------------------------------------------------------------
# install
# --------------------------------------------------------------------------
def build_bytes(e, find_rec):
    """(record dict or None, reason)."""
    d1, d2, d3 = e["Lens"]
    tot = d1 + d2 + d3
    if e["Mode"] == "raw":
        nb = bytes.fromhex(e["Hex"])
    else:
        src = find_rec(int(e["CloneOf"], 16))
        if src is None:
            return None, "donor %s is not in this install" % e["CloneOf"]
        sb = blob(src)
        if len(sb) != e["SrcLen"] or crc(sb) != e["SrcCrc"]:
            return None, "donor %s differs from the one this preset was made against" % e["CloneOf"]
        nb = apply_ops(sb, e["Ops"]) if "Ops" in e else apply_runs(sb, e["Patch"], tot)
        if len(nb) != tot:
            return None, "patch produced %d bytes, expected %d" % (len(nb), tot)
    return dict(kind=e["Kind"], hash=int(e["Hash"], 16), flags=e["Flags"],
                desc=nb[:d1], s2=nb[d1:d1 + d2], s3=nb[d1 + d2:tot], c2=0, c3=0), None


def refs_of(desc):
    out = set()
    for k in range(len(desc) - 3):
        out.add(struct.unpack_from("<I", desc, k)[0])
    out.update(game_hash(p) for p in WF.paths_in(desc))
    try:
        out.update(WF.composed(desc))
    except Exception:
        pass
    return out


def make_resident(region, hashes, global_h, where, dry):
    """Port whatever `hashes` reference that this region lacks, from its own
    install. Repeats until nothing new is missing (ported records have refs)."""
    ported = []
    for _pass in range(6):
        idx = region_index(region)
        missing = {}
        for h in hashes:
            for y in WF.needs(h, idx) if h in idx else [h]:
                if y not in idx:
                    continue
                for x in refs_of(idx[y][1]["desc"]):
                    if x in idx or x in global_h or x in ported:
                        continue
                    src = where.get(x)
                    if src and src != region:
                        missing.setdefault(src, set()).add(x)
        if not missing:
            return ported, None
        for src, xs in missing.items():
            xs = sorted(xs)
            if not dry:
                PT.port(src, xs, dry=False, lean=True, to=region)
            ported += xs
        if dry:
            return ported, None
    return ported, "dependencies still missing after 6 passes"


def install(path, dry):
    pre = json.load(io.open(path, encoding="utf-8-sig"))
    ents = (pre.get("Customs") or {}).get("Records") or []
    if not ents:
        print("no custom records in this preset")
        return 0
    stamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    where = {}
    for r in NUMBERED:
        for h in BC.idx_of(r):
            where.setdefault(h, r)
    global_h = BC.live_hashes("global")

    built = {}      # records built by this install, usable as donors

    def find_rec(h):
        if h in built:
            return built[h]
        r = where.get(h)
        return BC.idx_of(r)[h][1] if r else None

    by_region = {}
    for e in ents:
        by_region.setdefault(e["Region"], []).append(e)

    ok_all = True
    installed = {}
    for region, es in by_region.items():
        print("=== region %s ===" % region)
        if region not in NUMBERED:
            print("   REFUSED: %s is not a shipped region" % region)
            ok_all = False
            continue
        dest, dreg, dname = PT.dest_for(region)
        bm = BA.bm_path(dreg)
        raw = open(dest, "rb").read()
        hdr, recs, v, off = RB.parse(raw)
        if RB.build(hdr, recs, v, off, len(raw))[0] != raw:
            print("   REFUSED: %s does not round-trip byte-identically" % dname)
            ok_all = False
            continue
        ok, why = BC.blockmap_consistent(dreg)
        if not ok:
            print("   REFUSED: blockmap not consistent before install: %s" % why)
            ok_all = False
            continue
        pos = {r["hash"]: i for i, r in enumerate(recs)}
        out = list(recs)
        changed, touched = [], []
        for e in es:
            h = int(e["Hash"], 16)
            if e["Mode"] == "edit":
                if h not in pos:
                    print("   SKIP  %08X edit - the record is not in %s" % (h, dname))
                    continue
                cur = blob(out[pos[h]])
                d1, d2, d3 = e["Lens"]
                if len(cur) == e["BaseLen"] and crc(cur) == e["BaseCrc"]:
                    nb = apply_runs(cur, e["Patch"], d1 + d2 + d3)
                elif len(cur) == d1 + d2 + d3 and all(cur[o:o + len(bytes.fromhex(x))] == bytes.fromhex(x) for o, x in e["Patch"]):
                    print("   same  %08X edit already applied" % h)
                    continue
                else:
                    print("   SKIP  %08X edit - this install's record is not the one the preset edited" % h)
                    ok_all = False
                    continue
                r2 = dict(out[pos[h]], desc=nb[:d1], s2=nb[d1:d1 + d2], s3=nb[d1 + d2:])
                out[pos[h]] = r2
                changed.append(r2)
                print("   edit  %08X (%d byte patch)" % (h, patch_size(e["Patch"])))
                continue
            rec, why = build_bytes(e, find_rec)
            if rec is None:
                print("   FAILED %08X: %s" % (h, why))
                ok_all = False
                continue
            built[h] = rec
            if h in pos:
                if blob(out[pos[h]]) == blob(rec):
                    print("   same  %08X already installed" % h)
                    touched.append(h)
                    continue
                out[pos[h]] = rec
                print("   update %08X (differed from the preset's)" % h)
            else:
                pos[h] = len(out)
                out.append(rec)
                print("   add   %08X %s" % (h, e["Mode"]))
            changed.append(rec)
            touched.append(h)
        installed[region] = touched
        if dry or not changed:
            continue

        bk = ".presetbak_%s" % stamp
        for f in (dest, bm):
            if not os.path.exists(f + bk):
                shutil.copy2(f, f + bk)

        def restore(reason):
            print("   FAILED: %s" % reason)
            for f in (dest, bm):
                shutil.copy2(f + bk, f)
            print("   region %s restored from %s" % (region, bk))
            return False

        newraw, _ = RB.build(hdr, out, v, off, len(raw))
        open(dest, "wb").write(newraw)
        try:
            smh, _used = CG.rebuild(dreg)
        except RuntimeError as ex:
            ok_all = restore("blockmap could not be regenerated: %s" % ex) and ok_all
            continue
        open(bm, "wb").write(smh)
        from build_weapon import smh_holds
        if not all(smh_holds(smh, r["hash"], r["desc"]) for r in changed):
            ok_all = restore("a written record is not in the blockmap byte for byte") and ok_all
            continue
        ok, why = BC.blockmap_consistent(dreg)
        if not ok:
            ok_all = restore("blockmap not consistent after install: %s" % why) and ok_all
            continue
        print("   wrote %d record(s)" % len(changed))

    # Dependencies from the recipient's own install, then register the names.
    BC._IDX.clear()
    for region, hs in installed.items():
        if not hs:
            continue
        ported, err = make_resident(region, hs, global_h, where, dry)
        if ported:
            print("   region %s: %s %d dependency record(s)" % (region, "would port" if dry else "ported", len(ported)))
        if err:
            print("   FAILED: region %s - %s" % (region, err))
            ok_all = False
    if not dry:
        have = {((x.get("Hash") or "").upper(), x.get("Region") or "") for x in registry_rows()}
        for e in ents:
            for row in e.get("Registry") or []:
                k = ((row.get("Hash") or "").upper(), row.get("Region") or "")
                if k not in have:
                    BC.append_custom_row(row)
                    have.add(k)
        print("INSTALLED stamp %s" % stamp)
    else:
        print("(dry run - nothing written)")
    return 0 if ok_all else 1


def revert(stamp):
    n = 0
    for p in glob.glob(os.path.join(ROOT, "data", "bundles", "**", "*.presetbak_%s" % stamp), recursive=True):
        shutil.copy2(p, p[:-len(".presetbak_%s" % stamp)])
        n += 1
    print("REVERTED %d file(s) from install %s" % (n, stamp))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["capture", "install", "revert"])
    ap.add_argument("path")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if a.action == "capture":
        data = capture()
        io.open(a.path, "w", encoding="utf-8").write(json.dumps(data))
        print("CAPTURED %d record(s)" % len(data["Records"]))
        for n in data["Notes"]:
            print("   NOTE: %s" % n)
        return 0
    if a.action == "revert":
        revert(a.path)
        return 0
    return install(a.path, a.dry_run)


if __name__ == "__main__":
    sys.exit(main() or 0)
