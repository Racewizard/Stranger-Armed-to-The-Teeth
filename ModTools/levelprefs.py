"""Read and edit each region's LevelPrefs: sky light, fog, and ambience.

WHERE IT LIVES
--------------
LevelPrefs is serialized inside `lm_level_XX.lvl` - the same file spawnswap.py
edits. Originally found by hashing the cloud-shadow texture
(`/data/textures/sky/cloudshadow.tga` -> 0xCDBE0B18, the value of the
`m_cloudShadowName` hashref) and searching for it.

A region holds **more than one** LevelPrefs: one per localized environment,
blended over `m_lerpTime`. Buzzardton has 33, Last Legs 5, Gizzard Gulch 2,
the rest 1. Enumeration therefore anchors on `heightFogColor` instead, which is
byte-identical in every set (the cloudshadow hash is not - region_00 uses a
different texture and was missed by that anchor).

SERIALIZED != STRUCT LAYOUT
---------------------------
Fields are written in *registration* order with natural widths, not at the
struct offsets that fielddump.py reports. Decoding at struct offsets produces
garbage (ambientShadow came out as 1e25 for some regions).

**Bools are 4 bytes in this record**, unlike the ammo/bolt prefs records where
a bool is 1 unpadded byte (see GAME_DATA_FORMAT.md). Confirmed by
m_allowFreeMovement and m_cloudShadowEnabled both reading as clean 4-byte 1s
and by every following field then landing correctly.

The whole layout was validated by reading it out across all 7 regions: colors
land in 0..1 RGBA, fog distances are sane and ordered, maxHunters is exactly
100, and the three sky texture hashes land where 8 leading floats predict.

SHARES THE .lvl WITH spawnswap.py
---------------------------------
Both tools edit `lm_level_XX.lvl`. spawnswap.py restores from its own `.at3bak`
before every apply, so running it AFTER an env edit silently reverts the env
edit. This tool therefore keeps a separate `.envbak`. If you use both, re-apply
the env change after any spawnswap run.

Usage:
    python levelprefs.py show [region]
    python levelprefs.py set <region> <field> <value>       # scalar
    python levelprefs.py set <region> fogColor r g b a      # color
    python levelprefs.py revert <region>
"""
import os, struct, shutil, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGIONS = ["00", "01", "02", "02a", "03", "04", "05", "06"]
NAMES = {"00": "Tutorial", "01": "Gizzard Gulch", "02": "Buzzardton", "02a": "Buzzardton (b)",
         "03": "Mongo Valley", "04": "Wolvark Docks", "05": "Last Legs",
         "06": "Sekto Springs Dam"}
CLOUDSHADOW_HASH = 0xCDBE0B18

# A region can hold MANY LevelPrefs - one per localized environment, blended
# with m_lerpTime. Buzzardton has 33, Last Legs 5, Gizzard Gulch 2, most 1.
# m_cloudShadowName is not a reliable anchor because some sets use a different
# texture (region_00 has none), but heightFogColor is byte-identical in every
# set found so far, so it is the signature used to enumerate them. It sits 28
# bytes before the cloudShadowName field.
HEIGHTFOGCOLOR_SIG = struct.pack("<4f", 0.31372549, 0.43137255, 0.31372549, 1.0)
SIG_TO_ANCHOR = 28

# offset from the cloudShadowName hash -> (name, kind)
# kind: f=float, i=int, b=bool32, h=hash, c=color(4 floats)
LEVEL = [
    (-84, "allowFreeMovement", "b"),
    (-80, "reflectionMapName", "h"),
    (-76, "fogColor", "c"),
    (-60, "fogStart", "f"),
    (-56, "fogEnd", "f"),
    (-52, "dofDistance", "f"),
    (-48, "dofRange", "f"),
    (-44, "lerpTime", "f"),
    (-40, "heightFogXYDistToMaxFog", "f"),
    (-36, "heightFogDepthToMaxFog", "f"),
    (-32, "heightFogHeight", "f"),
    (-28, "heightFogColor", "c"),
    (-12, "ambientShadow", "f"),
    (-8, "selfShadow", "f"),
    (-4, "maxHunters", "i"),
    (0, "cloudShadowName", "h"),
    (4, "cloudShadowEnabled", "b"),
    (8, "cloudShadowStrength", "f"),
    (12, "cloudShadowRot", "f"),
    (16, "cloudShadowSpeed", "f"),
    (20, "cloudShadowTiling", "f"),
    (24, "cloudShadowSingleColorScale", "f"),
    (28, "distantSingleLightViewColor", "c"),
    (44, "distortionScale", "f"),
    (48, "glareStartFade", "f"),
    (52, "glareEndFade", "f"),
    (56, "transFadeOutOverrideStart", "f"),
    (60, "transFadeOutOverrideEnd", "f"),
]

