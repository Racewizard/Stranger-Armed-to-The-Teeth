"""The .smb / .smh bundle container format, as far as it is understood.

HEADER
    .smb:  3A4B5C6D | 05 | <u32 len> | <bundle path> | <8 dwords> | BEEF1234
    .smh:  BEEF2B16 | 01 | <u32 content> | then exactly the same block

    The 8 dwords describe the .smb bundle:

        [0] sec1_size   [1] sec1_used
        [2] sec2_size   [3] sec3_size
        [4] sec2_used   [5] sec3_used
        [6] record_count
        [7] 2            (constant)

    sec1_size + sec2_size + sec3_size == the .smb file size, and record_count
    equals the number of records. Verified on regions 00, 01, 02 and 03.

RECORDS
    4D FA A7 7E | <u32 kind> | <record bytes>, run end to end.

INDEX TERMINATOR (.smh only)
    CAFED00D sits at exactly the offset the header's content field points to.
    Overwriting it makes the loader scan past the end of the index: the game
    hangs on a still frame, then crashes.

WHAT THIS COST TO LEARN
    Injection failed twice. First by destroying CAFED00D. Then by appending at
    the last non-zero byte instead of the true section-3 content end (5 bytes
    early), and by leaving record_count and the section sizes stale, so the
    loader read 1209 records and never saw the 1210th.
"""
import struct

MAGIC = struct.pack("<I", 0x4DFAA77E)
TERMINATOR = struct.pack("<I", 0xCAFED00D)
SMB_MAGIC = 0x3A4B5C6D
SMH_MAGIC = 0xBEEF2B16
BLOCK = 1024
SECT_ALIGN = 4096


def header_offset(d):
    """Where the 8-dword descriptor starts, and whether this is an .smh."""
    m = struct.unpack_from("<I", d, 0)[0]
    if m == SMH_MAGIC:
        base = 12                      # magic, version, content
    elif m == SMB_MAGIC:
        base = 0
    else:
        raise ValueError(f"unknown container magic {m:08X}")
    # base -> 3A4B5C6D | 05 | len | path
    ln = struct.unpack_from("<I", d, base + 8)[0]
    return base + 12 + ln, (m == SMH_MAGIC)


def read_desc(d):
    off, is_smh = header_offset(d)
    v = list(struct.unpack_from("<8I", d, off))
    return off, is_smh, v


def write_desc(buf, off, v):
    struct.pack_into("<8I", buf, off, *v)


def sections(v):
    return {"sec1": v[0], "sec1_used": v[1], "sec2": v[2], "sec3": v[3],
            "sec2_used": v[4], "sec3_used": v[5], "count": v[6]}


def content_end_smb(v):
    """Absolute offset where section 3's content ends - the append point."""
    return v[0] + v[2] + v[5]


def describe(d, label=""):
    off, is_smh, v = read_desc(d)
    s = sections(v)
    total = s["sec1"] + s["sec2"] + s["sec3"]
    return (f"{label} {'smh' if is_smh else 'smb'} file={len(d)} "
            f"sections={s['sec1']}+{s['sec2']}+{s['sec3']}={total} "
            f"{'OK' if total == len(d) or is_smh else 'MISMATCH'} "
            f"sec3_used={s['sec3_used']} count={s['count']}")
