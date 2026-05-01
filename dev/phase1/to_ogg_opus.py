#!/usr/bin/env python3
"""
Convert .opus_raw (receive_opus.py の出力) を OGG Opus コンテナ (.ogg) に変換する。

依存なし -- 純粋 Python で OGG ページを組み立てる。
出力ファイルは VLC / Windows Media Player / ffplay 等で再生可能。

Usage:
  python to_ogg_opus.py confbridge_20260501_120000.opus_raw
  python to_ogg_opus.py confbridge_20260501_120000.opus_raw --out output.ogg
"""

import struct
import sys
import argparse

SAMPLE_RATE   = 48000
CHANNELS      = 1
PRE_SKIP      = 312   # Opus 仕様の標準 pre-skip 値
SERIAL_NUMBER = 0x4F50_5553  # "OPUS" の ASCII コード

FILE_MAGIC    = b"OPSR"


# ── OGG CRC-32 ────────────────────────────────────────────────────────────────
# OGG が使う CRC は標準 CRC-32 と多項式が異なる (0x04c11db7)

_CRC_TABLE = []
for i in range(256):
    r = i << 24
    for _ in range(8):
        r = ((r << 1) ^ 0x04c11db7) if (r & 0x8000_0000) else (r << 1)
    _CRC_TABLE.append(r & 0xFFFF_FFFF)


def _ogg_crc(data: bytes) -> int:
    crc = 0
    for b in data:
        crc = ((crc << 8) & 0xFFFF_FFFF) ^ _CRC_TABLE[(crc >> 24) ^ b]
    return crc


# ── OGG page builder ──────────────────────────────────────────────────────────

def _lacing(data_len: int) -> bytes:
    """Lacing values for a single packet (OGG segment table)."""
    segs = []
    while data_len >= 255:
        segs.append(255)
        data_len -= 255
    segs.append(data_len)
    return bytes(segs)


def ogg_page(
    payload: bytes,
    serial: int,
    seq: int,
    granule: int,
    header_type: int = 0,
) -> bytes:
    """Build a single OGG page containing one packet."""
    lace  = _lacing(len(payload))
    head  = struct.pack(
        "<4sBBqIIIB",
        b"OggS",       # capture pattern
        0,             # stream structure version
        header_type,   # header type flags
        granule,       # granule position (int64)
        serial,        # bitstream serial number
        seq,           # page sequence number
        0,             # CRC placeholder
        len(lace),     # number of segments
    )
    page_no_crc = head + lace + payload
    crc = _ogg_crc(page_no_crc)
    # Patch CRC into bytes 22-25
    return page_no_crc[:22] + struct.pack("<I", crc) + page_no_crc[26:]


# ── Opus header packets ───────────────────────────────────────────────────────

def opus_head(channels: int, pre_skip: int, sample_rate: int) -> bytes:
    """OpusHead packet (RFC 7845 §5.1)."""
    return struct.pack(
        "<8sBBHIhB",
        b"OpusHead",   # magic
        1,             # version
        channels,
        pre_skip,
        sample_rate,
        0,             # output gain
        0,             # channel mapping family (mono/stereo RTP)
    )


def opus_tags() -> bytes:
    """Minimal OpusTags packet (RFC 7845 §5.2)."""
    vendor = b"ConfBridgeMonitor PoC"
    return (
        b"OpusTags"
        + struct.pack("<I", len(vendor))
        + vendor
        + struct.pack("<I", 0)   # no user comments
    )


# ── Main conversion ───────────────────────────────────────────────────────────

def convert(input_path: str, output_path: str) -> int:
    # Read raw Opus frames
    frames = []
    with open(input_path, "rb") as f:
        magic = f.read(4)
        if magic != FILE_MAGIC:
            raise ValueError(f"Not an .opus_raw file (magic={magic!r})")
        while True:
            hdr = f.read(2)
            if not hdr:
                break
            (size,) = struct.unpack(">H", hdr)
            data = f.read(size)
            if len(data) < size:
                print(f"[warn] Truncated frame, stopping at {len(frames)} frames",
                      file=sys.stderr)
                break
            frames.append(data)

    if not frames:
        raise ValueError("No frames found in input file.")

    serial = SERIAL_NUMBER
    seq    = 0
    pages  = []

    # Page 0: OpusHead (beginning-of-stream)
    pages.append(ogg_page(
        opus_head(CHANNELS, PRE_SKIP, SAMPLE_RATE),
        serial, seq, granule=0, header_type=0x02,
    ))
    seq += 1

    # Page 1: OpusTags
    pages.append(ogg_page(
        opus_tags(),
        serial, seq, granule=0, header_type=0,
    ))
    seq += 1

    # Audio pages: one Opus frame per page
    # granule = cumulative decoded samples (pre_skip + frame samples)
    FRAME_SAMPLES = SAMPLE_RATE * 20 // 1000  # 960 samples @ 48kHz / 20ms
    granule = PRE_SKIP  # initial granule accounts for pre-skip

    for i, frame in enumerate(frames):
        granule += FRAME_SAMPLES
        is_last  = i == len(frames) - 1
        pages.append(ogg_page(
            frame,
            serial, seq, granule=granule,
            header_type=0x04 if is_last else 0,
        ))
        seq += 1

    with open(output_path, "wb") as f:
        for page in pages:
            f.write(page)

    duration_s = len(frames) * 0.020
    print(f"Converted {len(frames)} frames ({duration_s:.1f}s) -> {output_path}")
    return len(frames)


def main():
    parser = argparse.ArgumentParser(
        description=".opus_raw -> OGG Opus コンテナ変換 (依存なし)"
    )
    parser.add_argument("input", help=".opus_raw file from receive_opus.py")
    parser.add_argument("--out", help="Output .ogg path (default: input.ogg)")
    args = parser.parse_args()

    out = args.out or args.input.replace(".opus_raw", ".ogg")
    convert(args.input, out)


if __name__ == "__main__":
    main()
