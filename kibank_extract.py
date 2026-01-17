#!/usr/bin/env python3
"""
Extract Kilohearts .bank files (Phase Plant / Snap Heap / Multipass banks)
based on kibank's format (lib.rs + read.rs).

Usage:
  python kibank_extract.py MyBank.bank -o outdir
"""

from __future__ import annotations

import argparse
import os
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import List


# ---- Constants from lib.rs ----
FILE_ID = bytes([137, ord("k"), ord("H"), ord("s")])  # [137_u8, b'k', b'H', b's']
FORMAT_VERSION = b"Bank0001"
CORRUPTION_CHECK_BYTES = bytes([0x0D, 0x0A, 0x1A, 0x0A])

PATH_SEPARATOR = "/"  # inside bank; lib.rs uses char '/'

U64LE = struct.Struct("<Q")
LOC = struct.Struct("<QQQ")  # file_name_offset, data_offset, data_size


@dataclass(frozen=True)
class Location:
    name_off: int
    data_off: int
    data_size: int

    @property
    def data_end(self) -> int:
        return self.data_off + self.data_size


@dataclass(frozen=True)
class BankEntry:
    name_bytes: bytes
    loc: Location

    @property
    def is_dir(self) -> bool:
        return self.loc.data_size == 0

    @property
    def is_file(self) -> bool:
        return self.loc.data_size != 0

    def name_text(self) -> str:
        # Bank file names are typically ASCII/UTF-8; be tolerant:
        return self.name_bytes.decode("utf-8", errors="surrogateescape")


class BankReader:
    def __init__(self, path: Path):
        self.path = path
        self.fp = open(path, "rb")
        self.entries: List[BankEntry] = []
        self._parse()

    def close(self) -> None:
        try:
            self.fp.close()
        except Exception:
            pass

    def _read_exact(self, n: int) -> bytes:
        b = self.fp.read(n)
        if len(b) != n:
            raise IOError("Unexpected EOF while reading bank")
        return b

    def _read_u64(self) -> int:
        return U64LE.unpack(self._read_exact(8))[0]

    def _parse(self) -> None:
        # header
        if self._read_exact(len(FILE_ID)) != FILE_ID:
            raise ValueError("FILE_ID mismatch: not a Kilohearts .bank (or unsupported)")
        if self._read_exact(len(CORRUPTION_CHECK_BYTES)) != CORRUPTION_CHECK_BYTES:
            raise ValueError("CORRUPTION_CHECK_BYTES mismatch: file may be corrupted")
        if self._read_exact(len(FORMAT_VERSION)) != FORMAT_VERSION:
            raise ValueError("FORMAT_VERSION mismatch: unsupported bank version")

        location_count = self._read_u64()

        locations: List[Location] = []
        for _ in range(location_count):
            name_off, data_off, data_size = LOC.unpack(self._read_exact(LOC.size))
            locations.append(Location(int(name_off), int(data_off), int(data_size)))

        file_name_block_length = self._read_u64()
        file_name_block = self._read_exact(file_name_block_length)

        # resolve names
        entries: List[BankEntry] = []
        for loc in locations:
            if loc.name_off < 0 or loc.name_off >= file_name_block_length:
                raise ValueError("Name offset out of bounds in filename block")
            end = file_name_block.find(b"\x00", loc.name_off)
            if end == -1:
                # kibank read.rs allows reaching end if missing terminator
                end = file_name_block_length
            name = file_name_block[loc.name_off:end]
            entries.append(BankEntry(name, loc))

        # overlap/corruption check (matches read.rs intent)
        file_entries = sorted((e for e in entries if e.is_file), key=lambda e: e.loc.data_off)
        for a, b in zip(file_entries, file_entries[1:]):
            if a.loc.data_end > b.loc.data_off:
                raise ValueError(
                    f"Overlapping data ranges: {a.name_text()} overlaps {b.name_text()}"
                )

        self.entries = entries

    def read_file_bytes(self, entry: BankEntry) -> bytes:
        if not entry.is_file:
            return b""
        self.fp.seek(entry.loc.data_off)
        return self._read_exact(entry.loc.data_size)


def safe_join(base: Path, bank_rel: str) -> Path:
    """
    Convert a bank internal path (uses '/') into a safe path under base.
    Prevents path traversal (../) and absolute paths.
    """
    # Normalize separators and strip leading slashes
    rel = bank_rel.replace("\\", "/").lstrip("/")

    # Remove empty segments and '.' segments; reject '..'
    parts = []
    for p in rel.split("/"):
        if p in ("", "."):
            continue
        if p == "..":
            raise ValueError(f"Refusing path traversal entry: {bank_rel!r}")
        parts.append(p)

    out = base.joinpath(*parts)

    # Final safety: ensure resolved path is within base
    base_res = base.resolve()
    out_res = out.resolve()
    if base_res != out_res and base_res not in out_res.parents:
        raise ValueError(f"Refusing to write outside output dir: {bank_rel!r}")

    return out


def extract_bank(bank_path: Path, out_dir: Path, *, overwrite: bool = False) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    br = BankReader(bank_path)
    try:
        # First create directories explicitly present in the bank
        for e in br.entries:
            if e.is_dir:
                rel = e.name_text()
                target_dir = safe_join(out_dir, rel)
                target_dir.mkdir(parents=True, exist_ok=True)

        # Then extract files
        extracted = 0
        skipped = 0
        for e in br.entries:
            if not e.is_file:
                continue

            rel = e.name_text()
            target = safe_join(out_dir, rel)
            target.parent.mkdir(parents=True, exist_ok=True)

            if target.exists() and not overwrite:
                skipped += 1
                continue

            data = br.read_file_bytes(e)
            with open(target, "wb") as f:
                f.write(data)
            extracted += 1

        print(f"OK: extracted {extracted} files to: {out_dir}")
        if skipped:
            print(f"Note: skipped {skipped} existing files (use --overwrite to replace).")
    finally:
        br.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="Extract Kilohearts .bank files (Phase Plant banks).")
    ap.add_argument("bank", type=Path, help="Path to .bank file")
    ap.add_argument("-o", "--out", type=Path, default=None, help="Output directory")
    ap.add_argument("--overwrite", action="store_true", help="Overwrite existing files")
    args = ap.parse_args()

    bank_path: Path = args.bank
    if not bank_path.exists():
        ap.error(f"Bank file not found: {bank_path}")

    out_dir = args.out if args.out else bank_path.with_suffix("")  # default: BankName/
    extract_bank(bank_path, out_dir, overwrite=args.overwrite)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
