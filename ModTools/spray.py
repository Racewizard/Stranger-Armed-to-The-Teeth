r"""Custom sprays: mint a collectable spawner record from a Spray Designer definition.

A collectable spawner is a 43-byte kind-7 record:

    +0   12 bytes  header - identical on all 19 retail spawners
    +12  hash      the collectable it spawns
    +16  uint32    how many
    +20  float  +24 byte  +25 byte  +26 byte  +27 float  +31 float  +35 float  +39 float
                   UNNAMED on purpose - what they do is for testers to find out

The launcher sends a spray in place of a spawner hash:

    "m_onDeathCollectableSpawner": {"spray": {"collectable": "63CB6FAD", "count": 5,
                                              "params": {"f20": "3", ..., "b26": "0"}}}

prepare() swaps each one for a hash and returns the records that must be
appended. The hash is CONTENT-ADDRESSED - game_hash of a path built from the
record's own bytes - so the same spray always gets the same hash: re-saving a
character does not mint a duplicate, and two characters with the same spray
share one record. Spawners embed no path, so rule 3 has nothing to contradict.

Never edits an existing spawner - 47188952 is shared by 29 characters.
"""
import math, struct, zlib

from gamehash import game_hash

BS = chr(92)
HEAD = bytes.fromhex("65420b0059e94a3e01000000")
FIELDS = ("m_onDamageCollectableSpawner", "m_onExhaustCollectableSpawner",
          "m_onDeathCollectableSpawner", "m_onSteefRamAliveCollectableSpawner",
          "m_onStrangerRamAliveCollectableSpawner", "m_onSteefRamDeadCollectableSpawner",
          "m_onStrangerRamDeadCollectableSpawner")
FLOATS = (("f20", 20), ("f27", 27), ("f31", 31), ("f35", 35), ("f39", 39))
BYTES = (("b24", 24), ("b25", 25), ("b26", 26))


class SprayError(ValueError):
    pass


def desc_of(sp):
    """The 43-byte record for one definition. Raises SprayError on bad input."""
    try:
        coll = int(str(sp["collectable"]), 16)
        n = int(sp["count"])
    except (KeyError, TypeError, ValueError):
        raise SprayError("a spray needs a collectable hash and a whole-number count")
    if not 1 <= n <= 100:
        raise SprayError("spray count must be 1..100, got %d" % n)
    p = sp.get("params") or {}
    d = bytearray(43)
    d[:12] = HEAD
    struct.pack_into("<II", d, 12, coll, n)
    for k, o in FLOATS:
        try:
            x = float(p[k])
        except (KeyError, TypeError, ValueError):
            raise SprayError("spray %s needs a number, got %r" % (k, p.get(k)))
        if not math.isfinite(x):
            raise SprayError("spray %s must be finite" % k)
        struct.pack_into("<f", d, o, x)
    for k, o in BYTES:
        try:
            x = int(str(p[k]))
        except (KeyError, TypeError, ValueError):
            raise SprayError("spray %s needs a whole number, got %r" % (k, p.get(k)))
        if not 0 <= x <= 255:
            raise SprayError("spray %s must be 0..255, got %d" % (k, x))
        d[o] = x
    return bytes(d)


def hash_of(desc):
    return game_hash(BS + "data" + BS + "prefs" + BS + "Collectables" + BS + "Spawners" + BS +
                     "AT3_spray_%08X.txt" % (zlib.crc32(desc) & 0xFFFFFFFF))


def prepare(edits, known, lookup=None):
    """Replace every spray definition in `edits` with its hash.

    Returns {hash: (field, desc, collectable)} for EVERY spray, new or not;
    the caller appends the ones its target region lacks. `lookup(h)` returns
    an existing record's desc (or None) and guards against a hash collision
    with some unrelated record. Adds new hashes to `known` so field
    validation accepts them.
    """
    out = {}
    for f in FIELDS:
        v = edits.get(f)
        if not isinstance(v, dict):
            continue
        sp = v.get("spray", v)
        d = desc_of(sp)
        coll = struct.unpack_from("<I", d, 12)[0]
        if coll not in known:
            raise SprayError("%s: collectable %08X is not a record in this install" % (f, coll))
        h = hash_of(d)
        if h in known and lookup:
            have = lookup(h)
            if have is not None and bytes(have) != d:
                raise SprayError("%s: minted hash %08X collides with a different record" % (f, h))
        known.add(h)
        edits[f] = "%08X" % h
        out[h] = (f, d, coll)
    return out


def record(h, desc):
    return dict(kind=7, hash=h, flags=0, desc=desc, s2=b"", s3=b"", c2=0, c3=0)


def describe(desc):
    coll, n = struct.unpack_from("<II", desc, 12)
    fl = " ".join("%s=%g" % (k, struct.unpack_from("<f", desc, o)[0]) for k, o in FLOATS)
    by = " ".join("%s=%d" % (k, desc[o]) for k, o in BYTES)
    return "%08X x%d  %s %s" % (coll, n, fl, by)
