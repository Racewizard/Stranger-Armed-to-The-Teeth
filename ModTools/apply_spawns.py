r"""Apply the AT3 launcher's NPC CONFIG edits to a region's .lvl.

The grid describes a DIFF from vanilla, one row per change:

    Action,Slot,Hash,X,Y,Z,Yaw
    edit,12,FFFC00CB,47.37,91.98,38.22,90
    delete,44,,,,,
    add,,BAF35C16,32.96,95.46,38.22,204.9

  edit    change an existing spawn: its character, position and/or facing.
          `Slot` indexes spawn_table() in the BASE file, the same numbering the
          launcher's grid shows.
  delete  remove that spawn entirely.
  add     create a new spawn of `Hash`, cloned from a donor of that character
          (see spawn_char.py / NEW_SPAWNS.md).

Nothing is expressed as "reset": a group reverts to vanilla simply by dropping
its rows, because the whole file is rebuilt from the base every run.

ORDER MATTERS, and slots are resolved up front. Deletes and adds move records
around, so every target offset is looked up against the base before anything is
written, and then:

    1. edits    - in place, no size change, cannot disturb anything
    2. deletes  - highest offset first, so lower offsets stay valid
    3. adds     - appended last, where shifting can no longer invalidate a slot

    python apply_spawns.py 01 --csv spawns_01.csv
    python apply_spawns.py 01 --csv spawns_01.csv --base <level from place_props>
    python apply_spawns.py 01 --revert
"""
import argparse, csv, math, os, shutil, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from whose_attachment import spawn_table
from spawn_prop import (ROOT, NEXT, ROT, POS, TINT, ZONE, lvl_path, u32, walk, pos_of)
from place_props import matrix_from_euler, zone_at
from spawn_char import (TYPE_OFF, NULL_ID, spawn_records, pick_donor, insert, fresh_ids,
                        catalogue)

BAK = ".spawnsbak"

# THE SAFE-DONOR STRATEGY.
#
# A spawn cloned from a hostile character never appears, however faithfully it
# is copied - even with the encounter's own job and tag carried across. A clone
# of an ambient character DOES appear, reliably. And retyping an EXISTING spawn
# is long-since proven (jailbreak_blisterz took over a boss's spawn).
#
# So `add` no longer clones a donor of the requested character. It clones the
# region's SAFE character - one that always appears unconditionally - and then
# writes the requested type over it. Build something that works, then change
# what it is.
#
# The sizes cooperate: clakker_clerk, outlaw_cutter and outlaw_shooter are all
# 201-byte records, so retyping between them changes no lengths. The 263-byte
# clakkers are a different shape and are flagged rather than silently retyped.
SAFE_CHAR = {"01": 0xBAF35C16}          # clakker_clerk - verified in game

# DONORS CONFIRMED IN GAME, PER REGION - the slot to clone for a new spawn.
#
# Found empirically 2026-08-30 by sweeping several donors at once and seeing
# which produced a visible NPC. Note how many are SCRIPTED: safe_donor's
# null-job preference would reject them, so an exact slot is recorded instead of
# a character. Job state turned out not to decide whether a clone appears.
#
# THE THING THAT MADE THIS HARD: a spawn placed at ground level falls THROUGH
# the floor and out of the world. It is created correctly and is visible on the
# radar, but you never see it - indistinguishable from "the add did nothing".
# Several rounds of testing were spent on that ambiguity. Place spawns a few
# units ABOVE the floor; the tests below all used +3.
SAFE_SLOT = {
    "01":  0,     # clakker_clerk, null-job, zone 3
    "02":  50,    # clakker_clerk, SCRIPTED, zone 9
    "02a": 7,     # dcasteraider,  SCRIPTED, zone 14
    "03":  0,     # clakker_clerk, null-job, zone 2
    "04":  62,    # grubb_leader,  SCRIPTED, zone 6   (slot 93 is the null-job one)
    "05":  118,   # wolvarkshooter, null-job, zone 20 - CONFIRMED IN GAME
                  # 2026-08-30. Slot 135 was never confirmed and is wrong; a
                  # 16-donor sweep found 8 that work (16, 31, 89?, 104?, 106,
                  # 109, 118, 140) and 8 that do not, with no property telling
                  # the two groups apart.
    "06":  0,     # wolvarkshooter,null-job, zone 3
    "00":  9,     # outlawboss_blisterz, SCRIPTED, zone 5
    # Region_00 disambiguated 2026-08-30 by a paired test: slot 9 spawned with
    # BOTH a fresh tag and the donor's tag, while null-job slots 2 and 7 spawned
    # with neither. The donor decides, not the tag and not the job.
}


