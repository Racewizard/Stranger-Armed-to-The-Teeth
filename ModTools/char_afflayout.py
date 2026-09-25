r"""Immunity and the character tail: m_affList, the four flags, the drops.

STATUS 2026-09-12 (second pass): the earlier "SOLVED - the affect block is
OPTIONAL, absence means immune" is WITHDRAWN. It was a misreading.

THE LAYOUT

    ANC+137            m_affList count N
    ANC+141 ...        N record hashes
    ANC+141+4N         m_respondsToDamageDynamite, ..SkunkBomb, ..SpiderBola, ..TrapFuzzle
    ANC+145+4N         m_collectableSpawnLimit, then the seven collectable spawners

It is char_fields.tail_layout(); this module only reports it.

57 of 75 characters have N = 0 - the old "layout A", where the four zero bytes
at ANC+137 are simply an empty list. The six former "layout B" characters
(gloktigi x2, shocktank, Elboze Freely, Meagly McGraw & Tiny, Splosives McGee
787 B) were never missing a block: their count is a small number and their
listed hashes are real records, so the old reader took the count for a spawn
limit and the hashes for spawners. Twelve more (Boilz Booty, Looten Duke,
Filthy Hands Floyd, Packrat, Giant Sleg, Fatty, Sekto's Machine...) resolved
no layout at all, which is why their flags and drops were disabled. With the
count honoured, all 75 resolve.

WHAT THE LIST HOLDS - the player's AMMO prefs, by path:

    sniperdart               ImmobilizeSpiderBola     ImmobilizeSkunkBomb
    ImmobilizeBolaBlast      TrapFuzzle / TrapFuzzleRabid
    DamageDynamite           DamageArmadillo          SendToChipmunk
    SendToHowlerPunk         ActivateHiveQueen(Charge)   + 3 unnamed

WHAT IT MEANS - NOT TESTED IN GAME. The evidence points at immunity:
sniperdart is listed on Fatty McBoomBoom, "meagly" (Lefty Lugnutz) and Elboze
Freely - exactly the three the player named as sniper-immune, plus gloktigi,
also named. SendToChipmunk is on the outlaw bosses the player called
chipmunk-immune. But it does not line up everywhere (shocktank is described as
fuzzle-immune and does not list TrapFuzzle - its fuzzle FLAG is 0 instead), so
"listed = immune" is a strong reading, not a result.

The flags keep their earlier meaning, which came from the player: 0 is
affected at zero efficiency (one frame), 1 normal. outlawNailer and outlawPyro
are the two with skunk = 0.

THE ANC+140 CRASH, revisited: ANC+140 is the top byte of the m_affList COUNT.
Writing 1 there makes the count 16777216 on a record that has none, and the
game reads that many hashes. That is a better explanation than either earlier
one.

LESSON: a signature of "small int + dwords that are real records" also matches
a LIST of real records. Validate a structure with its own count first.

    python char_afflayout.py
"""
import argparse, collections, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import char_anchor as CA
import char_fields as CF


def classify():
    import resolve_assets as RA
    from gamehash import game_hash
    h2p = {}
    for q in RA.harvest():
        h2p.setdefault(game_hash(q), q)
    rs, known = CA.roster()
    out = []
    for h, (nm, C, A, b) in rs.items():
        if not nm or A is None or CF.head_problem(b, A, known):
            continue
        ents, f, tail = CF.tail_layout(b, A, known)
        out.append((nm, h, ents, None if f is None else list(b[f:f + 4]), h2p))
    return out


def main():
    argparse.ArgumentParser().parse_args()
    rows = classify()
    print("%d characters with a valid front; tail resolved for %d"
          % (len(rows), sum(1 for r in rows if r[2] is not None)))
    print("   list lengths: %s" % dict(collections.Counter(len(r[2]) for r in rows if r[2] is not None)))
    seen = set()
    for nm, h, ents, flags, h2p in sorted(rows):
        if nm in seen:
            continue
        seen.add(nm)
        if ents is None:
            print("   %-28s %08X  UNRESOLVED" % (nm, h))
            continue
        names = [CF.AMMO_NAMES.get(e) or (h2p[e].replace("/", "\\").split("\\")[-1].rsplit(".", 1)[0]
                                         if e in h2p else "%08X" % e) for e in ents]
        print("   %-28s %08X  flags d/s/sp/f=%s  affList: %s" % (nm, h, flags, ", ".join(names) or "-"))


if __name__ == "__main__":
    main()
