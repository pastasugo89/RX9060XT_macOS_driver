#!/usr/bin/env python3
"""Esegue su Linux i test host di Cobalt64 (cobalt64/src/navi48-bringup/tests/*_test.cpp e src/dcn41/tests).

Ogni test di Cobalt64 scrive in testa il proprio comando di build (righe di commento con "clang++ ..." e
continuazioni "\\"). Questo script li estrae, li lancia dalla radice di cobalt64/ con l'uscita in una cartella
temporanea, aggiunge il flag del profilo ASIC ed esegue il binario (senza argomenti, timeout 120 s).

Uso: tools/hosttests/run-cobalt64-tests.py [--asic navi44|navi48] [--jobs N] [filtro...]
Esito per test: PASS, FAIL (il binario esce != 0), BUILD (non compila su Linux), NOCMD (nessun comando in testa).

Riferimento: tools/hosttests/cobalt64-baseline.txt (esiti del 12/10/2026, identici sull'albero originale d6c9aed:
i FAIL/BUILD li' elencati dipendono da file che Cobalt64 non pubblica). Un test che nel riferimento e' PASS e ora non
lo e' e' una REGRESSIONE e fa uscire con 1. --write-baseline riscrive il riferimento.
"""
import argparse, concurrent.futures as cf, os, pathlib, re, shlex, subprocess, sys, tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
C64 = pathlib.Path(os.environ.get("C64_ROOT", ROOT / "cobalt64")).resolve()


def build_cmd(path):
    """(comando di build, argomenti di esecuzione) dal commento in testa, oppure (None, None)."""
    lines = path.read_text(errors="replace").splitlines()[:80]
    for i, line in enumerate(lines):
        body = line.lstrip("/ *\t")
        if re.match(r"(clang\+\+|clang|c\+\+|cc|g\+\+)\s", body):
            parts = [body]
            j = i
            while parts[-1].rstrip().endswith("\\") and j + 1 < len(lines):
                parts[-1] = parts[-1].rstrip()[:-1]
                j += 1
                parts.append(lines[j].lstrip("/ *\t"))
            segs = " ".join(parts).split("&&")
            try:
                cmd = shlex.split(segs[0].split(";")[0])
            except ValueError:
                return None, None
            exe = cmd[cmd.index("-o") + 1] if "-o" in cmd else None
            args = []
            for seg in segs[1:]:                              # "&& /tmp/x arg..." oppure "&& ./x arg..."
                try:
                    toks = shlex.split(seg.split(";")[0])
                except ValueError:
                    continue
                if toks and exe and os.path.basename(toks[0]) == os.path.basename(exe):
                    args = toks[1:]
                    break
            if not args and exe and j + 1 < len(lines):        # oppure sulla riga dopo, da sola
                nxt = lines[j + 1].lstrip("/ *\t")
                try:
                    toks = shlex.split(nxt)
                except ValueError:
                    toks = []
                if toks and os.path.basename(toks[0]) == os.path.basename(exe):
                    args = toks[1:]
            return cmd, args
    return None, None


def run_one(path, outdir, asic_flag):
    name = path.stem
    cmd, args = build_cmd(path)
    if not cmd and path.parent.name == "tests" and path.parent.parent.name == "dcn41":
        # i test di src/dcn41 non scrivono il comando: tools/dcn41/build.py li compila con il modulo intero
        cmd = ["cc", "-std=c11", "-Wall", "-Isrc/dcn41", str(path.relative_to(C64))] + \
              sorted(str(p.relative_to(C64)) for p in (C64 / "src/dcn41").glob("dcn41_*.c")) + ["-o", name]
        args = []
    if not cmd:
        return name, "NOCMD", ""
    exe = outdir / name
    if "-o" in cmd:
        cmd[cmd.index("-o") + 1] = str(exe)
    else:
        cmd += ["-o", str(exe)]
    if cmd[0] in ("clang++", "c++", "g++"):
        cmd[0] = "clang++"
    elif cmd[0] in ("clang", "cc", "gcc"):
        cmd[0] = "clang"
    cmd = [c for c in cmd if c != "-Werror"] + [asic_flag]   # warning di clang Linux diversi da Apple clang
    b = subprocess.run(cmd, cwd=C64, capture_output=True, text=True, timeout=600)
    if b.returncode:
        err = [l for l in b.stderr.splitlines() if "error" in l][:3]
        return name, "BUILD", "\n".join(err)
    try:
        r = subprocess.run([str(exe)] + args, cwd=C64, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return name, "FAIL", "timeout"
    except OSError as e:                                     # es. il comando produce un .o, non un eseguibile
        return name, "BUILD", f"non eseguibile: {e.strerror}"
    tail = (r.stdout.strip().splitlines() or [""])[-1][:160]
    return name, "PASS" if r.returncode == 0 else "FAIL", tail if r.returncode == 0 else \
        "\n".join((r.stdout + r.stderr).strip().splitlines()[-4:])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asic", default="navi44", choices=("navi44", "navi48"))
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) // 2))
    ap.add_argument("--write-baseline", action="store_true")
    ap.add_argument("filters", nargs="*")
    a = ap.parse_args()
    flag = "-DN4X_ASIC_NAVI48" if a.asic == "navi48" else "-DN4X_ASIC_NAVI44"
    tests = sorted((C64 / "src/navi48-bringup/tests").glob("*_test.cpp")) + \
        sorted((C64 / "src/dcn41/tests").glob("test_*.c"))
    if a.filters:
        tests = [t for t in tests if any(f in t.name for f in a.filters)]
    out = pathlib.Path(tempfile.mkdtemp(prefix="c64tests-"))
    res = []
    with cf.ThreadPoolExecutor(a.jobs) as ex:
        for name, st, info in ex.map(lambda t: run_one(t, out, flag), tests):
            res.append((name, st, info))
            print(f"{st:5s} {name}" + (f"\n      {info}" if st != "PASS" and info else ""), flush=True)
    count = {s: sum(1 for _, x, _ in res if x == s) for s in ("PASS", "FAIL", "BUILD", "NOCMD")}
    print(f"\n[{a.asic}] " + ", ".join(f"{k} {v}" for k, v in count.items()))
    base_path = pathlib.Path(__file__).resolve().parent / "cobalt64-baseline.txt"
    if a.write_baseline:
        base_path.write_text("".join(f"{st} {n}\n" for n, st, _ in sorted(res)))
        print(f"riferimento scritto: {base_path}")
        return 0
    if not base_path.exists():
        return 1 if count["FAIL"] else 0
    base = dict(reversed(l.split()) for l in base_path.read_text().splitlines() if l.strip())
    regress = [n for n, st, _ in res if base.get(n) == "PASS" and st != "PASS"]
    fixed = [n for n, st, _ in res if n in base and base[n] != "PASS" and st == "PASS"]
    new = [n for n, st, _ in res if n not in base]
    if fixed: print("ora PASS (prima no): " + ", ".join(fixed))
    if new: print("nuovi test: " + ", ".join(new))
    if regress:
        print("REGRESSIONI: " + ", ".join(regress))
        return 1
    print("nessuna regressione rispetto al riferimento")
    return 0


if __name__ == "__main__":
    sys.exit(main())
