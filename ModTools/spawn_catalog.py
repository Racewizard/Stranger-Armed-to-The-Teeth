r"""Spawn catalogue: what each spawn is, where it stands, and what drives it - LIVE.

The Spawns Editor needs two views of a region's level, and this writes both:

  THE BASE  `lm_level_NN.lvl.spawnsbak`, the file apply_spawns.py rebuilds from
            on every Apply Changes. Saved edits (spawns_<r>.csv) are keyed to its
            slot numbers, so the Spawns Editor's baseline columns come from it
            and nothing else.
  THE LIVE  `lm_level_NN.lvl`, what the game actually loads: already modded, and
            it keeps changing - added spawns, clones, retypes, preset writes. Every
            descriptive column (character, position, zone, group, script, jobs)
            comes from here.

A base slot is found in the live level by (tag +16, id +96, id +108). That key
is unique in every retail region's base; the tag alone is not (regions 03 and
05 ship duplicate tags). A clone copies the key, so when several live records
carry it the one nearest the slot's expected position is the slot and the rest
are clones. Live spawns that match no slot are paired with the editor's add and
clone rows by position; any left over came from somewhere other than the
Spawns Editor and are listed as such, never hidden.

Writes into StrangerAT3\RegionData:

    spawntable_<r>.csv   one row per BASE slot. The first nine columns
                         (Slot,Tag,Hash,Name,X,Y,Z,Yaw,Job) are the editor's
                         baseline, from the base, unchanged in meaning. The rest
                         describe that slot as it is in the live level.
    spawnlive_<r>.csv    one row per spawn in the LIVE level, with its origin
    spawnjobs_<r>.csv    one row per JobTag in the live level
    spawnzones_<r>.csv   one row per zone

DECODED 2026-09-14, checked against all eight retail regions (1,275 spawns,
1,516 JobTags). Read-only: nothing here writes a game file.

SPAWN RECORD (class InstancedObjectTag 2B9F6678), beyond spawn_char.py's table
    +20   zone index into WorldTag's zone list (see below)
    +82   GROUP = game_hash(group name). Scripts address it by name:
          MoveOutOfPurgatoryGroup("FallingBeamsGroup") hashes to the +82 of the
          records it releases. Boilz Booty's town fight is group "Gun_Fight"
          (E2FF89A9) - all nine fighters, scripted or not, and no script names
          any of them individually. Props carry groups too.
    +92   SCRIPT = the spawn's attached script. It is NOT a JobTag: it is
          game_hash of a .foo path (\data\levels\Region_01\Scripts\...foo) or of
          an inline script's tag path (|Tag_area_01|Design|Gun_Fight|NPCs|...).
          Resolved 461/461. Repeated at RECORD LENGTH - 6 on every spawn, which
          is +195 only on a 201-byte record.
    +100  AREA = game_hash of the source .tag file
          (/data/levels/Region_01/lm_town_01_1.tag).

JOBTAG (3DB9BAD3). A job points AT a spawn; nothing in the spawn points back.
    +88   u32 length, then the job's point list ("point1|<tag>|point2|<tag>")
    then, from the end of that string (p):
    p+0   job SCRIPT - what the job does (Empty_Job.foo, OA_01_3_Patrol.foo,
          NPC_All_ChargeAt01.foo, OA1_GuardDemolitions.foo, ...)
    p+4   the job's own hash
    p+8   AREA hash - where the layout is proven: valid on 1,516 of 1,516
    p+32  restricted to this specific spawn = that spawn's TAG (+16)
    p+37  restricted to this character type = game_hash("townsfolk"), ...

WORLDTAG (1A0FF55D) lists the zones in index order, each as a length-prefixed
name, the zone body, then its length-prefixed source .tag path. The count
matches the blockmap .txt's "Zones: N" in all eight regions, and in region_01
the named zones line up with who stands in them: the Vykker Doc in zone 1
Doc_Interior, the jailed bosses in zone 5 jail_interior.

Names come only from the files: every printable run in the levels and .smh is
hashed, whole and per '|' segment. A group, tag or job whose name was never
shipped stays a hash. Character names come from the live catalogues
(at3catalogue.py) for the live columns, and from the existing spawntable for
the baseline Name column so the editor's labels do not change under it.

    python spawn_catalog.py --build                 regions whose inputs changed
    python spawn_catalog.py --build --force         every region
    python spawn_catalog.py --region 01 --check     report only, write nothing
    python spawn_catalog.py --region 01 --show      the live level as area > zone
"""
import argparse, binascii, bisect, csv, json, math, os, re, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gamehash
from spawn_prop import walk, u32, pos_of, NEXT
from whose_attachment import spawn_table

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGIONDATA = os.path.join(ROOT, "StrangerAT3", "RegionData")
PROPDIR = os.path.join(ROOT, "StrangerAT3", "PropPlacements")
STATE = os.path.join(REGIONDATA, "spawncatalogue_state.json")
REGIONS = ["00", "01", "02", "02a", "03", "04", "05", "06"]
VERSION = 2

