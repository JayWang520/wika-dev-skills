#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Esafenet (亿赛通 CDG) whole-file container: identify / recover-pad / decrypt."""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

MAGIC = bytes.fromhex("e0a891e7d8f205ac")
HEADER_SIZE = 4096
PAD_SIZE = 512
NAME_OFFSET = 88
SIZE_OFFSET = 16


def die(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    raise SystemExit(code)


def load(path: Path) -> bytes:
    if not path.is_file():
        die(f"file not found: {path}")
    return path.read_bytes()


def parse_header(data: bytes) -> dict:
    if len(data) < HEADER_SIZE:
        die("file shorter than 4096-byte header")
    if data[:8] != MAGIC:
        die(f"not Esafenet magic (got {data[:8].hex()}, want {MAGIC.hex()})")
    orig_size = int.from_bytes(data[SIZE_OFFSET:SIZE_OFFSET + 8], "little")
    hdr_size = int.from_bytes(data[12:16], "little")
    name = data[NAME_OFFSET:NAME_OFFSET + 32].split(b"\x00", 1)[0].decode("ascii", "replace")
    body = data[HEADER_SIZE:]
    return {
        "magic": data[:8].hex(),
        "header_size": hdr_size,
        "orig_size": orig_size,
        "product": name,
        "file_size": len(data),
        "body_size": len(body),
        "body": body,
    }


def cmd_identify(args: argparse.Namespace) -> None:
    data = load(Path(args.file))
    head = data[:8]
    result = {
        "path": str(args.file),
        "size": len(data),
        "is_esafenet": head == MAGIC,
        "magic": head.hex(),
    }
    if head == MAGIC:
        info = parse_header(data)
        result.update(
            {
                "product": info["product"],
                "header_size": info["header_size"],
                "orig_size": info["orig_size"],
                "body_size": info["body_size"],
                "size_ok": info["body_size"] == info["orig_size"],
            }
        )
    elif data[:2] == b"PK":
        result["hint"] = "looks like ZIP/DOCX/XLSX (already plaintext)"
    elif data[:5] == b"%PDF-":
        result["hint"] = "looks like PDF (already plaintext)"
    else:
        result["hint"] = "unknown container"
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_recover_pad(args: argparse.Namespace) -> None:
    plain = load(Path(args.plain))
    enc = load(Path(args.encrypted))
    info = parse_header(enc)
    body = info["body"]
    if len(plain) != len(body):
        die(f"plain size {len(plain)} != encrypted body {len(body)}")
    ks = bytes(a ^ b for a, b in zip(body, plain))
    pad = ks[:PAD_SIZE]
    mismatches = 0
    for off in range(0, len(ks), PAD_SIZE):
        chunk = ks[off : off + PAD_SIZE]
        if chunk != pad[: len(chunk)]:
            mismatches += 1
    roundtrip = bytes(p ^ pad[i % PAD_SIZE] for i, p in enumerate(body)) == plain
    out = Path(args.output) if args.output else Path(args.plain).with_suffix(".esa-pad.bin")
    out.write_bytes(pad)
    report = {
        "pad_file": str(out),
        "pad_size": PAD_SIZE,
        "period_ok": mismatches == 0,
        "mismatch_chunks": mismatches,
        "roundtrip_ok": roundtrip,
        "pad_hex": pad.hex(),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if mismatches or not roundtrip:
        die("recovered pad failed validation; do not use it")


def sniff(data: bytes) -> str | None:
    if data[:5] == b"%PDF-":
        return "pdf"
    if data[:2] == b"PK":
        return "zip"
    if data[:8] == bytes.fromhex("d0cf11e0a1b11ae1"):
        return "ole"
    return None


def decrypt_bytes(data: bytes, pad: bytes) -> bytes:
    if len(pad) != PAD_SIZE:
        die(f"pad must be {PAD_SIZE} bytes, got {len(pad)}")
    info = parse_header(data)
    body = info["body"]
    plain = bytes(p ^ pad[i % PAD_SIZE] for i, p in enumerate(body))
    if info["orig_size"] and len(plain) != info["orig_size"]:
        die(f"decrypted length {len(plain)} != header orig_size {info['orig_size']}")
    return plain


def default_out_path(src: Path) -> Path:
    name = src.name
    for marker in (".encrypted", ".esafenet", ".enc"):
        if name.endswith(marker):
            return src.with_name(name[: -len(marker)] + ".decrypted" + src.suffix)
    return src.with_name(src.stem + ".decrypted" + src.suffix)


def cmd_decrypt(args: argparse.Namespace) -> None:
    pad = load(Path(args.pad))
    out_dir = Path(args.out_dir) if args.out_dir else None
    results = []
    for item in args.files:
        src = Path(item)
        data = load(src)
        plain = decrypt_bytes(data, pad)
        if out_dir:
            out_dir.mkdir(parents=True, exist_ok=True)
            out = out_dir / default_out_path(src).name
        elif args.output and len(args.files) == 1:
            out = Path(args.output)
        else:
            out = default_out_path(src)
        out.write_bytes(plain)
        kind = sniff(plain)
        entry = {
            "input": str(src),
            "output": str(out),
            "size": len(plain),
            "type": kind,
        }
        if kind == "zip":
            try:
                with zipfile.ZipFile(out) as zf:
                    bad = zf.testzip()
                    entry["zip_entries"] = len(zf.namelist())
                    entry["zip_ok"] = bad is None
            except zipfile.BadZipFile:
                entry["zip_ok"] = False
        results.append(entry)
    print(json.dumps(results, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="esafenet", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    i = sub.add_parser("identify", help="check whether a file is Esafenet-encrypted")
    i.add_argument("file")
    i.set_defaults(func=cmd_identify)

    r = sub.add_parser("recover-pad", help="recover 512-byte XOR pad from known plaintext pair")
    r.add_argument("plain")
    r.add_argument("encrypted")
    r.add_argument("-o", "--output", help="pad output path (default: <plain>.esa-pad.bin)")
    r.set_defaults(func=cmd_recover_pad)

    d = sub.add_parser("decrypt", help="decrypt Esafenet file(s) with a recovered pad")
    d.add_argument("pad", help="512-byte pad file from recover-pad")
    d.add_argument("files", nargs="+", help="encrypted file(s)")
    d.add_argument("-o", "--output", help="output path (single input only)")
    d.add_argument("--out-dir", help="output directory (batch)")
    d.set_defaults(func=cmd_decrypt)
    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
