#!/usr/bin/env python3
"""
Decode .opus_raw file saved by receive_opus.py into a WAV file.

Requires: pip install pyogg opuslib
  (or install libopus system library first)

Usage:
  python decode_opus_raw.py confbridge_20260501_120000.opus_raw
  python decode_opus_raw.py confbridge_20260501_120000.opus_raw --out output.wav
"""

import sys
import struct
import wave
import argparse
import ctypes
import ctypes.util

SAMPLE_RATE = 48000
CHANNELS    = 1
FRAME_MS    = 20
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000  # 960 samples per frame


def find_libopus():
    for name in ("opus", "libopus", "libopus.so.0", "libopus-0"):
        path = ctypes.util.find_library(name)
        if path:
            return path
    raise RuntimeError(
        "libopus not found. Install with:\n"
        "  Ubuntu/Debian: sudo apt install libopus0\n"
        "  Windows: download opus.dll and place it in the same directory"
    )


def decode_raw_file(input_path, output_path):
    libopus = ctypes.CDLL(find_libopus())

    # opus_decoder_create(sample_rate, channels, *error) -> decoder
    libopus.opus_decoder_create.restype  = ctypes.c_void_p
    libopus.opus_decoder_create.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_int)]

    # opus_decode(decoder, data, len, pcm, frame_size, decode_fec) -> samples
    libopus.opus_decode.restype  = ctypes.c_int
    libopus.opus_decode.argtypes = [
        ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int,
        ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
    ]

    libopus.opus_decoder_destroy.argtypes = [ctypes.c_void_p]

    err = ctypes.c_int(0)
    decoder = libopus.opus_decoder_create(SAMPLE_RATE, CHANNELS, ctypes.byref(err))
    if err.value != 0:
        raise RuntimeError(f"opus_decoder_create error: {err.value}")

    pcm_buf = (ctypes.c_int16 * (FRAME_SAMPLES * CHANNELS))()
    all_pcm = []

    with open(input_path, "rb") as f:
        magic = f.read(4)
        if magic != b"OPSR":
            raise ValueError(f"Not an .opus_raw file (magic={magic!r})")

        frame_count = 0
        while True:
            hdr = f.read(2)
            if not hdr:
                break
            (frame_len,) = struct.unpack(">H", hdr)
            frame_data   = f.read(frame_len)
            if len(frame_data) < frame_len:
                print(f"[warn] Truncated frame at {frame_count}", file=sys.stderr)
                break

            n = libopus.opus_decode(
                decoder,
                frame_data, len(frame_data),
                pcm_buf, FRAME_SAMPLES, 0,
            )
            if n < 0:
                print(f"[warn] Frame {frame_count}: decode error {n}", file=sys.stderr)
                continue

            all_pcm.extend(pcm_buf[:n * CHANNELS])
            frame_count += 1

    libopus.opus_decoder_destroy(decoder)

    with wave.open(output_path, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)  # int16
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(
            struct.pack(f"<{len(all_pcm)}h", *all_pcm)
        )

    duration = frame_count * FRAME_MS / 1000
    print(f"Decoded {frame_count} frames ({duration:.1f}s) -> {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Decode .opus_raw to WAV")
    parser.add_argument("input", help=".opus_raw file from receive_opus.py")
    parser.add_argument("--out", help="Output .wav (default: input.wav)")
    args = parser.parse_args()

    out = args.out or args.input.replace(".opus_raw", ".wav")
    decode_raw_file(args.input, out)


if __name__ == "__main__":
    main()