NULL_ID = 0x2DFD1072
HASHED = 0x000B4265
SAME_SPOT = 0.05        # apply_spawns writes the CSV's floats verbatim

LEGACY = ["Slot", "Tag", "Hash", "Name", "X", "Y", "Z", "Yaw", "Job"]
DESCRIBE = ["Zone", "ZoneName", "Area", "Group", "GroupName", "GroupSize",
            "Script", "ScriptName", "ScriptKind", "Jobs", "JobNames", "JobScripts"]
SPAWN_COLS = LEGACY + DESCRIBE + ["LiveState", "LiveIndex", "LiveHash", "LiveName"]
LIVE_COLS = ["Live", "Slot", "Origin", "EditorAdd", "EditorClone", "Tag", "Hash", "Name",
             "X", "Y", "Z", "Yaw"] + DESCRIBE
JOB_COLS = ["Job", "Name", "Zone", "ZoneName", "Area", "Group", "GroupName", "Script",
            "ScriptName", "Points", "GuySlot", "GuyLive", "GuyTag", "GuyType", "X", "Y", "Z"]
ZONE_COLS = ["Zone", "Name", "Area", "Spawns", "Jobs"]

# ---------------------------------------------------------------------------
# hashing: gamehash.game_hash is exact but pure Python per character, and this
# hashes every printable run in three files. The same function through
# binascii: reflected CRC-32, init FFFFFFFF, no final xor, length byte last.
_FOLD = bytearray(range(256))
for _c in range(0x61, 0x7B):
    _FOLD[_c] = _c - 0x20
_FOLD[0x2F] = 0x5C
_FOLD = bytes(_FOLD)


def ghash(raw):
    """game_hash of a bytes string."""
    b = raw.translate(_FOLD) + bytes([len(raw) & 0xFF])
    return binascii.crc32(b, 0) ^ 0xFFFFFFFF


def _selftest():
    for path, want in gamehash.PAIRS:
        if ghash(path.encode("latin1")) != want:
            sys.exit("fast hash disagrees with gamehash.py on %r" % path)


WORLDTAG = ghash(b"WorldTag")
JOBTAG = ghash(b"JobTag")

# ---------------------------------------------------------------------------
PRINTABLE = re.compile(rb"[\x20-\x7E]{3,}")
TAGPATH = re.compile(rb"/data/levels/[A-Za-z0-9_]+/lm_[A-Za-z0-9_]+\.tag")
IDENT = re.compile(rb"[A-Za-z0-9_]+")


def harvest(*blobs):
    """hash -> string for every printable run, whole and per '|' segment."""
    out = {}
    for blob in blobs:
        for m in PRINTABLE.finditer(blob):
            s = m.group(0)
            out.setdefault(ghash(s), s)
            if b"|" in s:
                for part in s.split(b"|"):
                    if len(part) >= 3:
                        out.setdefault(ghash(part), part)
    return out


def paths(region):
    base = os.path.join(ROOT, "data", "bundles", "region_" + region)
    live = os.path.join(base, "lm_level_%s.lvl" % region)
    spawnbase = live + ".spawnsbak" if os.path.exists(live + ".spawnsbak") else live
    return {"base": spawnbase, "live": live,
            "smh": os.path.join(base, "lm_level_%s_blockmap.smh" % region),
            "edits": os.path.join(PROPDIR, "spawns_%s.csv" % region),
            "catalogue": os.path.join(REGIONDATA, "catalogue_%s.csv" % region),
            "global": os.path.join(REGIONDATA, "GlobalCatalogue.csv")}


