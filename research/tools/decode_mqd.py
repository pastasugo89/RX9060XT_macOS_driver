#!/usr/bin/env python3
"""Decode amdgpu MQD dumps (debugfs amdgpu_mqd_*) using struct definitions
parsed from linux/drivers/gpu/drm/amd/include/v12_structs.h.
Usage: decode_mqd.py <v12_structs.h> <struct_name> <mqd.bin> [--all]"""
import re, struct, sys

def parse_struct(header, name):
    src = open(header).read()
    m = re.search(r"struct\s+%s\s*\{(.*?)\n\};" % re.escape(name), src, re.S)
    if not m:
        sys.exit("struct %s not found" % name)
    fields = []
    for line in m.group(1).splitlines():
        line = re.sub(r"//.*|/\*.*?\*/", "", line).strip()
        fm = re.match(r"uint32_t\s+(\w+)(?:\[(\d+)\])?\s*;", line)
        if fm:
            n = int(fm.group(2) or 1)
            if n == 1:
                fields.append(fm.group(1))
            else:
                fields += ["%s[%d]" % (fm.group(1), i) for i in range(n)]
    return fields

def main():
    header, name, path = sys.argv[1:4]
    show_all = "--all" in sys.argv
    fields = parse_struct(header, name)
    data = open(path, "rb").read()
    words = struct.unpack("<%dI" % (len(data) // 4), data[: len(data) // 4 * 4])
    print("# %s: %d fields, dump %d dwords" % (name, len(fields), len(words)))
    for i, f in enumerate(fields):
        if i >= len(words):
            break
        if show_all or words[i] != 0:
            print("%4d 0x%03x %-40s 0x%08x" % (i, i * 4, f, words[i]))

if __name__ == "__main__":
    main()
