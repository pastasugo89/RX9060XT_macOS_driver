#!/usr/bin/env python3
"""Replay enabled kernel Find/Mask patches on a read-only Mach-O or BootKC copy.

Replacements happen in memory only. This validates static pattern destinations,
not hardware boot, relocation effects, other OpenCore quirks or kext patches.
"""
import argparse
import bisect
import hashlib
import json
import plistlib
import re
import struct
from pathlib import Path


def commands(data, start=0):
    if data[start:start + 4] != b"\xcf\xfa\xed\xfe":
        raise ValueError("Expected little-endian 64-bit Mach-O")
    count = struct.unpack_from("<I", data, start + 16)[0]
    position = start + 32
    for _ in range(count):
        kind, size = struct.unpack_from("<II", data, position)
        if size < 8 or position + size > len(data):
            raise ValueError("Invalid load command")
        yield kind, position, size
        position += size


def layout(data):
    header = 0
    for kind, position, _ in commands(data):
        if kind == 0x80000035:
            _, _, _, offset, string_offset, _ = struct.unpack_from("<IIQQII", data, position)
            end = data.index(0, position + string_offset)
            if data[position + string_offset:end] == b"com.apple.kernel":
                header = offset
    segments, symbols = [], []
    for kind, position, _ in commands(data, header):
        if kind == 0x19:
            _, _, name, address, _, offset, size, *_ = struct.unpack_from("<II16sQQQQIIII", data, position)
            segments.append((offset, size, address, name.split(b"\0")[0].decode()))
        elif kind == 2:
            _, _, symoff, count, stroff, strsize = struct.unpack_from("<IIIIII", data, position)
            for index in range(count):
                strx, kind, _, _, address = struct.unpack_from("<IBBHQ", data, symoff + index * 16)
                if strx and kind & 0xE == 0xE:
                    end = data.index(0, stroff + strx, stroff + strsize)
                    symbols.append((address, data[stroff + strx:end].decode(errors="replace")))
    symbols.sort()
    return header, segments, symbols


def masked_pattern(find, mask):
    if not mask:
        return re.compile(re.escape(find))
    if len(mask) != len(find):
        raise ValueError("Find/Mask length mismatch")
    parts = []
    for wanted, bitmask in zip(find, mask):
        allowed = bytes(v for v in range(256) if v & bitmask == wanted & bitmask)
        parts.append(b"." if len(allowed) == 256 else b"[" + b"".join(re.escape(bytes([v])) for v in allowed) + b"]")
    return re.compile(b"".join(parts), re.DOTALL)


def replay(original, config, version):
    header, segments, symbols = layout(original)
    addresses = [s[0] for s in symbols]
    by_name = {name: address for address, name in symbols}
    modified = bytearray(original)
    results = []
    def where(offset):
        segment = next((s for s in segments if s[0] <= offset < s[0] + s[1]), None)
        address = offset - segment[0] + segment[2] if segment else None
        index = bisect.bisect_right(addresses, address) - 1 if address else -1
        symbol = symbols[index] if index >= 0 else None
        return {"file_offset": hex(offset), "address": hex(address) if address else None,
                "segment": segment[3] if segment else None,
                "nearest_symbol": symbol[1] if symbol else None,
                "symbol_delta": hex(address - symbol[0]) if symbol else None}
    for patch in config["Kernel"]["Patch"]:
        if not patch["Enabled"] or patch["Identifier"].lower() != "kernel":
            continue
        if patch["MinKernel"] and tuple(map(int, patch["MinKernel"].split("."))) > version:
            continue
        if patch["MaxKernel"] and tuple(map(int, patch["MaxKernel"].split("."))) < version:
            continue
        # OpenCore's kernel patch context starts at the collection header.
        begin, end = 0, len(modified)
        base = patch["Base"].strip()
        if base:
            address = by_name[base]
            segment = next(s for s in segments if s[2] <= address < s[2] + s[1])
            begin = address - segment[2] + segment[0]
        if patch["Limit"]:
            end = min(end, begin + patch["Limit"])
        find, replace = patch["Find"], patch["Replace"]
        if not find:
            raise ValueError("This audit requires explicit Find patterns")
        pattern = masked_pattern(find, patch["Mask"])
        position, skip, hits = begin, patch["Skip"], []
        while position < end:
            match = pattern.search(modified, position, end)
            if match is None:
                break
            offset = match.start()
            position = offset + len(find)
            if skip:
                skip -= 1
                continue
            hits.append(where(offset))
            mask = patch["ReplaceMask"] or bytes([255]) * len(find)
            for index, bitmask in enumerate(mask):
                modified[offset + index] = (modified[offset + index] & (~bitmask & 255)) | (replace[index] & bitmask)
            if patch["Count"] and len(hits) == patch["Count"]:
                break
        results.append({"comment": patch["Comment"], "base_whitespace_trimmed": base != patch["Base"],
                        "expected_count": patch["Count"], "actual_count": len(hits), "hits": hits,
                        "count_passed": bool(hits) and (not patch["Count"] or patch["Count"] == len(hits))})
    return {"kernel_header_offset": hex(header), "patches": results,
            "all_expected_counts_passed": all(r["count_passed"] for r in results)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kernel", type=Path)
    parser.add_argument("configs", nargs="+", type=Path)
    parser.add_argument("--darwin", default="25.6.0")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    original = args.kernel.read_bytes()
    version = tuple(map(int, args.darwin.split(".")))
    result = {"kernel_sha256": hashlib.sha256(original).hexdigest(), "darwin": args.darwin,
              "coverage": "Sequential enabled kernel patches on the extracted recovery BootKC; static replay in memory. Kext patches and other runtime transformations are excluded. Symbol labels identify the nearest preceding defined symbol.",
              "configs": []}
    for path in args.configs:
        config = plistlib.loads(path.read_bytes())
        record = replay(original, config, version)
        record["config_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        result["configs"].append(record)
        print(path.parent.parent.parent.name, "all expected counts:", record["all_expected_counts_passed"])
        for patch in record["patches"]:
            if "thread_invoke, thread_dispatch" in patch["comment"]:
                print(patch["comment"], patch["hits"])
    with args.output.open("x") as handle:
        json.dump(result, handle, indent=2)
        handle.write("\n")
    if hashlib.sha256(args.kernel.read_bytes()).hexdigest() != result["kernel_sha256"]:
        raise RuntimeError("Source kernel changed during audit")


if __name__ == "__main__":
    main()
