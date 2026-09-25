r"""Apply a batch of LevelPrefs edits, for the AT3 launcher's ENVIRONMENT CONFIG.

`levelprefs.py set` writes one field per invocation, which is fine by hand but
means dozens of processes when a tab full of values is applied at once. This
takes the whole lot in one CSV and one pass.

    Field,SetIndex,Value
    fogColor,1,"0.55 0.30 0.40 1.0"
    fogStart,1,80
    colorBase,0,"0.3 0.3 1.0 1.0"

`SetIndex` selects which LevelPrefs set (area) to write - 0 is the region
default. Fog is per-area; sky, water and the fade fields exist only in set 0,
and rows targeting them elsewhere are refused rather than silently written to
a byte range that means something else.

Only fog is confirmed to have a visible effect in game. Sky, water and lighting
decode and write correctly but showed no change in testing - see
ENVIRONMENT_HANDOFF.md. Rows for those are applied as asked and reported, but
do not expect them to do anything yet.

    python apply_env.py 01 --csv env_edits_01.csv
    python apply_env.py 01 --csv env_edits_01.csv --check
    python apply_env.py 01 --revert
"""
import argparse, csv, os, shutil, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import levelprefs as L


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("region")
    ap.add_argument("--csv")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--revert", action="store_true")
    a = ap.parse_args()
    p = L.lvl_path(a.region)

    if a.revert:
        b = p + ".envbak"
        if os.path.exists(b):
            shutil.copy2(b, p)
            print("reverted region_%s environment to vanilla" % a.region)
        else:
            print("no .envbak for region_%s" % a.region)
        return

    if not a.csv or not os.path.exists(a.csv):
        print("no environment edits for region_%s" % a.region)
        return

    d = bytearray(open(p, "rb").read())
    aa = L.anchors(bytes(d))
    if not aa:
        sys.exit("no LevelPrefs anchor in region_%s" % a.region)
    names = [L.area_name(bytes(d), c) for c in aa]

    applied = skipped = 0
    with open(a.csv, newline="", encoding="utf-8-sig") as f:
        for ln, row in enumerate(csv.DictReader(f), 2):
            field = (row.get("Field") or "").strip()
            if not field:
                continue
            if field not in L.FIELDS:
                print("  line %d: unknown field %r" % (ln, field))
                skipped += 1
                continue
            off, kind, region_only = L.FIELDS[field]
            try:
                n = int(row.get("SetIndex") or 0)
            except ValueError:
                n = 0
            if n < 0 or n >= len(aa):
                print("  line %d: set %d out of range (%d sets)" % (ln, n, len(aa)))
                skipped += 1
                continue
            if region_only and n != 0:
                print("  line %d: %s exists only in the region default, "
                      "not in set %d - refused" % (ln, field, n))
                skipped += 1
                continue

            raw = (row.get("Value") or "").replace(",", " ").split()
            c = aa[n]
            before = L.read_field(bytes(d), c, off, kind)
            try:
                if kind == "c":
                    if len(raw) != 4:
                        raise ValueError("a colour needs 4 values")
                    struct.pack_into("<4f", d, c + off, *[float(v) for v in raw])
                elif kind == "f":
                    struct.pack_into("<f", d, c + off, float(raw[0]))
                elif kind == "v2":
                    # A vec2 is TWO floats, 8 bytes - the cloud uvSpeed fields.
                    # Without this branch it fell through to the u32 case below
                    # and wrote 4 bytes of a parsed integer over half of it.
                    if len(raw) != 2:
                        raise ValueError("a vec2 needs 2 values")
                    struct.pack_into("<2f", d, c + off, *[float(v) for v in raw])
                else:
                    struct.pack_into("<I", d, c + off, int(raw[0], 0))
            except (ValueError, IndexError) as e:
                print("  line %d: %s - %s" % (ln, field, e))
                skipped += 1
                continue
            after = L.read_field(bytes(d), c, off, kind)
            if str(before) != str(after):
                area = names[n] or ("set %d" % n)
                print("  %-28s [%s] %s -> %s" % (field, area, before, after))
                applied += 1

    if a.check:
        print("\ncheck only - nothing written (%d change(s) pending)" % applied)
        return
    if applied:
        L.backup(p)
        open(p, "wb").write(bytes(d))
    print("\nregion_%s: %d field(s) changed, %d skipped" % (a.region, applied, skipped))


if __name__ == "__main__":
    main()