def area_label(path):
    """/data/levels/Region_01/lm_town_01_1.tag -> town_01_1"""
    base = path.rsplit("/", 1)[-1]
    if base.endswith(".tag"):
        base = base[:-4]
    return base[3:] if base.startswith("lm_") else base


def read_zones(d, recs):
    wt = [s for s in recs if u32(d, s + 8) == HASHED and u32(d, s + 12) == WORLDTAG]
    if not wt:
        return []
    w = d[wt[0]:u32(d, wt[0] + NEXT)]
    zones = []
    for m in TAGPATH.finditer(w):
        p = m.start()
        if p < 4 or u32(w, p - 4) != len(m.group(0)):
            continue
        name = ""
        # the nearest length-prefixed identifier before the path is the zone's
        # name; the zone body between them holds floats and, for portals, a
        # polygon - never a run of identifier bytes with a matching prefix
        for q in range(p - 11, max(-1, p - 4 - 4000), -1):
            n = u32(w, q)
            if 3 <= n <= 96 and q + 4 + n <= p - 4 and IDENT.fullmatch(w[q + 4:q + 4 + n]):
                name = w[q + 4:q + 4 + n].decode()
                break
        path = m.group(0).decode()
        zones.append({"Zone": len(zones), "Name": name, "Area": area_label(path),
                      "AreaHash": ghash(m.group(0))})
    return zones


def read_spawns(d, recs):
    """Every spawn record, in spawn_table order - apply_spawns' slot numbering."""
    starts = sorted(recs)
    out = []
    for slot, (off, _h) in enumerate(spawn_table(d)):
        i = bisect.bisect_right(starts, off) - 1
        if i < 0:
            continue
        s = starts[i]
        e = u32(d, s + NEXT)
        if not (s <= off < e and e - s >= 132):
            continue
        q = pos_of(d, s) or struct.unpack_from("<3f", d, s + 61)
        m = struct.unpack_from("<9f", d, s + 25)
        out.append({"slot": slot, "s": s, "e": e, "tag": u32(d, s + 16), "zone": u32(d, s + 20),
                    "group": u32(d, s + 82), "script": u32(d, s + 92), "id2": u32(d, s + 96),
                    "area": u32(d, s + 100), "id3": u32(d, s + 108), "type": u32(d, s + 128),
                    "pos": tuple(q), "yaw": math.degrees(math.atan2(m[3], m[0])),
                    "mirror": u32(d, e - 6)})
    return out


def key(sp):
    return (sp["tag"], sp["id2"], sp["id3"])


def read_jobs(d, recs):
    out = []
    for s in recs:
        if u32(d, s + 8) != HASHED or u32(d, s + 12) != JOBTAG:
            continue
        e = u32(d, s + NEXT)
        n = u32(d, s + 88)
        p = s + 92 + n
        if n > 4000 or p + 41 > e:
            continue
        out.append({"hash": u32(d, s + 16), "zone": u32(d, s + 20),
                    "group": u32(d, s + 82), "points": d[s + 92:p].decode("latin1"),
                    "script": u32(d, p), "area": u32(d, p + 8),
                    "guy": u32(d, p + 32), "guytype": u32(d, p + 37), "pos": pos_of(d, s)})
    return out


