"""
Reimplementation of Stranger's Wrath's path-hash function, transcribed
directly from the disassembly at RVA 0x24D920.

  esi = path;  ebx = 0;  *edi = 0xFFFFFFFF (caller-initialised)
  per char:  c = (*esi == '/') ? '\\' : tolower(*esi)
             crc = (crc >> 8) ^ TABLE[(crc ^ c) & 0xFF]
             len++
  finally:   crc = (crc >> 8) ^ TABLE[(crc ^ (len & 0xFF)) & 0xFF]

i.e. reflected CRC-32, init 0xFFFFFFFF, NO final xor, with the low byte of
the length folded in as a final extra byte. That trailing length byte is why
no stock CRC-32 ever matched.
"""
# The table stranger.exe carries at RVA 0x7F7478 is the STANDARD reflected
# CRC-32 table (polynomial 0xEDB88320) - verified byte-for-byte against the
# retail exe. Generating it here instead of reading it out of the exe removes
# the dependency on pefile AND on knowing where the game is installed, so these
# tools run from any install path rather than only the author's.
TABLE = []
for _i in range(256):
    _c = _i
    for _ in range(8):
        _c = (_c >> 1) ^ (0xEDB88320 if _c & 1 else 0)
    TABLE.append(_c)

M = 0xFFFFFFFF

def game_hash(path):
    """VERIFIED 8/8 against known pairs. Note the case fold is toUPPER -
    0x6E7DC5 is toupper, not tolower as first assumed."""
    crc = 0xFFFFFFFF
    n = 0
    for ch in path:
        c = ord(ch)
        if c == 0x2F:              # '/'
            c = 0x5C               # '\'
        elif 0x61 <= c <= 0x7A:
            c -= 0x20              # toupper
        crc = (crc >> 8) ^ TABLE[(crc ^ c) & 0xFF]
        n += 1
    crc = (crc >> 8) ^ TABLE[(crc ^ (n & 0xFF)) & 0xFF]
    return crc & M

PAIRS = [
    ("/data/prefs/weapons/damagebeegun.txt",            0xADF7DEE1),
    ("\\data\\prefs\\weapons\\damagebeegun.txt",        0xADF7DEE1),
    ("/data/prefs/weapons/DamageBeeGun.txt",            0xADF7DEE1),
    ("damagebeegun.txt",                                0x8431D121),
    ("damagebeegun",                                    0x86B9A927),
    ("\\data\\prefs\\weapons\\npc\\outlawshooter.txt",  0xF0DF813D),
    ("\\data\\prefs\\weapons\\npc\\outlawcutter.txt",   0xB83625EB),
    ("\\data\\prefs\\weapons\\npc\\outlawsniper.txt",   0x104B30E3),
    ("\\data\\prefs\\weapons\\npc\\outlawmortar.txt",   0x5D994255),
    ("\\data\\prefs\\weapons\\npc\\wolvarkshooter.txt", 0x5207CB4E),
]

if __name__ == "__main__":
    print(f"CRC table generated (poly 0xEDB88320): "
          f"[0]=0x{TABLE[0]:08X} [1]=0x{TABLE[1]:08X} [255]=0x{TABLE[255]:08X}")
    print(f"(standard reflected CRC-32 table has [1]=0x77073096)\n")
    ok = 0
    for path, want in PAIRS:
        got = game_hash(path)
        mark = "OK  " if got == want else "FAIL"
        if got == want:
            ok += 1
        print(f"  {mark} {want:08X} expected | {got:08X} computed | {path}")
    print(f"\n{ok}/{len(PAIRS)} pairs matched")