def _factions():
    """type hash -> faction, from the launcher's global catalogue."""
    out = {}
    p = os.path.join(ROOT, "StrangerAT3", "RegionData", "GlobalCatalogue.csv")
    if not os.path.exists(p):
        return out
    with open(p, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            try:
                out[int(r["Hash"], 16)] = (r.get("Faction") or "").strip().lower()
            except (ValueError, KeyError):
                pass
    return out


def safe_donor(spawns, region, want_type=None):
    """The record to clone for a new spawn: null job, AND matching faction.

    THE DONOR'S FACTION MUST MATCH THE TARGET'S.

    Measured across all eight regions by adding one retyped spawn to each:

        donor -> target        regions          result
        friendly -> hostile    01               appears
        friendly -> friendly   03               appears
        hostile  -> hostile    06               appears
        hostile  -> FRIENDLY   00,02,02a,04,05  NEVER APPEARS

    Eight for eight. Retyping a hostile spawn into a friendly character is the
    one combination that fails; the other three all work. Regions 01 and 03 only
    worked before this because they happen to contain a clakker_clerk, which is
    friendly - that, and not anything about clerks, is why the clerk seemed
    special.

    Choosing by record length alone therefore picks a hostile donor in most
    regions (outlaw_shooter and wolvarkshooter dominate the null-job pool) and
    silently produces a spawn that never renders.
    """
    fac = _factions()
    want_fac = fac.get(want_type) if want_type is not None else None

    named = SAFE_CHAR.get(region)
    if named is not None:
        dr, why = pick_donor(spawns, named)
        if dr is not None and dr[3] == NULL_ID:
            if want_fac is None or fac.get(named) == want_fac:
                return dr, "safe donor %08X (%s)" % (named, why)

    free = [r for r in spawns if r[3] == NULL_ID]
    if not free:
        return None, "no null-job spawn in this region to clone"

    match = [r for r in free if want_fac is not None and fac.get(r[2]) == want_fac]
    pool, note = (match, "%s donor" % want_fac) if match else (free, "ANY-faction donor")
    lens = {}
    for r in pool:
        lens.setdefault(r[1], []).append(r)
    best = max(lens, key=lambda n: len(lens[n]))
    chosen = lens[best][0]
    warn = ""
    if not match and want_fac is not None:
        warn = (" - WARNING: no null-job %s donor in this region; a %s donor "
                "retyped to a %s character does not appear"
                % (want_fac, fac.get(chosen[2], "?"), want_fac))
    return chosen, "null-job %s (%d byte record)%s" % (note, best, warn)


def slot_offsets(d, recs):
    """Record offset for every spawn slot, in the launcher's numbering."""
    import bisect
    starts = sorted(recs)
    out = []
    for off, h in spawn_table(bytes(d)):
        i = bisect.bisect_right(starts, off) - 1
        s = starts[i] if i >= 0 else None
        out.append(s if (s is not None and s <= off < u32(d, s + NEXT)) else None)
    return out


def remove(d, recs, start, dlen):
    """Delete a record: cut the bytes out and fix every pointer past it.

    Unlinking instead - pointing the previous record past this one - would be
    wrong: a record's extent IS next minus start, so the previous record would
    swallow these bytes and be misparsed. That is what destroyed a sign post
    early on.
    """
    src = bytes(d)
    out = bytearray(src[:start]) + bytearray(src[start + dlen:])
    for s in recs:
        if s == start:
            continue
        moved = s if s < start else s - dlen
        v = u32(src, s + NEXT)
        struct.pack_into("<I", out, moved + NEXT, v if v <= start else v - dlen)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("region")
    ap.add_argument("--csv")
    ap.add_argument("--base")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--allow-wired", action="store_true",
                    help="accepted for compatibility; adds are no longer refused")
    ap.add_argument("--revert", action="store_true")
    ap.add_argument("--donor-slot", dest="donor_slot", type=int,
                    help="clone this exact slot instead of choosing a donor")
    ap.add_argument("--allow-delete", dest="allow_delete", action="store_true",
                    help="permit deletes - they disable every spawn in the region")
    ap.add_argument("--fresh-tags", dest="fresh_tags", action="store_true",
                    help="mint a unique tag/ids for added spawns instead of "
                         "sharing the donor's")
    a = ap.parse_args()
    p = lvl_path(a.region)

    if a.revert:
        if os.path.exists(p + BAK):
            shutil.copy2(p + BAK, p)
            print("reverted lm_level_%s.lvl" % a.region)
        else:
            print("nothing to revert - no %s" % BAK)
        return

    if not os.path.exists(p + BAK):
        shutil.copy2(p, p + BAK)
    base_path = a.base if (a.base and os.path.exists(a.base)) else p + BAK
    src = open(base_path, "rb").read()
    d = bytearray(src)

    if not a.csv or not os.path.exists(a.csv):
        open(p, "wb").write(src)
        print("no spawn edits for region_%s - level left as the base" % a.region)
        return

    edits, dels, adds, clones = [], [], [], []
    used_ids = set()
    with open(a.csv, newline="", encoding="utf-8-sig") as f:
        for ln, r in enumerate(csv.DictReader(f), 2):
            act = (r.get("Action") or "").strip().lower()
            if act not in ("edit", "delete", "add", "clone"):
                continue
            try:
                slot = int(r["Slot"]) if (r.get("Slot") or "").strip() else None
                h = (r.get("Hash") or "").strip()
                hh = int(h, 16) if h else None
                def num(k):
                    v = (r.get(k) or "").strip()
                    return float(v) if v else None
                # Optional per-row Donor: the slot to clone for THIS add. Lets
                # one run test several donors at once, each placed a few units
                # apart, so a single launch distinguishes them.
                dv = (r.get("Donor") or "").strip()
                tagmode = (r.get("Tag") or "").strip().lower()   # "donor" keeps it
                rec = (slot, hh, num("X"), num("Y"), num("Z"), num("Yaw"), ln,
                       int(dv) if dv else None, tagmode)
            except ValueError:
                print("  line %d: unreadable - skipped" % ln)
                continue
            if act == "edit":
                edits.append(rec)
            elif act == "delete":
                dels.append(rec)
            elif act == "clone":
                clones.append(rec)
            else:
                adds.append(rec)

    recs, end = walk(bytes(d))
    slots = slot_offsets(bytes(d), recs)
    base_slots = list(slots)
    base_sp = spawn_records(bytes(src), walk(bytes(src))[0])
    names = catalogue(a.region)
    print("region_%s: %d spawn slot(s) in the base; %d edit, %d delete, %d add, %d clone"
          % (a.region, len(slots), len(edits), len(dels), len(adds), len(clones)))

    # Capture clone sources as BYTES up front. Deletes and adds move records, so
    # an offset captured now would be stale by the time clones are applied.
    clone_src = []
    for slot, hh, x, y, z, yaw, ln, _dn, _tm in clones:
        if slot is None or slot >= len(slots) or slots[slot] is None:
            print("  line %d: clone source slot %s not in this level - skipped" % (ln, slot))
            continue
        s0 = slots[slot]
        blob = bytes(d[s0:u32(bytes(d), s0 + NEXT)])
        clone_src.append((blob, slot, x, y, z, yaw, ln))

    # 1. edits - in place
    for slot, hh, x, y, z, yaw, ln, _dn, _tm in edits:
        if slot is None or slot >= len(slots) or slots[slot] is None:
            print("  line %d: slot %s not in this level - skipped" % (ln, slot))
            continue
        s = slots[slot]
        if hh is not None:
            struct.pack_into("<I", d, s + TYPE_OFF, hh)
        q = list(pos_of(bytes(d), s) or (0, 0, 0))
        if x is not None: q[0] = x
        if y is not None: q[1] = y
        if z is not None: q[2] = z
        for k, v in enumerate(q):
            struct.pack_into("<f", d, s + POS + 4 * k, v)
        if yaw is not None:
            for k, v in enumerate(matrix_from_euler(yaw, 0.0, 0.0)):
                struct.pack_into("<f", d, s + ROT + 4 * k, v)
        if x is not None or y is not None or z is not None:
            zn, _ = zone_at(bytes(d), recs, tuple(q))
            if zn is not None:
                struct.pack_into("<I", d, s + ZONE, zn)
        print("  edit slot %-3d -> %-20s (%8.2f,%8.2f,%7.2f)%s"
              % (slot, names.get(hh, "") if hh else "(unchanged)", q[0], q[1], q[2],
                 "" if yaw is None else "  yaw %.1f" % yaw))

    # 2. deletes - REFUSED BY DEFAULT.
    #
    # DELETING A SPAWN DISABLES EVERY SPAWN IN THE REGION.
    #
    # Measured 2026-08-30 in region_00. A run of 1 add + 21 in-place retypes
    # worked: the retyped NPCs appeared. The very next run differed only by
    # removing two null-job spawns (and adding two back, so the total count was
    # unchanged at 21) - and the region came back COMPLETELY VANILLA. Not one
    # spawn changed, including the retype that had worked moments before.
    #
    # So a delete does not merely drop its own record; it takes the region's
    # whole spawn set with it. The cause is unknown - the chain re-links
    # correctly and check_groups stays consistent - but something else indexes
    # these records and a removal invalidates it.
    #
    # This is the worst possible failure mode: silent, total, and it looks
    # exactly like "the tool did nothing", which is how it cost several test
    # launches before being isolated. Refuse it unless explicitly forced.
    if dels and not getattr(a, "allow_delete", False):
        print("  REFUSED %d delete(s): removing a spawn disables EVERY spawn in "
              "the region. Retype it to something harmless instead, or pass "
              "--allow-delete if you are deliberately testing this." % len(dels))
        dels = []
    todo = []
    for slot, hh, x, y, z, yaw, ln, _dn, _tm in dels:
        if slot is None or slot >= len(slots) or slots[slot] is None:
            print("  line %d: slot %s not in this level - skipped" % (ln, slot))
            continue
        todo.append((slots[slot], slot))
    for s, slot in sorted(todo, reverse=True):
        recs, end = walk(bytes(d))
        dlen = u32(bytes(d), s + NEXT) - s
        d = remove(d, recs, s, dlen)
        print("  delete slot %-3d (%d bytes)" % (slot, dlen))

    # 3. adds - last, where shifting can no longer invalidate a slot
    for slot, hh, x, y, z, yaw, ln, row_donor, tagmode in adds:
        if hh is None or None in (x, y, z):
            print("  line %d: add needs Hash and X,Y,Z - skipped" % ln)
            continue
        recs, end = walk(bytes(d))
        sp = spawn_records(bytes(d), recs)
        # --donor-slot forces an exact donor, bypassing every heuristic. It
        # exists so a specific record can be tested as the clone source without
        # rewriting the selection rules to reach it.
        # A per-row Donor column beats the global --donor-slot, so one run can
        # test several donors at once - each add cloned from a different source,
        # placed a few units apart. One launch, many hypotheses.
        #
        # A forced donor is read from the UNMODIFIED BASE, not from `d`. Each
        # add splices bytes in and shifts every later offset, so a slot table
        # built once against the base goes stale after the first insertion - the
        # second add would clone from the wrong place.
        forced = row_donor
        if forced is None:
            forced = getattr(a, "donor_slot", None)
        if forced is None:
            forced = SAFE_SLOT.get(a.region)
        base_donor = None
        if forced is not None and 0 <= forced < len(base_slots) and base_slots[forced] is not None:
            bs = base_slots[forced]
            bmatch = [r for r in base_sp if r[0] == bs]
            if bmatch:
                base_donor = (bs, bmatch[0][1])
        if base_donor is not None:
            dr, why = None, "FORCED donor slot %d (from base)" % forced
        else:
            dr, why = safe_donor(sp, a.region, hh)
        if dr is None and base_donor is None:
            print("  line %d: %s" % (ln, why))
            continue
        dn, dln = base_donor if base_donor is not None else (dr[0], dr[1])
        # warn when retyping across record shapes - the clone keeps the safe
        # character's length, and a type that normally needs more may not fit
        want_len = [r[1] for r in sp if r[2] == hh]
        if want_len and dln not in want_len:
            print("  line %d: NOTE %08X normally uses a %d-byte record, the clone is %d"
                  % (ln, hh, want_len[0], dln))
        # NOTE ONLY - do not refuse.
        #
        # This used to refuse characters with no job-less vanilla spawn,
        # because adding outlawboss_lootenduke was followed by a crash on
        # entering region_01. That was a false conclusion: the crash had a
        # separate, sufficient cause - preset-injected npc_19.smb and
        # npc_23.smb left on disk against a vanilla blockmap that no longer
        # described their sizes. The region crashed with no added spawn at
        # all, which is what finally showed it.
        #
        # Adding such a character is therefore unproven, not known-bad, so
        # this says so and gets out of the way.
        mine = [r for r in sp if r[2] == hh]
        if mine and not any(r[3] == NULL_ID for r in mine):
            print("  line %d: NOTE %s has no job-less vanilla spawn - every "
                  "instance is encounter-wired. Adding one is untested."
                  % (ln, names.get(hh, "%08X" % hh)))
        target = (x, y, z)
        zn, _ = zone_at(bytes(d), recs, target)
        nearest, best = None, None
        for sx in recs:
            q = pos_of(bytes(d), sx)
            if q is None:
                continue
            dd = math.dist(q, target)
            if best is None or dd < best:
                nearest, best = sx, dd
        place = u32(bytes(d), nearest + NEXT)
        # Forced donors index the BASE, so their bytes must come from the base
        # too; heuristic donors were resolved against `d` and come from `d`.
        rec = bytearray((bytes(src) if base_donor is not None else bytes(d))[dn:dn + dln])
        struct.pack_into("<I", rec, NEXT, place + dln)
        struct.pack_into("<I", rec, TYPE_OFF, hh)
        # OPTIONAL: give the clone its OWN tag and ids.
        #
        # A clone inherits the donor's tag at +16 verbatim, so donor and clone
        # share one tag - and the engine spawns characters by walking tags
        # (SpawnNPCFromTag). If it honours one NPC per tag, the donor wins and
        # the clone never appears, which is the shape of the unexplained add
        # failures in regions 00, 02a, 04 and 05.
        #
        # NEW_SPAWNS.md warns that inventing a tag is "not obviously safe" - it
        # was never tried, only avoided. This makes it testable. Off by default.
        # SEVER THE CLONE'S SCRIPT WIRING. Always.
        #
        # A clone inherits the donor's tag (+16) and job (+92) verbatim, and a
        # SCRIPTED donor's role then has two claimants. The script picks the
        # wrong one: cloning region_02a's dcasteraider put our clakker into the
        # cutscene that should cast the raider. Nothing in the FILES changes -
        # both records are byte-identical to vanilla apart from the clone - so
        # this is invisible to any static check and only shows in game.
        #
        # A null job means "spawns unconditionally, runs no script", which is
        # exactly what an added NPC should be. Combined with a fresh tag the
        # clone cannot be mistaken for the donor by anything.
        struct.pack_into("<I", rec, 92, NULL_ID)
        # The job is MIRRORED at +195 (see NEW_SPAWNS.md section 2). Nulling one
        # copy and leaving the other would sever the wiring only halfway.
        if len(rec) >= 199:
            struct.pack_into("<I", rec, 195, NULL_ID)
        # Tag=donor keeps the donor's tag at +16. The engine spawns characters
        # by walking TAGS (SpawnNPCFromTag), so a clone with a tag nothing
        # references may never be visited at all - which is what a radar dot
        # with no model looks like. Sharing the tag is what let region_00's
        # clone spawn, and also what let region_02a's clone hijack a cutscene,
        # so the two are in tension and worth testing separately.
        ids = fresh_ids(bytes(d), used_ids, 3)
        if tagmode != "donor":
            struct.pack_into("<I", rec, 16, ids[0])
        struct.pack_into("<I", rec, 96, ids[1])
        struct.pack_into("<I", rec, 108, ids[2])

        if False and getattr(a, "fresh_tags", False):
            ids = fresh_ids(bytes(d), used_ids, 3)
            struct.pack_into("<I", rec, 16, ids[0])
            struct.pack_into("<I", rec, 96, ids[1])
            struct.pack_into("<I", rec, 108, ids[2])
        if zn is not None:
            struct.pack_into("<I", rec, ZONE, zn)
        for k, v in enumerate(matrix_from_euler(yaw or 0.0, 0.0, 0.0)):
            struct.pack_into("<f", rec, ROT + 4 * k, v)
        for k, v in enumerate(target):
            struct.pack_into("<f", rec, POS + 4 * k, v)
        if u32(bytes(d), nearest + NEXT) - nearest > TINT + 4:
            rec[TINT:TINT + 4] = d[nearest + TINT:nearest + TINT + 4]
        d = insert(d, recs, dn, dln, place, rec)
        struct.pack_into("<I", d, nearest + NEXT, place)
        print("  add %-20s (%8.2f,%8.2f,%7.2f) yaw %6.1f zone %s   [%s, retyped]"
              % (names.get(hh, "%08X" % hh), x, y, z, yaw or 0.0, zn, why))

    # 4. clones - a byte-for-byte copy of one existing spawn, job and tag
    # included, moved to a new spot.
    #
    # This is how a new character joins a SCRIPTED encounter. `add` picks a
    # null-job donor on purpose, which strips the wiring that activates a
    # fight's members - measured: a cloned clakker_clerk appeared in game while
    # an added outlaw_cutter never did, because the only null-job cutter in
    # region_01 stands alone at (259, 329, 88) with no encounter behind it.
    # The crane_pair cutters carry jobs F7E25A11 and 717628BF; copying one of
    # those carries its activation across too.
    for blob, slot, x, y, z, yaw, ln in clone_src:
        recs, end = walk(bytes(d))
        dln = len(blob)
        target = (x, y, z)
        zn, _ = zone_at(bytes(d), recs, target)
        nearest, best = None, None
        for sx in recs:
            q = pos_of(bytes(d), sx)
            if q is None:
                continue
            dd = math.dist(q, target)
            if best is None or dd < best:
                nearest, best = sx, dd
        place = u32(bytes(d), nearest + NEXT)
        rec = bytearray(blob)
        struct.pack_into("<I", rec, NEXT, place + dln)
        if zn is not None:
            struct.pack_into("<I", rec, ZONE, zn)
        if yaw is not None:
            for k, v in enumerate(matrix_from_euler(yaw, 0.0, 0.0)):
                struct.pack_into("<f", rec, ROT + 4 * k, v)
        for k, v in enumerate(target):
            struct.pack_into("<f", rec, POS + 4 * k, v)
        d = insert(d, recs, 0, dln, place, rec)
        struct.pack_into("<I", d, nearest + NEXT, place)
        print("  clone of slot %-3d -> (%8.2f,%8.2f,%7.2f)  job %08X  tag %08X"
              % (slot, x, y, z, u32(bytes(rec), 92), u32(bytes(rec), 16)))

    if a.check:
        print("\ncheck only - nothing written")
        return
    open(p, "wb").write(bytes(d))

    chk = open(p, "rb").read()
    r2, e2 = walk(chk)
    bad = sum(1 for i, s in enumerate(r2)
              if u32(chk, s + NEXT) != (r2[i + 1] if i + 1 < len(r2) else e2))
    ok = (u32(chk, e2) == 0x601307A6 and bad == 0 and r2 == sorted(r2))
    print("\nchain: %d records, %d spawns, %d non-contiguous -> %s"
          % (len(r2), len(spawn_table(chk)), bad, "OK" if ok else "BROKEN"))
    if not ok:
        open(p, "wb").write(src)
        print("chain did not verify - reverted to the base, nothing applied")


if __name__ == "__main__":
    main()
