r"""Bone names for every character rig, read from the kind-20 skeleton records.

An attachment entry names its bone as a plain string and a wrong name fails
SILENTLY - the attachment just never renders. The names are not guessable and
are not in the .geo: they live in the kind-20 record, prefixed with the rig name
(`twnsFlk_spn2`), while the attachment list stores only the suffix (`spn2`).

    python rig_bones.py                 every rig
    python rig_bones.py twnsFlk         one rig
"""
import os, re, sys, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rebuild_bundle as RB

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOK = re.compile(rb"[A-Za-z][A-Za-z0-9_]{2,30}")


def bones_of(desc):
    """(rig prefix, [bone names without the prefix]) of one kind-20 record."""
    toks = [t.decode() for t in TOK.findall(desc)]
    named = [t for t in toks if "_" in t]
    if not named:
        return None, []
    rig = named[0].split("_")[0]
    bones = []
    for t in named:
        if not t.startswith(rig + "_"):
            break
        b = t[len(rig) + 1:]
        if b not in bones:
            bones.append(b)
    return rig, bones


def rigs():
    out = {}
    for p in glob.glob(os.path.join(ROOT, "data", "bundles", "**", "*.smb"), recursive=True):
        try:
            recs = RB.parse(open(p, "rb").read())[1]
        except Exception:
            continue
        for r in recs:
            if r["kind"] != 20:
                continue
            rig, bones = bones_of(r["desc"])
            # Keep every DISTINCT bone list under a prefix, not just the
            # longest. twnsFlk ships two skeletons that differ only in the hand
            # bones - grabL/grabR on one, grbL/grbR on the other - and picking
            # one hides the other, which is exactly the mistake that sends an
            # attachment to a bone the character does not have.
            if rig and bones:
                out.setdefault(rig, [])
                if bones not in out[rig]:
                    out[rig].append(bones)
    return out


if __name__ == "__main__":
    want = sys.argv[1].lower() if len(sys.argv) > 1 else None
    for rig, variants in sorted(rigs().items()):
        if want and want != rig.lower():
            continue
        for n, bones in enumerate(variants):
            tag = "" if len(variants) == 1 else "  variant %d of %d" % (n + 1, len(variants))
            print("%s  (%d bones)%s" % (rig, len(bones), tag))
            for i in range(0, len(bones), 8):
                print("   " + "  ".join("%-14s" % b for b in bones[i:i + 8]).rstrip())