def read_names(order):
    """Hash -> character name from the first of these files that has one."""
    out = {}
    for p in order:
        if not os.path.exists(p):
            continue
        with open(p, newline="", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                try:
                    h = int(r["Hash"], 16)
                except (KeyError, ValueError, TypeError):
                    continue
                if h not in out and (r.get("Name") or "").strip():
                    out[h] = r["Name"].strip()
    return out


def read_edits(path):
    """The Spawns Editor's saved diff: {slot: edit row}, [add rows], [clone rows]."""
    edits, adds, clones = {}, [], []
    if not os.path.exists(path):
        return edits, adds, clones
    with open(path, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            act = (r.get("Action") or "").strip().lower()

            def num(k):
                try:
                    return float((r.get(k) or "").strip())
                except ValueError:
                    return None
            row = {"slot": (r.get("Slot") or "").strip(), "hash": (r.get("Hash") or "").strip().upper(),
                   "pos": (num("X"), num("Y"), num("Z"))}
            if act == "edit" and row["slot"]:
                edits[row["slot"]] = row
            elif act == "add":
                adds.append(row)
            elif act == "clone":
                clones.append(row)
    return edits, adds, clones


def short_script(name):
    if not name:
        return ""
    if name.startswith("|"):
        return name.rstrip("|").rsplit("|", 1)[-1]
    base = name.replace("/", "\\").rsplit("\\", 1)[-1]
    return base[:-4] if base.lower().endswith(".foo") else base


def fnum(v):
    return str(round(v, 2))


# ---------------------------------------------------------------------------
def catalogue(region):
    P = paths(region)
    if not os.path.exists(P["base"]):
        return None
    bd = open(P["base"], "rb").read()
    ld = open(P["live"], "rb").read() if os.path.exists(P["live"]) else bd
    sd = open(P["smh"], "rb").read() if os.path.exists(P["smh"]) else b""
    brecs, _ = walk(bd)
    lrecs, _ = walk(ld)
    names = harvest(ld, bd, sd)

    def nm(h):
        s = names.get(h)
        return s.decode("latin1") if s is not None else ""

    zones = read_zones(ld, lrecs) or read_zones(bd, brecs)
    areas = {z["AreaHash"]: z["Area"] for z in zones}
    base = read_spawns(bd, brecs)
    live = read_spawns(ld, lrecs)
    jobs = read_jobs(ld, lrecs)
    legacy = read_names([os.path.join(REGIONDATA, "spawntable_%s.csv" % region), P["catalogue"], P["global"]])
    current = read_names([P["catalogue"], P["global"], os.path.join(REGIONDATA, "spawntable_%s.csv" % region)])
    edits, adds, clones = read_edits(P["edits"])

    # ---- which live record is each base slot ----
    by_key = {}
    for i, y in enumerate(live):
        by_key.setdefault(key(y), []).append(i)
    slot_live, live_slot = {}, {}
    for x in base:
        cands = [i for i in by_key.get(key(x), []) if i not in live_slot]
        if not cands:
            continue
        want = x["pos"]
        ed = edits.get(str(x["slot"]))
        if ed:
            want = tuple(v if v is not None else want[k] for k, v in enumerate(ed["pos"]))
        i = min(cands, key=lambda i: math.dist(live[i]["pos"], want))
        slot_live[x["slot"]] = i
        live_slot[i] = x["slot"]
    base_by_key = {key(x): x for x in base}

    # ---- the rest: the editor's adds and clones, by position ----
    live_add, live_clone = {}, {}
    free = [i for i in range(len(live)) if i not in live_slot]
    for n, a in enumerate(adds):
        if None in a["pos"]:
            continue
        hits = [i for i in free if i not in live_add and math.dist(live[i]["pos"], a["pos"]) <= SAME_SPOT
                and (not a["hash"] or "%08X" % live[i]["type"] == a["hash"])]
        if hits:
            live_add[hits[0]] = n
    for n, c in enumerate(clones):
        if None in c["pos"]:
            continue
        hits = [i for i in free if i not in live_add and i not in live_clone
                and math.dist(live[i]["pos"], c["pos"]) <= SAME_SPOT]
        if hits:
            live_clone[hits[0]] = n

    # ---- jobs, from the live level ----
    tag_live = {}
    for i, y in enumerate(live):
        tag_live.setdefault(y["tag"], []).append(i)
    jobs_by_live = {}
    for j in jobs:
        for i in tag_live.get(j["guy"], []):
            jobs_by_live.setdefault(i, []).append(j)
    group_size = {}
    for y in live:
        if y["group"] != NULL_ID:
            group_size[y["group"]] = group_size.get(y["group"], 0) + 1

    def zone_name(z):
        return zones[z]["Name"] if z < len(zones) else ""

    def describe(y, i):
        mine = jobs_by_live.get(i, []) if i is not None else []
        jscripts = []
        for j in mine:
            k = short_script(nm(j["script"])) or "%08X" % j["script"]
            if k not in jscripts:
                jscripts.append(k)
        sname = nm(y["script"]) if y["script"] != NULL_ID else ""
        return {
            "Zone": y["zone"], "ZoneName": zone_name(y["zone"]),
            "Area": areas.get(y["area"], "%08X" % y["area"]),
            "Group": "" if y["group"] == NULL_ID else "%08X" % y["group"],
            "GroupName": "" if y["group"] == NULL_ID else nm(y["group"]),
            "GroupSize": "" if y["group"] == NULL_ID else group_size.get(y["group"], 0),
            "Script": "" if y["script"] == NULL_ID else "%08X" % y["script"],
            "ScriptName": sname,
            "ScriptKind": "" if y["script"] == NULL_ID else ("inline" if sname.startswith("|") else
                                                            ("file" if sname else "?")),
            "Jobs": len(mine),
            "JobNames": "; ".join(nm(j["hash"]) or "%08X" % j["hash"] for j in mine),
            "JobScripts": "; ".join(jscripts),
        }

    def changes(x, y):
        out = []
        if x["type"] != y["type"]:
            out.append("character")
        if math.dist(x["pos"], y["pos"]) > SAME_SPOT:
            out.append("position")
        for f, label in (("zone", "zone"), ("group", "group"), ("script", "script")):
            if x[f] != y[f]:
                out.append(label)
        return out

    stats = {"base": len(base), "live": len(live), "zones": len(zones), "jobs": len(jobs),
             "groups": len(group_size), "scripts": 0, "scripts_named": 0, "mirror_ok": 0,
             "zone_ok": 0, "area_ok": 0, "job_area_ok": 0, "slots_found": len(slot_live),
             "adds": len(live_add), "clones": len(live_clone), "outside": 0,
             "edit_adds": len(adds), "edit_clones": len(clones)}

    # ---- live rows ----
    lrows = []
    for i, y in enumerate(live):
        if y["script"] != NULL_ID:
            stats["scripts"] += 1
            stats["scripts_named"] += bool(nm(y["script"]))
        stats["mirror_ok"] += (y["mirror"] == y["script"])
        stats["zone_ok"] += y["zone"] < len(zones)
        stats["area_ok"] += y["area"] in areas
        if i in live_slot:
            x = base[[b["slot"] for b in base].index(live_slot[i])]
            ch = changes(x, y)
            edited = str(live_slot[i]) in edits
            if not ch:
                origin = "vanilla"
            elif edited:
                origin = "edited in the Spawns Editor: " + ", ".join(ch)
            else:
                origin = "changed outside the Spawns Editor: " + ", ".join(ch)
        elif i in live_add:
            origin = "added in the Spawns Editor"
        elif i in live_clone:
            src = base_by_key.get(key(y))
            origin = "cloned in the Spawns Editor" + (" from slot %d" % src["slot"] if src else "")
        elif key(y) in base_by_key:
            origin = "copy of slot %d, not from the Spawns Editor" % base_by_key[key(y)]["slot"]
            stats["outside"] += 1
        else:
            origin = "not from the Spawns Editor"
            stats["outside"] += 1
        row = {"Live": i, "Slot": live_slot.get(i, ""), "Origin": origin,
               "EditorAdd": live_add.get(i, ""), "EditorClone": live_clone.get(i, ""),
               "Tag": "%08X" % y["tag"], "Hash": "%08X" % y["type"], "Name": current.get(y["type"], ""),
               "X": fnum(y["pos"][0]), "Y": fnum(y["pos"][1]), "Z": fnum(y["pos"][2]), "Yaw": fnum(y["yaw"])}
        row.update(describe(y, i))
        lrows.append(row)

    # ---- base slot rows: baseline from the base, description from the live level ----
    rows = []
    for x in base:
        i = slot_live.get(x["slot"])
        row = {"Slot": x["slot"], "Tag": "%08X" % x["tag"], "Hash": "%08X" % x["type"],
               "Name": legacy.get(x["type"], ""),
               "X": fnum(x["pos"][0]), "Y": fnum(x["pos"][1]), "Z": fnum(x["pos"][2]),
               "Yaw": fnum(x["yaw"]), "Job": "n" if x["script"] == NULL_ID else "y"}
        if i is None:
            row.update(describe(x, None))
            row.update({"LiveState": "not in the live level", "LiveIndex": "", "LiveHash": "", "LiveName": ""})
        else:
            y = live[i]
            row.update(describe(y, i))
            row.update({"LiveState": lrows[i]["Origin"], "LiveIndex": i,
                        "LiveHash": "%08X" % y["type"], "LiveName": current.get(y["type"], "")})
        rows.append(row)

    # ---- jobs + zones ----
    jrows = []
    zone_jobs = {}
    for j in jobs:
        stats["job_area_ok"] += j["area"] in areas
        zone_jobs[j["zone"]] = zone_jobs.get(j["zone"], 0) + 1
        q = j["pos"] or (0.0, 0.0, 0.0)
        guy = j["guy"]
        on = tag_live.get(guy, [])
        jrows.append({
            "Job": "%08X" % j["hash"], "Name": nm(j["hash"]), "Zone": j["zone"],
            "ZoneName": zone_name(j["zone"]), "Area": areas.get(j["area"], "%08X" % j["area"]),
            "Group": "" if j["group"] == NULL_ID else "%08X" % j["group"],
            "GroupName": "" if j["group"] == NULL_ID else nm(j["group"]),
            "Script": "%08X" % j["script"], "ScriptName": nm(j["script"]),
            "Points": j["points"],
            "GuySlot": " ".join(str(live_slot[i]) for i in on if i in live_slot),
            "GuyLive": " ".join(str(i) for i in on),
            "GuyTag": "" if guy == NULL_ID else "%08X" % guy,
            "GuyType": "" if j["guytype"] == NULL_ID else (nm(j["guytype"]) or "%08X" % j["guytype"]),
            "X": fnum(q[0]), "Y": fnum(q[1]), "Z": fnum(q[2]),
        })
    zone_spawns = {}
    for y in live:
        zone_spawns[y["zone"]] = zone_spawns.get(y["zone"], 0) + 1
    zrows = [{"Zone": z["Zone"], "Name": z["Name"], "Area": z["Area"],
              "Spawns": zone_spawns.get(z["Zone"], 0), "Jobs": zone_jobs.get(z["Zone"], 0)}
             for z in zones]
    return {"rows": rows, "live": lrows, "jobs": jrows, "zones": zrows, "stats": stats}


def baseline_diff(region, rows):
    """Legacy-column differences against the spawntable already on disk."""
    p = os.path.join(REGIONDATA, "spawntable_%s.csv" % region)
    if not os.path.exists(p):
        return None
    with open(p, newline="", encoding="utf-8-sig") as f:
        old = {r["Slot"]: r for r in csv.DictReader(f)}
    diffs = []
    new = {str(r["Slot"]): r for r in rows}
    for slot in sorted(set(old) | set(new), key=lambda x: int(x)):
        o, n = old.get(slot), new.get(slot)
        if o is None or n is None:
            diffs.append((slot, "row", "present" if o else "-", "present" if n else "-"))
            continue
        for k in LEGACY:
            if k == "Name":
                continue
            ov, nv = (o.get(k) or "").strip(), str(n[k])
            if k in ("X", "Y", "Z", "Yaw"):
                try:
                    if abs(float(ov) - float(nv)) <= 0.011:
                        continue
                except ValueError:
                    pass
            elif ov.upper() == nv.upper():
                continue
            diffs.append((slot, k, ov, nv))
    return diffs


def write_csv(path, cols, rows):
    tmp = path + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    os.replace(tmp, path)


def input_state(region):
    """Everything a catalogue is read from. Any change rebuilds it."""
    st = {"version": VERSION}
    for label, p in paths(region).items():
        if os.path.exists(p):
            s = os.stat(p)
            st[label] = [os.path.basename(p), s.st_size, s.st_mtime_ns]
    return st


def show(region, cat):
    print("region_%s - %d spawns in the live level" % (region, len(cat["live"])))
    area = zone = None
    for r in sorted(cat["live"], key=lambda r: (r["Area"], r["Zone"], r["GroupName"] or r["Group"], r["Live"])):
        if r["Area"] != area:
            area, zone = r["Area"], None
            print("\n  %s" % area)
        if r["Zone"] != zone:
            zone = r["Zone"]
            print("    zone %-3d %s" % (zone, r["ZoneName"]))
        grp = r["GroupName"] or r["Group"] or "-"
        slot = "slot %s" % r["Slot"] if r["Slot"] != "" else "live %s" % r["Live"]
        print("      %-9s %-24s group %-20s script %-32s jobs %-28s %s"
              % (slot, (r["Name"] or r["Hash"])[:24], grp[:20],
                 short_script(r["ScriptName"])[:32] or "-", (r["JobScripts"] or "-")[:28],
                 "" if r["Origin"] == "vanilla" else "[" + r["Origin"] + "]"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--region", action="append")
    ap.add_argument("--check", action="store_true", help="report only, write nothing")
    ap.add_argument("--show", action="store_true", help="print the live level as area > zone")
    ap.add_argument("--force", action="store_true",
                    help="rebuild unchanged regions, and write even when the baseline columns differ")
    a = ap.parse_args()
    if not (a.build or a.check or a.show):
        sys.exit(__doc__)
    _selftest()

    regions = a.region or REGIONS
    state = {}
    if os.path.exists(STATE):
        try:
            state = json.load(open(STATE, encoding="utf-8"))
        except (OSError, ValueError):
            state = {}

    changed = False
    for region in regions:
        inputs = input_state(region)
        if a.build and not (a.check or a.show or a.force) and state.get(region) == inputs \
                and os.path.exists(os.path.join(REGIONDATA, "spawnlive_%s.csv" % region)):
            print("region_%s: unchanged - skipped" % region)
            continue
        cat = catalogue(region)
        if cat is None:
            print("region_%s: no level file" % region)
            continue
        st = cat["stats"]
        print("region_%s: base %d slots, live %d spawns (%d slots found, %d editor adds of %d, "
              "%d editor clones of %d, %d from elsewhere) | %d zones, %d jobs, %d groups | "
              "zones ok %d, areas ok %d, scripts named %d/%d, script copy at len-6 %d/%d, job layout %d/%d"
              % (region, st["base"], st["live"], st["slots_found"], st["adds"], st["edit_adds"],
                 st["clones"], st["edit_clones"], st["outside"], st["zones"], st["jobs"], st["groups"],
                 st["zone_ok"], st["area_ok"], st["scripts_named"], st["scripts"], st["mirror_ok"],
                 st["live"], st["job_area_ok"], st["jobs"]))
        if a.show:
            show(region, cat)
        diffs = baseline_diff(region, cat["rows"])
        if diffs is None:
            print("   baseline: no previous spawntable")
        elif diffs:
            print("   baseline: %d difference(s) from the spawntable on disk" % len(diffs))
            for dd in diffs[:10]:
                print("      slot %s %s: %r -> %r" % dd)
        else:
            print("   baseline: legacy columns identical to the spawntable on disk")
        if a.check or not a.build:
            continue
        if diffs and not a.force:
            print("   REFUSED - the Spawns Editor's saved edits are keyed to that baseline; "
                  "re-run with --force once the differences are understood")
            continue
        p = os.path.join(REGIONDATA, "spawntable_%s.csv" % region)
        if os.path.exists(p) and not os.path.exists(p + ".prebuild"):
            with open(p, "rb") as fi, open(p + ".prebuild", "wb") as fo:
                fo.write(fi.read())
        write_csv(p, SPAWN_COLS, cat["rows"])
        write_csv(os.path.join(REGIONDATA, "spawnlive_%s.csv" % region), LIVE_COLS, cat["live"])
        write_csv(os.path.join(REGIONDATA, "spawnjobs_%s.csv" % region), JOB_COLS, cat["jobs"])
        write_csv(os.path.join(REGIONDATA, "spawnzones_%s.csv" % region), ZONE_COLS, cat["zones"])
        state[region] = input_state(region)
        changed = True
        print("   written: spawntable, spawnlive, spawnjobs, spawnzones")
    if changed:
        with open(STATE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=1)


if __name__ == "__main__":
    main()
