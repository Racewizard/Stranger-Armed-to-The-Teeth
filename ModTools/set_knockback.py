r"""Set m_maxKnockSpeedPlayer (and optionally m_maxKnockSpeed) on ammo prefs.

Each ammo type has a serialised prefs record in EVERY region that can fire it,
holding two floats:

    +164  m_maxKnockSpeed        how hard the blast throws NPCs and objects
    +168  m_maxKnockSpeedPlayer  how hard it throws STRANGER

Vanilla ships -1 for the player field everywhere, which is why an explosion at
your feet does nothing to you. Raising it turns a blast into a launch pad, which
is how you clear an invisible wall or leave an area whose exit is gated behind a
bounty you cannot take.

Offsets come from StrangerAT3/AmmoPatchMap.csv, which the launcher built from
the exe's reflection tables. That map only names the regions that existed when
it was built, so a COPIED region (emptygulch) is addressed by substituting the
region name in each path - valid only while the copy's tgl and blockmap keep the
donor's record layout, which is why the class tag at RecOff+0x14 is re-checked
before every single write and the write is skipped if it does not match.

BOTH files are patched. The .smh blockmap holds a byte copy of the bundle's
section 1 and the game loads from THAT, so writing only the .smb changes nothing
in game - see the blockmap-holds-the-live-copy note.

    python set_knockback.py --list region_01
    python set_knockback.py --region region_01 --region emptygulch \
           --ammo damagedynamite --player 1000
    python set_knockback.py --revert
"""
import argparse, csv, os, shutil, struct, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAP = os.path.join(ROOT, "StrangerAT3", "AmmoPatchMap.csv")
TAG = 0x000B4265
BAK = ".selfknockbak"


def load(region):
    """Patch-map rows addressed at `region`, substituting the donor path."""
    out = []
    for r in csv.DictReader(open(MAP)):
        f = r["File"]
        if "/region_01/" not in f:
            continue
        if region != "region_01":
            f = f.replace("region_01", region)
        r = dict(r)
        r["File"] = os.path.join(ROOT, f.replace("/", os.sep))
        out.append(r)
    return out


def rdf(p, o):
    with open(p, "rb") as f:
        f.seek(o)
        return struct.unpack("<f", f.read(4))[0]


def rdu(p, o):
    with open(p, "rb") as f:
        f.seek(o)
        return struct.unpack("<I", f.read(4))[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--region", action="append", default=[])
    ap.add_argument("--ammo", action="append", default=[])
    ap.add_argument("--player", type=float)
    ap.add_argument("--knock", type=float)
    ap.add_argument("--list")
    ap.add_argument("--revert", action="store_true")
    a = ap.parse_args()

    if a.revert:
        n = 0
        for dp, _, fs in os.walk(os.path.join(ROOT, "data", "bundles")):
            for f in fs:
                if f.endswith(BAK):
                    src = os.path.join(dp, f)
                    shutil.copyfile(src, src[: -len(BAK)])
                    os.remove(src)
                    n += 1
        print("reverted %d file(s)" % n)
        return

    if a.list:
        rows = [r for r in load(a.list) if r["File"].endswith(".smb")]
        print("%-38s %10s %12s" % ("ammo", "knock", "knockPlayer"))
        for r in sorted(rows, key=lambda x: x["Name"]):
            if not os.path.exists(r["File"]):
                continue
            print("%-38s %10.2f %12.2f"
                  % (r["Name"], rdf(r["File"], int(r["OffKnock"])),
                     rdf(r["File"], int(r["OffKnockPlayer"]))))
        return

    if not a.region or not a.ammo or (a.player is None and a.knock is None):
        sys.exit("need --region, --ammo and at least one of --player/--knock")

    want = set(a.ammo)
    total = skipped = 0
    needs_repair = set()
    for region in a.region:
        rows = [r for r in load(region) if r["Name"] in want]
        if not rows:
            print("%-12s no matching ammo rows" % region)
            continue
        for r in rows:
            p = r["File"]
            if not os.path.exists(p):
                print("   missing %s" % p)
                continue
            # The map .smh offsets belong to region_01 blockmap. A COPIED
            # region blockmap is a different size, so those offsets address
            # the wrong bytes there - writing them corrupts the index silently.
            # Patch only the .smb for a copy and regenerate the blockmap from it.
            if region != "region_01" and p.endswith(".smh"):
                needs_repair.add(region)
                continue
            tag = rdu(p, int(r["RecOff"]) + 0x14)
            if tag != TAG:
                print("   SKIP %s in %s: class tag %08X, expected %08X"
                      % (r["Name"], os.path.basename(p), tag, TAG))
                skipped += 1
                continue
            if not os.path.exists(p + BAK):
                shutil.copyfile(p, p + BAK)
            with open(p, "r+b") as f:
                if a.knock is not None:
                    f.seek(int(r["OffKnock"]))
                    f.write(struct.pack("<f", a.knock))
                if a.player is not None:
                    f.seek(int(r["OffKnockPlayer"]))
                    f.write(struct.pack("<f", a.player))
            total += 1
        # read back from the .smb, which is what --list shows
        smb = [r for r in rows if r["File"].endswith(".smb")]
        print("%-12s %d write(s)" % (region, len([r for r in rows])))
        for r in sorted(smb, key=lambda x: x["Name"]):
            print("    %-34s knock %8.2f  knockPlayer %8.2f"
                  % (r["Name"], rdf(r["File"], int(r["OffKnock"])),
                     rdf(r["File"], int(r["OffKnockPlayer"]))))
    print("\n%d record(s) written, %d skipped on tag mismatch" % (total, skipped))
    for region in sorted(needs_repair):
        print("  %s is a copied region: only its .smb was written. Run" % region)
        print("     python ModTools/check_groups.py %s --repair" % region)
        print("  to rebuild its blockmap from it - the game reads the blockmap.")


if __name__ == "__main__":
    main()
