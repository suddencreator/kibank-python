#!/usr/bin/env python3
"""
Create Kilohearts .bank files (Phase Plant / Snap Heap / Multipass banks)
based on kibank's format (lib.rs + write.rs).

Usage:
  python kibank_write.py INPUT_DIR OUTPUT.bank --name "My Bank" --author "Me" --description "..."

Notes:
- This writer preserves your folder tree exactly (Bass/Violin/etc).
- Directories are stored as entries with data_size=0.
- Paths inside the bank always use '/'.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Set, Tuple, Union


# ---- Constants from lib.rs ----
FILE_ID = bytes([137, ord("k"), ord("H"), ord("s")])  # b"\x89kHs"
FORMAT_VERSION = b"Bank0001"
CORRUPTION_CHECK_BYTES = bytes([0x0D, 0x0A, 0x1A, 0x0A])

PATH_SEPARATOR = "/"  # inside bank
METADATA_FILE_NAME = "index.json"
BACKGROUND_FILE_STEM = "background"  # background.png / background.jpg expected


U64LE = struct.Struct("<Q")
LOC = struct.Struct("<QQQ")  # file_name_offset, data_offset, data_size


@dataclass(frozen=True)
class DirEntry:
    rel_posix: str  # e.g. "Bass" or "Bass/Sub"


@dataclass(frozen=True)
class FileEntry:
    rel_posix: str          # e.g. "Bass/Arp1.phaseplant"
    abs_path: Optional[Path]  # None for virtual files (like generated index.json)
    size: int
    virtual_bytes: Optional[bytes] = None

    def open_stream(self) -> io.BufferedReader:
        if self.virtual_bytes is not None:
            return io.BufferedReader(io.BytesIO(self.virtual_bytes))
        if self.abs_path is None:
            raise ValueError("FileEntry has no data source")
        return open(self.abs_path, "rb")


def sanitize_bank_rel(rel: str) -> str:
    """
    Normalize a bank internal path to safe POSIX form.
    - uses '/'
    - strips leading '/'
    - removes '.' segments
    - rejects '..'
    """
    rel = rel.replace("\\", "/").lstrip("/")
    parts = []
    for p in rel.split("/"):
        if p in ("", "."):
            continue
        if p == "..":
            raise ValueError(f"Refusing path traversal segment in: {rel!r}")
        parts.append(p)
    return "/".join(parts)


def collect_tree(input_dir: Path) -> Tuple[List[DirEntry], List[FileEntry]]:
    """
    Walk input_dir recursively.
    Returns:
      - directories (excluding root) as DirEntry
      - files as FileEntry
    """
    dirs: Set[str] = set()
    files: List[FileEntry] = []

    for p in input_dir.rglob("*"):
        if p.is_dir():
            continue
        if not p.is_file():
            continue

        rel = p.relative_to(input_dir).as_posix()
        rel = sanitize_bank_rel(rel)

        # Collect all parent dirs
        parent = Path(rel).parent.as_posix()
        if parent not in ("", "."):
            # Add each ancestor directory
            cur = Path(parent)
            while True:
                dirs.add(cur.as_posix())
                if cur.parent == cur or cur.parent.as_posix() in ("", "."):
                    break
                cur = cur.parent

        size = p.stat().st_size
        files.append(FileEntry(rel_posix=rel, abs_path=p, size=size))

    dir_entries = [DirEntry(d) for d in sorted(dirs)]
    file_entries = sorted(files, key=lambda f: f.rel_posix.lower())
    return dir_entries, file_entries


def sanitize_id_part(s: str) -> str:
    """
    Mirror kibank's intent:
    - lowercase
    - keep alnum only
    """
    out = []
    for ch in s.lower():
        if ch.isalnum():
            out.append(ch)
    return "".join(out)


def build_metadata_bytes(
    name: str,
    author: str,
    description: str,
    bank_id: str,
) -> bytes:
    """
    Metadata model per lib.rs:
      { version?: u32, id: str, name: str, author: str, description: str, hash?: str, ...extra }
    """
    if not bank_id:
        parts = []
        a = sanitize_id_part(author)
        n = sanitize_id_part(name)
        if a:
            parts.append(a)
        if n:
            parts.append(n)
        bank_id = ".".join(parts)

    obj = {
        "version": None,      # Option<u32> -> null when absent/None
        "id": bank_id,
        "name": name,
        "author": author,
        "description": description,
        "hash": None,         # Option<String> -> null
        # extra fields can be added later if you want
    }

    # pretty-print to match kibank style closely
    text = json.dumps(obj, indent=2, ensure_ascii=False)
    return text.encode("utf-8")


def ensure_metadata_and_background(
    input_dir: Path,
    files: List[FileEntry],
    *,
    name: str,
    author: str,
    description: str,
    bank_id: str,
) -> List[FileEntry]:
    """
    Ensure root-level index.json exists. If missing, add generated virtual file.
    Include root-level background.png/jpg if present
    """
    existing = {f.rel_posix.lower(): f for f in files}

    # Metadata: must be exactly root "index.json"
    if METADATA_FILE_NAME.lower() not in existing:
        meta_bytes = build_metadata_bytes(name, author, description, bank_id)
        files.append(
            FileEntry(
                rel_posix=METADATA_FILE_NAME,
                abs_path=None,
                size=len(meta_bytes),
                virtual_bytes=meta_bytes,
            )
        )

    # Background: include if exists at root as background.png/jpg
    for ext in ("png", "jpg", "jpeg"):
        bg = input_dir / f"{BACKGROUND_FILE_STEM}.{ext}"
        if bg.exists() and bg.is_file():
            rel = sanitize_bank_rel(bg.name)  # root file
            if rel.lower() not in existing:
                files.append(FileEntry(rel_posix=rel, abs_path=bg, size=bg.stat().st_size))
            break

    # deterministic ordering
    return sorted(files, key=lambda f: f.rel_posix.lower())


def write_bank(input_dir: Path, output_bank: Path, *, name: str, author: str, description: str, bank_id: str) -> None:
    dir_entries, file_entries = collect_tree(input_dir)
    file_entries = ensure_metadata_and_background(
        input_dir,
        file_entries,
        name=name,
        author=author,
        description=description,
        bank_id=bank_id,
    )

    # Location order:
    #   1) directories (sorted)
    #   2) files (sorted)
    # This supports arbitrary trees like Bass/Violin/etc.
    location_names: List[Tuple[str, bool]] = []
    for d in dir_entries:
        location_names.append((d.rel_posix, True))
    for f in file_entries:
        location_names.append((f.rel_posix, False))

    location_count = len(location_names)

    # Build filename block (null-terminated)
    name_offsets: List[int] = []
    name_block = bytearray()
    for rel, _is_dir in location_names:
        rel_norm = sanitize_bank_rel(rel)
        name_offsets.append(len(name_block))
        name_block += rel_norm.encode("utf-8", errors="surrogateescape") + b"\x00"

    file_name_block_length = len(name_block)

    header_len = len(FILE_ID) + len(CORRUPTION_CHECK_BYTES) + len(FORMAT_VERSION) + 8
    location_block_len = location_count * LOC.size
    data_start = header_len + location_block_len + 8 + file_name_block_length

    # Map rel path -> FileEntry for quick lookup
    file_map = {f.rel_posix: f for f in file_entries}

    # Compute locations and data offsets
    cur_data_off = data_start
    locations: List[Tuple[int, int, int]] = []  # (name_off, data_off, data_size)

    for (rel, is_dir), name_off in zip(location_names, name_offsets):
        if is_dir:
            locations.append((name_off, 0, 0))
        else:
            fe = file_map[rel]
            locations.append((name_off, cur_data_off, fe.size))
            cur_data_off += fe.size

    # Write file
    output_bank.parent.mkdir(parents=True, exist_ok=True)
    with open(output_bank, "wb") as out:
        # Header
        out.write(FILE_ID)
        out.write(CORRUPTION_CHECK_BYTES)
        out.write(FORMAT_VERSION)
        out.write(U64LE.pack(location_count))

        # Location table
        for name_off, data_off, data_size in locations:
            out.write(LOC.pack(name_off, data_off, data_size))

        # Filename block
        out.write(U64LE.pack(file_name_block_length))
        out.write(name_block)

        # Data blobs (in the same order as file locations)
        for rel, is_dir in location_names:
            if is_dir:
                continue
            fe = file_map[rel]
            with fe.open_stream() as src:
                remaining = fe.size
                while remaining > 0:
                    chunk = src.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise IOError(f"Unexpected EOF while reading: {fe.abs_path}")
                    out.write(chunk)
                    remaining -= len(chunk)

        out.flush()

    print(f"OK: wrote bank: {output_bank} ({location_count} entries, {len(file_entries)} files, {len(dir_entries)} dirs)")


def main() -> int:
    ap = argparse.ArgumentParser(description="Create Kilohearts .bank from a folder tree.")
    ap.add_argument("input_dir", type=Path, help="Folder containing presets/samples/index.json/etc.")
    ap.add_argument("output_bank", type=Path, help="Output .bank file path")
    ap.add_argument("--name", default="", help="Bank name (used if generating index.json)")
    ap.add_argument("--author", default="", help="Bank author (used if generating index.json)")
    ap.add_argument("--description", default="", help="Bank description (used if generating index.json)")
    ap.add_argument("--id", dest="bank_id", default="", help="Bank id (used if generating index.json). If omitted, derived from author+name.")
    args = ap.parse_args()

    if not args.input_dir.exists() or not args.input_dir.is_dir():
        ap.error(f"input_dir must be an existing directory: {args.input_dir}")

    if args.output_bank.suffix.lower() != ".bank":
        ap.error("output_bank must end with .bank")

    write_bank(
        args.input_dir,
        args.output_bank,
        name=args.name,
        author=args.author,
        description=args.description,
        bank_id=args.bank_id,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