SKY_BASE = 64          # SkyParams begins here, relative to the anchor
SKY = [
    (0, "skyStretch", "f"),
    (4, "degreesFullFog", "f"),
    (8, "degreesNoFog", "f"),
    (12, "cloudParallax1", "f"),
    (16, "cloudParallax2", "f"),
    (20, "cloudTiling1", "f"),
    (24, "cloudTiling2", "f"),
    (28, "cloudTiling3", "f"),
    (32, "texName1", "h"),
    (36, "texName2", "h"),
    (40, "texName3", "h"),
    # uvSpeed1/2/3 are vec2 (8 bytes each), so the colors start at +68
    (44, "uvSpeed1", "v2"),
    (52, "uvSpeed2", "v2"),
    (60, "uvSpeed3", "v2"),
    (68, "colorBase", "c"),
    (84, "colorTop", "c"),
    (100, "colorSun", "c"),
    (116, "colorBaseCloud", "c"),
    (132, "colorSunCloud", "c"),
    (148, "colorInvSunCloud", "c"),
    (164, "overrideFog", "b"),
    (168, "overrideFogColor", "c"),
    (184, "sunSpikeSizeMin", "f"),
    (188, "sunSpikeSizeMax", "f"),
    (192, "sunBlobSizeMin", "f"),
    (196, "sunBlobSizeMax", "f"),
    (200, "sunBlobColor1", "c"),
    (216, "sunBlobColor2", "c"),
    (232, "sunBlobIntensity", "f"),
    (236, "sunSpikeColor1", "c"),
    (252, "sunSpikeColor2", "c"),
    (268, "sunSpikeIntensity", "f"),
    (272, "sunBlobSpeed1", "f"),
    (276, "sunBlobSpeed2", "f"),
]

# SkyParams is 280 bytes serialized, so LevelPrefs resumes at anchor+64+280.
# Everything below exists ONLY in the region default (set 0): cross-checking
# with SkyParams signatures finds exactly one per region, so sky, water and the
# fades are per-REGION settings, not per-area like fog.
SKY_LEN = 280
TAIL = [
    (344, "baseMusicIndex", "i"),
    (348, "tensionMusicIndex", "i"),
    (352, "battleMusicIndex", "i"),
    (356, "waterMurkStrength", "f"),
    (360, "waterMurkMinStrength", "f"),
    (364, "waterMurkColor", "c"),
    (380, "surfaceSparkleNear", "f"),
    (384, "surfaceSparkleFar", "f"),
    (388, "surfaceSparkleRadius", "f"),
    (392, "surfaceSparkleDensity", "f"),
    (396, "surfaceSparkleVerticalOffset", "f"),
    (400, "surfaceSparkleColor", "c"),
    (416, "cloudShadowStartFade", "f"),
    (420, "cloudShadowEndFade", "f"),
    (424, "shadowMapStartFade", "f"),
    (428, "shadowMapEndFade", "f"),
    (432, "critterCuePrefs", "h"),
    (436, "gameControlZone", "i"),
]

FIELDS = {n: (o, k, False) for o, n, k in LEVEL}
FIELDS.update({n: (SKY_BASE + o, k, True) for o, n, k in SKY})
FIELDS.update({n: (o, k, True) for o, n, k in TAIL})


def lvl_path(region):
    return os.path.join(ROOT, "data", "bundles", f"region_{region}",
                        f"lm_level_{region}.lvl")


def _shape(d, c):
    """Does a LevelPrefs sit at this anchor? Judged by shape, not by constants.

    The old detector matched the heightFogColor byte signature. That silently
    MISSED three real sets whose heightFogColor differs slightly - including
    native_village_lt_area_01 (the sibling of _02/_03/_04) and two teal water
    areas in Wolvark Docks and Sekto Springs. Never anchor on a value that is
    merely usually constant.
    """
    try:
        r, g, b, a = struct.unpack_from("<4f", d, c - 76)
        if a != 1.0 or not all(0.0 <= v <= 1.0 for v in (r, g, b)):
            return False
        fs, fe = struct.unpack_from("<2f", d, c - 60)
        # A real environment has an actual fog range. All-zero fog is what the
        # non-environment records sharing this shape look like (weapon nodes).
        if not (fs == fs and fe == fe and 0.0 <= fs < fe <= 100000):
            return False
        hr, hg, hb, ha = struct.unpack_from("<4f", d, c - 28)
        if ha != 1.0 or not all(0.0 <= v <= 1.0 for v in (hr, hg, hb)):
            return False
        mh = struct.unpack_from("<I", d, c - 4)[0]
        # 100 in the region default, INT_MAX ("no limit") in every later set
        return mh <= 100000 or mh == 0x7FFFFFFF
    except Exception:
        return False


def anchors(d):
    """Every LevelPrefs set in the file, as cloudShadowName-relative anchors.

    A set is real if it carries an area name; the region default has none, so
    the lowest-offset candidate is admitted unconditionally.
    """
    cands = [c for c in range(120, len(d) - 40) if _shape(d, c)]
    out = set(c for c in cands if area_name(d, c))
    if cands:
        out.add(min(cands))
    return sorted(out)


def anchor(d):
    a = anchors(d)
    return a[0] if a else -1


