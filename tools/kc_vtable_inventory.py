#!/usr/bin/env python3
"""Observe x86_64 MH_FILESET vtables without extracting or executing kexts.

Input offsets in embedded load commands are absolute KC file offsets. Format 11
rebases are decoded only at locations reached from LC_DYLD_CHAINED_FIXUPS chains.
This produces evidence, not C++ declarations: return types, class sizes and the
ABI of anonymous methods cannot be recovered from a symbol/vtable inventory.
"""
import argparse
import ast
from collections import defaultdict
import hashlib
import json
import mmap
from pathlib import Path
import struct
import sys
import uuid

U64 = (1 << 64) - 1
ROOT = Path(__file__).resolve().parents[1]


class FormatError(ValueError):
    pass


def check_range(data, offset, size, label="range"):
    if offset < 0 or size < 0 or offset > len(data) or size > len(data) - offset:
        raise FormatError(f"{label} outside file: {offset:#x}+{size:#x}")


def unpack(data, fmt, offset):
    check_range(data, offset, struct.calcsize(fmt))
    return struct.unpack_from(fmt, data, offset)


def cstring(data, start, end):
    check_range(data, start, end - start, "string")
    stop = data.find(b"\0", start, end)
    if stop < 0:
        raise FormatError("unterminated string")
    return data[start:stop].decode("utf-8", errors="replace")


def decode_rebase(raw):
    """Apple dyld fixup-chains.h format 11 (12-bit next, byte stride)."""
    return dict(target_offset=raw & ((1 << 30) - 1),
                cache_level=(raw >> 30) & 3,
                diversity=(raw >> 32) & 0xffff,
                addr_div=(raw >> 48) & 1, key=(raw >> 49) & 3,
                next=(raw >> 51) & 0xfff, authenticated=bool(raw >> 63))


