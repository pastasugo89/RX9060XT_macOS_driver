#!/usr/bin/env python3
"""Report explicitly declared Metal selectors; this is not an Objective-C parser.

Inputs are the existing ipsw class-dump headers and Navi48Device.m. No target
code runs. Only single-line declarations starting with '-' or '@property' are
counted, and only Navi48Device's own implementation is examined in the source.
Macros, categories in other files, synthesized/dynamic methods, conditionals,
and bodies of inherited implementations are deliberately outside coverage.
"""

import argparse
import hashlib
import json
import re
from pathlib import Path


METHOD = re.compile(r"^-\s*\([^)]*\)\s*(.*)")
ARGUMENT = re.compile(r"(\w+)\s*:\s*\(")
PROPERTY = re.compile(r"^@property\s+(?:\(([^)]*)\)\s+)?[^\n]*?\b([A-Za-z_]\w*)\s*;$")


def declared_selectors(path, root, include_properties=False, source=False):
    """Retain path/line/signature for each counted declaration."""
    entries = {}
    active = not source
    for number, original in enumerate(path.read_text().splitlines(), 1):
        line = original.strip()
        if source and line == "@implementation Navi48Device":
            active = True
            continue
        if source and active and line == "@end":
            break
        if not active:
            continue
        match = METHOD.match(line)
        if match:
            # In this bounded input, method signatures occupy one line and the
            # first '{' starts the body. Headers end their declarations in ';'.
            signature = line.split("{", 1)[0].strip() if source else line
            remainder = METHOD.match(signature).group(1)
            arguments = ARGUMENT.findall(remainder)
            if arguments:
                selector = "".join(argument + ":" for argument in arguments)
            else:
                name = re.match(r"\w+", remainder)
                if name is None:
                    raise ValueError(f"Unsupported declaration at {path}:{number}")
                selector = name.group(0)
            entries[selector] = {
                "path": str(path.relative_to(root)),
                "line": number,
                "kind": "method",
                "declaration": signature,
            }
        elif include_properties and not source:
            match = PROPERTY.match(line)
            if match:
                attributes, name = match.groups()
                attributes = attributes or ""
                getter = re.search(r"getter\s*=\s*(\w+)", attributes)
                selector = getter.group(1) if getter else name
                entry = {
                    "path": str(path.relative_to(root)),
                    "line": number,
                    "kind": "property_accessor",
                    "declaration": line,
                }
                entries[selector] = entry
                if "readonly" not in attributes:
                    setter = re.search(r"setter\s*=\s*(\w+:)", attributes)
                    selector = setter.group(1) if setter else "set" + name[0].upper() + name[1:] + ":"
                    entries[selector] = entry
    return entries


def merged(paths, root, include_properties):
    result = {}
    for path in paths:
        result.update(declared_selectors(path, root, include_properties))
    return result


def audit(root, apple_paths, base_paths, source_path, include_properties):
    apple = merged(apple_paths, root, include_properties)
    bases = merged(base_paths, root, include_properties)
    own = declared_selectors(source_path, root, source=True)
    absent_override = apple.keys() - own.keys()
    inherited = absent_override & bases.keys()
    unrepresented = absent_override - bases.keys()
    return {
        "counts": {
            "amd_declared": len(apple),
            "navi48_explicit": len(own),
            "common": len(apple.keys() & own.keys()),
            "amd_without_navi48_override": len(absent_override),
            "without_override_but_base_declared": len(inherited),
            "without_override_or_base_declaration": len(unrepresented),
        },
        "amd_without_override": {
            selector: {
                "amd": apple[selector],
                "base": bases.get(selector),
                "classification": "base_declared_body_unverified" if selector in inherited else "not_declared_in_examined_bases",
            }
            for selector in sorted(absent_override)
        },
        "lazy_initialize_declarations": {
            "navi48": own.get("lazyInitialize"),
            "base": bases.get("lazyInitialize"),
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--summary", action="store_true", help="Omit the per-selector declaration inventory")
    args = parser.parse_args()
    root = args.root.resolve()
    classdump = root / "research/macos/25G83/rea/classdump"
    apple_paths = [classdump / "amdx6000mtl/AMDRadeonX6000MTLDriver" / (name + ".h")
                   for name in ("GFXAAMD_MtlDevice", "GFX10_MtlDevice")]
    base_paths = [classdump / "metal/Metal" / (name + ".h")
                  for name in ("MTLIOAccelDevice", "_MTLDevice")]
    source_path = root / "cobalt64/tools/native/navi48metal/Navi48Device.m"
    report = {
        "coverage": "Explicit single-line instance methods; optionally declared property accessors. Native code is not executed.",
        "limitations": [
            "Declarations do not establish working implementations or safe inherited preconditions.",
            "No categories outside examined files, macro expansions, dynamic methods, or synthesized source accessors.",
            "Preprocessor alternatives are not evaluated; this is not a runtime census or compiler AST.",
            "Absence in the examined bases does not establish a requirement for the native Vulkan backend.",
        ],
        "inputs": [{"path": str(path.relative_to(root)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                   for path in apple_paths + base_paths + [source_path]],
        "method_only": audit(root, apple_paths, base_paths, source_path, False),
        "with_declared_properties": audit(root, apple_paths, base_paths, source_path, True),
    }
    if args.summary:
        for key in ("method_only", "with_declared_properties"):
            del report[key]["amd_without_override"]
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
