r"""Read and edit a character's attachment list.

The list sits at the very end of a character record, after the audio/bounty
strings, and is laid out as

    <u32 count>
    count x  <u32 namelen><bone name><u32 geoHash><9f rot><3f translate><f scale>
    <29-byte tail>          (two floats 75.0/200.0 then fixed data - never moved)

Found by locating the count that makes the entries parse and land exactly 29
bytes short of the record end, so no absolute offset is assumed - the strings
before it vary in length per character.

Bone names are per-rig and are NOT interchangeable. What retail actually uses:

    hd                    every rig
    spn2                  spine/torso        (outlawCutter's knife quiver)
    grabL                 townsfolk rig      (45 bones, long form)
    grbR                  outlaw rigs        (42 bones, short form)
    clvL / clvR           clavicles          (verified visible on this project's
                                              townsfolk-rig clakker)
    weapnode_melee_wpn1   weapon nodes
    weapnode_melee_wpn2
    weapnode_ranged_wpn1

A bone the rig does not have fails silently - the attachment simply never
renders - so check ATTACHMENTS_INDEX.md and prefer a name retail already uses.

    python attach_edit.py utility E25E452F --list
    python attach_edit.py utility E25E452F --add spn2=EE55DBAC@0.1
    python attach_edit.py utility E25E452F --set spn2 --trans 0,-0.5,0 --scale 0.08
    python attach_edit.py utility E25E452F --rename grabL=grbL
    python attach_edit.py utility E25E452F --remove spn2
    python attach_edit.py utility --revert
"""
import argparse, math, os, shutil, struct, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rebuild_bundle as RB

ROOT = os.path.dirname(HERE)
BAK = ".attachbak"
TAIL = 29
IDENT = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)


def bundle_path(region):
    if region == "utility":
        return os.path.join(ROOT, "data", "bundles", "utility", "empty", "empty_tag.smb")
    return RB.find_bundle(region, "lm_level_%s_tgl.smb" % region)


def find_list(b):
    """(count_offset, [entries]) - entries are dicts, in file order."""
    best = None
    for c in range(len(b) - 8):
        n = struct.unpack_from("<I", b, c)[0]
        if not (1 <= n <= 12):
            continue
        o, ents, ok = c + 4, [], True
        for _ in range(n):
            if o + 8 > len(b):
                ok = False
                break
            ln = struct.unpack_from("<I", b, o)[0]
            if not (1 <= ln <= 24 and o + 4 + ln + 56 <= len(b)):
                ok = False
                break
            nm = b[o + 4:o + 4 + ln]
            if not all(48 <= ch < 127 for ch in nm):
                ok = False
                break
            p = o + 4 + ln
            sc = struct.unpack_from("<f", b, p + 52)[0]
            if not (0.0 < sc < 1000.0):
                ok = False
                break
            ents.append({"bone": nm.decode(),
                         "geo": struct.unpack_from("<I", b, p)[0],
                         "rot": list(struct.unpack_from("<9f", b, p + 4)),
                         "tr": list(struct.unpack_from("<3f", b, p + 40)),
                         "scale": sc})
            o = p + 56
        if ok and ents and len(b) - o == TAIL:
            best = (c, ents)
    return best


def pack(ents):
    out = struct.pack("<I", len(ents))
    for e in ents:
        nm = e["bone"].encode()
        out += struct.pack("<I", len(nm)) + nm + struct.pack("<I", e["geo"])
        out += struct.pack("<9f", *e["rot"]) + struct.pack("<3f", *e["tr"])
        out += struct.pack("<f", e["scale"])
    return out


def show(ents):
    for e in ents:
        print("   %-22s geo=%08X  scale=%-7g trans=(%g, %g, %g)"
              % (e["bone"], e["geo"], e["scale"], e["tr"][0], e["tr"][1], e["tr"][2]))
        r = e["rot"]
        if tuple(r) != IDENT:
            print("      rot [%6.3f %6.3f %6.3f][%6.3f %6.3f %6.3f][%6.3f %6.3f %6.3f]" % tuple(r))


def rot_axis(axis, deg):
    # Snap the cardinal cases: cos(90 deg) comes out as 6.1e-17, which stores a
    # non-zero matrix element that reads as noise next to the vanilla entries.
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    c = round(c, 12) + 0.0
    s = round(s, 12) + 0.0
    if axis == "x":
        return [1, 0, 0, 0, c, -s, 0, s, c]
    if axis == "y":
        return [c, 0, s, 0, 1, 0, -s, 0, c]
    return [c, -s, 0, s, c, 0, 0, 0, 1]