class Image:
    def __init__(self, data, offset=0, ident="fileset"):
        self.data, self.offset, self.ident = data, offset, ident
        magic, cpu, _, self.filetype, ncmds, cmdbytes, _, _ = unpack(data, "<8I", offset)
        if magic != 0xfeedfacf or cpu != 0x01000007:
            raise FormatError("requires little-endian x86_64 Mach-O")
        check_range(data, offset + 32, cmdbytes, "load commands")
        end, pos = offset + 32 + cmdbytes, offset + 32
        self.segments, self.entries, self.symbols = [], [], []
        self.fixups, self.uuid, symtab = None, None, None
        for _ in range(ncmds):
            if pos + 8 > end:
                raise FormatError("load-command count exceeds command area")
            cmd, size = unpack(data, "<II", pos)
            if size < 8 or size % 8 or size > end - pos:
                raise FormatError("invalid load-command size")
            if cmd == 0x19:
                if size < 72:
                    raise FormatError("short segment command")
                name, va, vmsize, off, fsize, maxprot, prot, nsects, _ = unpack(data, "<16sQQQQiiII", pos + 8)
                if size != 72 + 80 * nsects or fsize > vmsize:
                    raise FormatError("invalid segment/section size")
                check_range(data, off, fsize, "segment")
                self.segments.append(dict(name=name.split(b"\0")[0].decode(),
                                          vmaddr=va, vmsize=vmsize, fileoff=off,
                                          filesize=fsize, maxprot=maxprot, prot=prot))
            elif cmd == 2:
                if size != 24:
                    raise FormatError("invalid symtab command")
                symtab = unpack(data, "<4I", pos + 8)
            elif cmd == 0x80000035:
                if size < 32:
                    raise FormatError("short fileset entry")
                va, off, stroff, _ = unpack(data, "<QQII", pos + 8)
                if not 32 <= stroff < size:
                    raise FormatError("invalid fileset entry string offset")
                self.entries.append((cstring(data, pos + stroff, pos + size), va, off))
            elif cmd == 0x80000034:
                if size != 16:
                    raise FormatError("invalid fixup command")
                self.fixups = unpack(data, "<II", pos + 8)
            elif cmd == 0x1b:
                if size != 24:
                    raise FormatError("invalid UUID command")
                self.uuid = str(uuid.UUID(bytes=bytes(data[pos + 8:pos + 24])))
            pos += size
        if pos != end:
            raise FormatError("load commands do not consume declared area")
        if symtab:
            off, count, stroff, strsize = symtab
            check_range(data, off, count * 16, "symbols")
            check_range(data, stroff, strsize, "string table")
            for i in range(count):
                strx, typ, sect, desc, value = unpack(data, "<IBBHQ", off + 16 * i)
                if strx >= strsize:
                    raise FormatError("symbol string offset outside table")
                name = cstring(data, stroff + strx, stroff + strsize)
                if not typ & 0xe0 and typ & 0x0e == 0x0e and sect:
                    self.symbols.append(dict(name=name, value=value, section=sect,
                                             external=bool(typ & 1)))
        self.by_name = defaultdict(list)
        for s in self.symbols:
            self.by_name[s["name"]].append(s)

    def mapping(self, va, size=8):
        found = [(s, s["fileoff"] + va - s["vmaddr"]) for s in self.segments
                 if s["vmaddr"] <= va and size <= s["filesize"] - (va - s["vmaddr"])]
        offsets = {off for _, off in found}
        if len(offsets) != 1:
            raise FormatError(f"VA {va:#x} has {len(offsets)} file mappings in {self.ident}")
        return found[0]

    def chains(self):
        """Map absolute file locations reached from this image's chain starts."""
        if self.fixups is None:
            raise FormatError(f"no chained fixups in {self.ident}")
        start, size = self.fixups
        check_range(self.data, start, size, "fixups")
        def bounded(fmt, off):
            length = struct.calcsize(fmt)
            if off < start or length > start + size - off:
                raise FormatError("fixup metadata outside payload")
            return unpack(self.data, fmt, off)
        version, starts, _, _, imports, _, _ = bounded("<7I", start)
        if version != 0 or imports:
            raise FormatError("unsupported fixup version/imports")
        st = start + starts
        count, = bounded("<I", st)
        if count != len(self.segments):
            raise FormatError("fixup segment count differs from load commands")
        offsets = bounded("<" + "I" * count, st + 4)
        text = [s for s in self.segments if s["name"] == "__TEXT"]
        if len(text) != 1:
            raise FormatError("ambiguous __TEXT chain base")
        image_base, out = text[0]["vmaddr"], {}
        for segment, rel in zip(self.segments, offsets):
            if not rel:
                continue
            info = st + rel
            info_size, page_size, fmt, vmoff, _, pages = bounded("<IHHQIH", info)
            if fmt != 11 or page_size not in (4096, 16384):
                raise FormatError("requires format 11 and standard page size")
            if info_size < 22 + 2 * pages or info_size > start + size - info:
                raise FormatError("invalid chain-start structure size")
            if (image_base + vmoff) & U64 != segment["vmaddr"]:
                raise FormatError("chain segment offset disagrees with Mach-O segment")
            entries = bounded("<" + "H" * ((info_size - 22) // 2), info + 22)
            for page in range(pages):
                val = entries[page]
                if val == 0xffff:
                    continue
                starts_on_page = []
                if val & 0x8000:
                    index = val & 0x7fff
                    if index < pages:
                        raise FormatError("multi-start index overlaps page array")
                    while True:
                        if index >= len(entries):
                            raise FormatError("multi-start index outside array")
                        more = entries[index]
                        starts_on_page.append(more & 0x7fff)
                        index += 1
                        if more & 0x8000:
                            break
                else:
                    starts_on_page.append(val)
                for pointer in starts_on_page:
                    while True:
                        if pointer + 8 > page_size:
                            raise FormatError("chain pointer crosses page")
                        va = (segment["vmaddr"] + page * page_size + pointer) & U64
                        _, off = self.mapping(va)
                        raw, = unpack(self.data, "<Q", off)
                        if off in out:
                            raise FormatError("overlapping fixup chains")
                        decoded = decode_rebase(raw)
                        if decoded["authenticated"] or decoded["diversity"] or decoded["addr_div"] or decoded["key"]:
                            raise FormatError("unexpected authentication bits in x86_64 rebase")
                        out[off] = decoded
                        if not decoded["next"]:
                            break
                        pointer += decoded["next"]
        return out


class Collection:
    def __init__(self, path, level):
        self.path, self.level = Path(path), level
        self.file = self.path.open("rb")
        self.data = mmap.mmap(self.file.fileno(), 0, access=mmap.ACCESS_READ)
        self.image = Image(self.data)
        if self.image.filetype != 12:
            raise FormatError("requires MH_FILESET")
        mapped = [s["vmaddr"] for s in self.image.segments if s["filesize"]]
        self.base = min(mapped)
        self.images = [Image(self.data, off, ident) for ident, _, off in self.image.entries]
        self.symbols = defaultdict(list)
        for image in self.images:
            for sym in image.symbols:
                self.symbols[sym["value"]].append(dict(image=image.ident, **sym))

    def metadata(self):
        return dict(path=str(self.path.resolve()), sha256=hashlib.sha256(self.data).hexdigest(),
                    bytes=len(self.data), level=self.level, base=hex(self.base),
                    base_rule="lowest file-backed outer segment VA", uuid=self.image.uuid,
                    fileset_entries=len(self.images), defined_symbols=sum(map(len, self.symbols.values())))

    def close(self):
        self.data.close()
        self.file.close()


def observe_vtable(collections, image, parent, max_slots=4096):
    name = f"__ZTV{len(parent)}{parent}"
    matches = image.by_name[name]
    if len(matches) != 1:
        raise FormatError(f"{parent}: expected one vtable symbol, found {len(matches)}")
    va = matches[0]["value"]
    chains = image.chains()
    _, off = image.mapping(va, 16)
    header = unpack(image.data, "<2Q", off)
    if header != (0, 0) or off in chains or off + 8 in chains:
        raise FormatError(f"{parent}: unsupported vtable prefix")
    following = min((s["value"] for s in image.symbols if s["value"] > va), default=va + 16 + 8 * max_slots)
    slots = []
    for i in range(max_slots + 1):
        slot_va = va + 16 + i * 8
        if slot_va > following:
            raise FormatError(f"{parent}: crossed next symbol without zero boundary")
        segment, slot_off = image.mapping(slot_va)
        raw, = unpack(image.data, "<Q", slot_off)
        if raw == 0:
            if slot_off in chains:
                raise FormatError(f"{parent}: zero is a chained pointer, not a boundary")
            return dict(parent=parent, image=image.ident, vtable_symbol=name,
                        vtable_va=hex(va), vtable_file_offset=hex(off),
                        prefix=list(header), nslots=len(slots), slots=slots,
                        zero_boundary=dict(va=hex(slot_va), file_offset=hex(slot_off),
                                           raw="0x0", chain_member=False,
                                           next_symbol_va=hex(following)),
                        pure_slots=[s["slot"] for s in slots if s["pure_virtual"]],
                        unresolved_slots=[s["slot"] for s in slots if not s["symbols"]],
                        alias_slots=[s["slot"] for s in slots if len(s["symbols"]) > 1])
        if i == max_slots or slot_va >= following:
            raise FormatError(f"{parent}: no verified zero boundary")
        if slot_off not in chains:
            raise FormatError(f"{parent}[{i}]: nonzero slot outside fixup chains")
        decoded = chains[slot_off]
        level = decoded["cache_level"]
        if level not in collections:
            raise FormatError(f"{parent}[{i}]: unavailable cache level {level}")
        target_collection = collections[level]
        target = (target_collection.base + decoded["target_offset"]) & U64
        target_segment, target_off = target_collection.image.mapping(target, 1)
        if not target_segment["prot"] & 4:
            raise FormatError(f"{parent}[{i}]: target is not executable")
        syms = target_collection.symbols[target]
        slots.append(dict(slot=i, va=hex(slot_va), file_offset=hex(slot_off), raw=hex(raw),
                          **decoded, target_va=hex(target), target_file_offset=hex(target_off),
                          symbols=syms, pure_virtual=any(s["name"] == "___cxa_pure_virtual" for s in syms)))
    raise FormatError("slot scan limit reached")


def read_leaf_spec(path):
    """Read literal LEAVES and totals; never execute project Python."""
    values = {}
    for node in ast.parse(Path(path).read_text()).body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in {"LEAVES", "EXPECT_CLASSES", "EXPECT_SLOTS"}:
                    if target.id == "LEAVES":
                        values[target.id] = [ast.literal_eval(row.elts[1]) for row in node.value.elts]
                    else:
                        values[target.id] = ast.literal_eval(node.value)
    if set(values) != {"LEAVES", "EXPECT_CLASSES", "EXPECT_SLOTS"}:
        raise FormatError("missing leaf specification fields")
    return values


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--boot", required=True, type=Path)
    p.add_argument("--system", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--leaves", type=Path, default=ROOT / "cobalt64/tools/native/navi48accel/gates/leaves.py")
    args = p.parse_args(argv)
    collections = {}
    try:
        collections[0] = Collection(args.boot, 0)
        collections[1] = Collection(args.system, 1)
        spec = read_leaf_spec(args.leaves)
        classes = []
        for parent in spec["LEAVES"]:
            candidates = [(c, im) for c in collections.values() for im in c.images
                          if f"__ZTV{len(parent)}{parent}" in im.by_name]
            if len(candidates) != 1:
                raise FormatError(f"{parent}: ambiguous owning image")
            _, image = candidates[0]
            classes.append(observe_vtable(collections, image, parent))
        count = sum(c["nslots"] for c in classes)
        report = dict(schema="kc-vtable-observations-v1", evidence_type="static",
                      inputs=[c.metadata() for c in collections.values()],
                      leaf_spec=dict(path=str(args.leaves), sha256=hashlib.sha256(args.leaves.read_bytes()).hexdigest()),
                      classes=classes, total_classes=len(classes), total_slots=count,
                      consistency=dict(expected_classes=spec["EXPECT_CLASSES"], expected_slots=spec["EXPECT_SLOTS"],
                                       match=len(classes) == spec["EXPECT_CLASSES"] and count == spec["EXPECT_SLOTS"]),
                      limits=["No class sizes, return types or ABI declarations inferred.",
                              "Zero boundary is observed data, not an explicit Mach-O symbol size.",
                              "Exact target aliases retained; symbols at neighboring addresses are never substituted.",
                              "No execution or runtime layout verification; cache bases must match this KC layout."])
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n")
        for c in classes:
            print(f"{c['parent']}: {c['nslots']} slots, {len(c['pure_slots'])} pure, {len(c['unresolved_slots'])} unresolved, {len(c['alias_slots'])} alias slots")
        print(f"{len(classes)} classes / {count} slots; expected totals {'MATCH' if report['consistency']['match'] else 'MISMATCH'}")
        return 0 if report["consistency"]["match"] else 1
    finally:
        for c in collections.values():
            c.close()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (FormatError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(2)
