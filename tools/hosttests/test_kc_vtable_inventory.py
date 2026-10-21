"""Synthetic Mach-O tests: no Apple artifacts or hardware required."""
import importlib.util
from pathlib import Path
import struct
import sys
from types import SimpleNamespace
import unittest

SPEC = importlib.util.spec_from_file_location("kc_vtable_inventory", Path(__file__).parents[1] / "kc_vtable_inventory.py")
kc = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(kc)


def fixture(base=0x1000):
    data = bytearray(0x1000)
    commands = []
    for name, va, offset, prot in ((b"__TEXT", base, 0, 5), (b"__DATA", base + 0x800, 0x800, 3)):
        commands.append(struct.pack("<II16sQQQQiiII", 0x19, 72, name, va, 0x800, offset, 0x800, prot, prot, 0, 0))
    names = ("__ZTV4Test", "__ZN4Test3fooEv", "__ZTV4Next")
    strings = b"\0" + b"\0".join(n.encode() for n in names) + b"\0"
    commands.append(struct.pack("<6I", 2, 24, 0xc00, 3, 0xc50, len(strings)))
    commands.append(struct.pack("<4I", 0x80000034, 16, 0xd00, 64))
    cmddata = b"".join(commands)
    struct.pack_into("<8I", data, 0, 0xfeedfacf, 0x01000007, 3, 11, len(commands), len(cmddata), 0, 0)
    data[32:32 + len(cmddata)] = cmddata
    data[0xc50:0xc50 + len(strings)] = strings
    strx = 1
    for i, (name, addr) in enumerate(zip(names, (base + 0x800, base + 0x100, base + 0x820))):
        struct.pack_into("<IBBHQ", data, 0xc00 + 16 * i, strx, 0xf, 1, 0, addr)
        strx += len(name) + 1
    struct.pack_into("<7I", data, 0xd00, 0, 28, 64, 64, 0, 1, 0)
    struct.pack_into("<3I", data, 0xd1c, 2, 0, 12)
    struct.pack_into("<IHHQIH", data, 0xd28, 24, 4096, 11, 0x800, 0, 1)
    struct.pack_into("<H", data, 0xd3e, 16)
    struct.pack_into("<2Q", data, 0x810, 0x100 | (1 << 30) | (8 << 51), 0x100)
    return data


class InventoryTests(unittest.TestCase):
    def collections(self, data=None):
        system = kc.Image(data if data is not None else fixture(), ident="system")
        boot = kc.Image(fixture(0x9000), ident="boot")
        symbols = lambda image: {s["value"]: [dict(image=image.ident, **s)] for s in image.symbols}
        return {0: SimpleNamespace(base=0x9000, image=boot, symbols=symbols(boot)),
                1: SimpleNamespace(base=0x1000, image=system, symbols=symbols(system))}, system

    def test_observed_slots_use_correct_cache_level(self):
        collections, image = self.collections()
        result = kc.observe_vtable(collections, image, "Test")
        self.assertEqual(result["nslots"], 2)
        self.assertEqual([s["target_va"] for s in result["slots"]], ["0x1100", "0x9100"])
        self.assertEqual([s["symbols"][0]["image"] for s in result["slots"]], ["system", "boot"])
        self.assertFalse(result["zero_boundary"]["chain_member"])

    def test_nonzero_slot_outside_chain_is_rejected(self):
        data = fixture()
        struct.pack_into("<Q", data, 0x810, 0x100 | (1 << 30))  # chain ends before slot 1
        collections, image = self.collections(data)
        with self.assertRaisesRegex(kc.FormatError, "outside fixup chains"):
            kc.observe_vtable(collections, image, "Test")

    def test_chained_zero_is_not_treated_as_terminator(self):
        data = fixture()
        struct.pack_into("<Q", data, 0x818, 0x100 | (8 << 51))
        collections, image = self.collections(data)
        with self.assertRaisesRegex(kc.FormatError, "zero is a chained pointer"):
            kc.observe_vtable(collections, image, "Test")

    def test_chain_crossing_page_is_rejected(self):
        data = fixture()
        struct.pack_into("<H", data, 0xd3e, 4092)
        with self.assertRaisesRegex(kc.FormatError, "crosses page"):
            kc.Image(data).chains()

    def test_invalid_command_size_is_rejected(self):
        data = fixture()
        struct.pack_into("<I", data, 36, 0)
        with self.assertRaisesRegex(kc.FormatError, "load-command size"):
            kc.Image(data)

    def test_symbol_string_offset_is_bounded(self):
        data = fixture()
        struct.pack_into("<I", data, 0xc00, 0xffff)
        with self.assertRaisesRegex(kc.FormatError, "symbol string offset"):
            kc.Image(data)

    def test_wrong_pointer_format_is_rejected(self):
        data = fixture()
        struct.pack_into("<H", data, 0xd2e, 8)
        with self.assertRaisesRegex(kc.FormatError, "requires format 11"):
            kc.Image(data).chains()

    def test_chain_segment_offset_is_verified(self):
        data = fixture()
        struct.pack_into("<Q", data, 0xd30, 0x900)
        with self.assertRaisesRegex(kc.FormatError, "segment offset disagrees"):
            kc.Image(data).chains()

    def test_unmapped_target_is_rejected(self):
        data = fixture()
        struct.pack_into("<Q", data, 0x810, 0x5000 | (1 << 30) | (8 << 51))
        collections, image = self.collections(data)
        with self.assertRaisesRegex(kc.FormatError, "0 file mappings"):
            kc.observe_vtable(collections, image, "Test")

    def test_non_executable_target_is_rejected(self):
        data = fixture()
        struct.pack_into("<Q", data, 0x810, 0x900 | (1 << 30) | (8 << 51))
        collections, image = self.collections(data)
        with self.assertRaisesRegex(kc.FormatError, "not executable"):
            kc.observe_vtable(collections, image, "Test")

    def test_pointer_fields_preserve_level_and_byte_stride(self):
        value = 0x1234 | (3 << 30) | (0xabc << 51)
        self.assertEqual(kc.decode_rebase(value)["cache_level"], 3)
        self.assertEqual(kc.decode_rebase(value)["next"], 0xabc)
        self.assertEqual(kc.decode_rebase(value)["target_offset"], 0x1234)

    def test_unknown_symbol_is_preserved_without_nearest_fallback(self):
        collections, image = self.collections()
        collections[1].symbols[0x1100] = []
        result = kc.observe_vtable(collections, image, "Test")
        self.assertEqual(result["unresolved_slots"], [0])
        self.assertEqual(result["slots"][0]["symbols"], [])

    def test_symbol_aliases_are_retained_as_ambiguity(self):
        collections, image = self.collections()
        original = collections[1].symbols[0x1100][0]
        collections[1].symbols[0x1100].append(dict(original, name="__ZN4Test5aliasEv"))
        result = kc.observe_vtable(collections, image, "Test")
        self.assertEqual(result["alias_slots"], [0])
        self.assertEqual(len(result["slots"][0]["symbols"]), 2)

    def test_pure_method_requires_exact_target_symbol(self):
        collections, image = self.collections()
        collections[0].symbols[0x9100][0]["name"] = "___cxa_pure_virtual"
        result = kc.observe_vtable(collections, image, "Test")
        self.assertEqual(result["pure_slots"], [1])

    def test_truncated_header_is_rejected(self):
        with self.assertRaises(kc.FormatError):
            kc.Image(b"\0" * 16)


if __name__ == "__main__":
    unittest.main()