def matmul(a, b):
    """Row-major 3x3 product."""
    return [sum(a[i * 3 + k] * b[k * 3 + j] for k in range(3))
            for i in range(3) for j in range(3)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("region")
    ap.add_argument("char", nargs="?")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--add", action="append", default=[],
                    help="bone=GEOHASH[@scale]")
    ap.add_argument("--set", dest="target",
                    help="bone to modify; use bone#N to pick the Nth entry on "
                         "that bone when a character wears more than one there "
                         "(retail does this - outlawCutter DDD3C8B8 carries two "
                         "on weapnode_melee_wpn1)")
    ap.add_argument("--remove")
    ap.add_argument("--rename", action="append", default=[],
                    help="old=new - move an attachment to a different bone, "
                         "keeping its rotation, translation and scale")
    ap.add_argument("--scale", type=float)
    ap.add_argument("--trans", help="x,y,z")
    ap.add_argument("--rot", help="axis:degrees - REPLACES the whole matrix")
    ap.add_argument("--turn", action="append", default=[],
                    help="axis:degrees - COMPOSES onto the current rotation in "
                         "bone space, so an existing tilt survives")
    ap.add_argument("--turn-local", dest="turn_local", action="append", default=[],
                    help="same, but about the attachment's own axes")
    ap.add_argument("--revert", action="store_true")
    a = ap.parse_args()

    path = bundle_path(a.region)
    if a.revert:
        if os.path.exists(path + BAK):
            shutil.copy2(path + BAK, path)
            print("restored %s" % os.path.basename(path))
        else:
            print("no %s to restore" % BAK)
        return

    raw = open(path, "rb").read()
    hdr, recs, v, off = RB.parse(raw)
    probe, _ = RB.build(hdr, recs, v, off, len(raw))
    if probe != raw:
        print("REFUSED: %s does not round-trip" % os.path.basename(path))
        return
    want = int(a.char, 16)
    out, touched = [], 0
    for r in recs:
        if r["hash"] != want:
            out.append(r)
            continue
        b = r["desc"]
        got = find_list(b)
        if not got:
            print("%08X: no attachment list found" % want)
            return
        c, ents = got
        if a.list:
            print("%08X in %s: %d attachment(s), list at +%d"
                  % (want, os.path.basename(path), len(ents), c))
            show(ents)
            return
        for spec in a.add:
            bone, rhs = spec.split("=", 1)
            geo, _, sc = rhs.partition("@")
            ents.append({"bone": bone, "geo": int(geo, 16), "rot": list(IDENT),
                         "tr": [0.0, 0.0, 0.0], "scale": float(sc) if sc else 1.0})
        for spec in a.rename:
            old, new = spec.split("=", 1)
            for e in ents:
                if e["bone"] == old:
                    e["bone"] = new
        if a.remove:
            ents = [e for e in ents if e["bone"] != a.remove]
        if a.target:
            tb, _, tix = a.target.partition("#")
            want_ix = int(tix) if tix else None
            seen_ix = -1
            for e in ents:
                if e["bone"] != tb:
                    continue
                seen_ix += 1
                if want_ix is not None and seen_ix != want_ix:
                    continue
                if a.scale is not None:
                    e["scale"] = a.scale
                if a.trans:
                    e["tr"] = [float(x) for x in a.trans.split(",")]
                if a.rot:
                    ax, _, dg = a.rot.partition(":")
                    e["rot"] = rot_axis(ax.lower(), float(dg))
                for spec in a.turn:
                    ax, _, dg = spec.partition(":")
                    e["rot"] = matmul(rot_axis(ax.lower(), float(dg)), e["rot"])
                for spec in a.turn_local:
                    ax, _, dg = spec.partition(":")
                    e["rot"] = matmul(e["rot"], rot_axis(ax.lower(), float(dg)))
        nd = b[:c] + pack(ents) + b[len(b) - TAIL:]
        r = dict(r)
        r["desc"] = nd
        touched += 1
        out.append(r)
        print("%08X: %d attachment(s), record %d -> %d B" % (want, len(ents), len(b), len(nd)))
        show(ents)
    if a.list:
        print("%08X not found in %s" % (want, os.path.basename(path)))
        return
    if not touched:
        print("%08X not found in %s" % (want, os.path.basename(path)))
        return
    if not os.path.exists(path + BAK):
        shutil.copy2(path, path + BAK)
    new, _ = RB.build(hdr, out, v, off, len(raw))
    open(path, "wb").write(new)


if __name__ == "__main__":
    main()