def area_name(d, c):
    """The area a set applies to.

    Each LevelPrefs is preceded by a length-prefixed ASCII area name
    (<u32 len><bytes>), e.g. 'town_02_1_Tag_area_1', 'sewer_area_2',
    'catacombs'. This is what makes the sets individually meaningful: they are
    per-AREA environment overrides, not an anonymous list. Set 0 has no name -
    it is the region default.
    """
    start = c - 84
    for back in range(6, 80):
        p = start - back
        if p < 4:
            break
        ln = struct.unpack_from("<I", d, p)[0]
        if 3 <= ln <= 64 and p + 4 + ln <= start:
            raw = d[p + 4:p + 4 + ln]
            # Take names exactly as authored. One of Buzzardton's really is
            # '|catacombs' with a leading pipe - its length prefix says 10 and
            # it is the only candidate, so that is data, not a bad read. Do not
            # "fix" it by requiring a leading letter; that just loses the name.
            if all(32 <= ch < 127 for ch in raw):
                return raw.decode()
    return None


def read_field(d, c, off, kind):
    p = c + off
    if kind == "f":
        return round(struct.unpack_from("<f", d, p)[0], 5)
    if kind == "i":
        # signed: music indices and gameControlZone are -1 when unset
        return struct.unpack_from("<i", d, p)[0]
    if kind == "b":
        return struct.unpack_from("<I", d, p)[0]
    if kind == "h":
        return f"0x{struct.unpack_from('<I', d, p)[0]:08X}"
    if kind == "c":
        return tuple(round(x, 4) for x in struct.unpack_from("<4f", d, p))
    if kind == "v2":
        return tuple(round(x, 5) for x in struct.unpack_from("<2f", d, p))


def show(regions):
    for r in regions:
        p = lvl_path(r)
        if not os.path.exists(p):
            continue
        d = open(p, "rb").read()
        aa = anchors(d)
        if not aa:
            print(f"region_{r}: no LevelPrefs found")
            continue
        for n, c in enumerate(aa):
            nm = area_name(d, c) or "(region default)"
            print(f"\n=== region_{r} {NAMES.get(r,'')} - set {n}/{len(aa)}: {nm} ===")
            for off, name, kind in LEVEL:
                print(f"   {name:30} {read_field(d, c, off, kind)}")
            print("   -- SkyParams --")
            for off, name, kind in SKY:
                print(f"   {name:30} {read_field(d, c, SKY_BASE + off, kind)}")
            if n == 0:      # region-level only; later sets have no SkyParams
                print("   -- Water / sparkle / fades (region default only) --")
                for off, name, kind in TAIL:
                    print(f"   {name:30} {read_field(d, c, off, kind)}")


def backup(p):
    b = p + ".envbak"
    if not os.path.exists(b):
        shutil.copy2(p, b)
        print(f"pristine backup created: {os.path.basename(b)}")
    elif os.path.getsize(b) != os.path.getsize(p):
        sys.exit(f"REFUSING: {os.path.basename(b)} is a different size to the live "
                 f".lvl - it is from another copy of the game. Delete it to re-baseline.")
    return b


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cmd = sys.argv[1]

    if cmd == "show":
        show([sys.argv[2]] if len(sys.argv) > 2 else REGIONS)
        return

    if cmd == "revert":
        p = lvl_path(sys.argv[2])
        b = p + ".envbak"
        if not os.path.exists(b):
            sys.exit("no backup to revert from")
        shutil.copy2(b, p)
        print(f"reverted region_{sys.argv[2]} .lvl to pristine")
        return

    if cmd == "set":
        region, field = sys.argv[2], sys.argv[3]
        if field not in FIELDS:
            sys.exit(f"unknown field. known: {', '.join(sorted(FIELDS))}")
        off, kind, _ = FIELDS[field]
        p = lvl_path(region)
        backup(p)
        d = bytearray(open(p, "rb").read())
        aa = anchors(bytes(d))
        if not aa:
            sys.exit("no LevelPrefs anchor in that .lvl")
        args = sys.argv[4:]
        which = list(range(len(aa)))
        if "--all" in args:
            args.remove("--all")
        elif "--set" in args:
            j = args.index("--set")
            key = args[j + 1]
            if key.isdigit():
                which = [int(key)]
            else:
                names = [area_name(bytes(d), a) for a in aa]
                if key not in names:
                    sys.exit(f"no area '{key}'. known: " +
                             ", ".join(n for n in names if n))
                which = [names.index(key)]
            del args[j:j + 2]
        else:
            which = [0]
        for n in which:
            c = aa[n]
            before = read_field(bytes(d), c, off, kind)
            if kind == "c":
                vals = [float(x) for x in args[:4]]
                if len(vals) != 4:
                    sys.exit("a color needs 4 values: r g b a")
                struct.pack_into("<4f", d, c + off, *vals)
            elif kind == "f":
                struct.pack_into("<f", d, c + off, float(args[0]))
            else:
                struct.pack_into("<I", d, c + off, int(args[0], 0))
            print(f"region_{region} set {n} {field}: {before} -> "
                  f"{read_field(bytes(d), c, off, kind)}")
        open(p, "wb").write(bytes(d))
        return

    sys.exit(__doc__)


if __name__ == "__main__":
    main()
