#!/usr/bin/env python3
"""Watchdog di sicurezza sul host per il test GPU (RX 9060 XT in VFIO, VM QEMU).

Indipendente dal kext: segue il log seriale della VM (diagnostics/serial.log) e, se la VM deve fermarsi, invia QMP `quit`
a QEMU. Nessun privilegio (nessun sudo): legge un file e parla a un socket unix dell'utente.

Quando termina QEMU, vfio-pci chiude il dispositivo e il kernel lo riporta a riposo (reset): questo e' il comportamento che
il watchdog sfrutta. Non e' un controllo della tensione o del clock: il watchdog fa solo STOP della VM.

Cause di stop (QMP quit):
  kext-trip:<motivo>      una riga N4X-SAFETY con state=TRIP, o un evento event=TRIP / START-FAILED
  host-temp:<C>           hotspot >= --trip-c (default 80) anche con state=OK (difesa in profondita' sul host)
  heartbeat-lost:<s>      nessuna riga heartbeat per piu' di --hb-timeout secondi, dopo il primo heartbeat (kext armato)
  max-runtime:<s>         piu' di --max-runtime secondi dal primo heartbeat (0 = nessun limite)
Un heartbeat state=STOP (kext scaricato in modo pulito) disarma il controllo di timeout: non e' uno stop della VM.

Uso:
  gpu-safety-watchdog.py --serial S --qmp Q --log L [--pidfile P] [--events-dir D] [--dry-run]
  gpu-safety-watchdog.py --selftest            casi unitari + scenari con seriale finto e QMP finto
  gpu-safety-watchdog.py --scenario trip       un singolo scenario (ok, warn, trip, lost, hot, stop, maxrt, malformed, nosensor)
Il lancio reale lo fa tools/vm/start-gpu-test-vm.sh --start (prima di exec OpenCore-Boot.sh). Per fermare solo il watchdog:
tools/vm/start-gpu-test-vm.sh --stop-watchdog.
"""
import argparse
import collections
import datetime
import json
import os
import pathlib
import re
import signal
import socket
import stat
import sys
import tempfile
import threading
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_EVENTS = ROOT / "research" / "hw_dump" / "gpu_safety_events"
DEFAULT_WARN_C = 75   # == n4xs::kDefaultWarnC (cobalt64/src/navi48-bringup/src/amd/n4x_safety_pure.h); test_gpu_safety_watchdog.py checks it
DEFAULT_TRIP_C = 80   # == n4xs::kDefaultTripC
DEFAULT_HB_TIMEOUT_S = 10.0
DEFAULT_MAX_RUNTIME_S = 3600.0
EXIT_QUIT = 2
EXIT_OK = 0

EVENT_RE = re.compile(r"N4X-SAFETY\s+(.*)$")
STATES = ("OK", "WARN", "TRIP", "STOP")


# ---------------------------------------------------------------- parsing ------------------------------------------------------
def parse_safety_line(line):
    """None when the line is not a safety line; else {'kind': 'hb'|'event'|'bad', ...}."""
    m = EVENT_RE.search(line)
    if not m:
        return None
    raw = line.rstrip("\r\n")
    fields = {}
    for tok in m.group(1).split():
        if "=" in tok:
            key, value = tok.split("=", 1)
            fields[key] = value
    if "event" in fields:
        return {"kind": "event", "event": fields["event"], "fields": fields, "raw": raw}
    if "state" not in fields or "t" not in fields:
        return {"kind": "bad", "raw": raw, "why": "no state/t"}
    if fields["state"] not in STATES:
        return {"kind": "bad", "raw": raw, "why": "unknown state %r" % fields["state"]}
    try:
        t_ms = int(fields["t"])
        hot_raw = fields.get("hotspot", "na")
        hot = None if hot_raw == "na" else int(hot_raw)
    except ValueError:
        return {"kind": "bad", "raw": raw, "why": "non-numeric field"}
    return {"kind": "hb", "t_ms": t_ms, "hot": hot, "state": fields["state"],
            "reason": fields.get("reason", "none"), "proto": fields.get("proto", "na"), "raw": raw}


# ---------------------------------------------------------------- decisions ----------------------------------------------------
class Watchdog:
    """The decisions only. No I/O, no sleeping: the caller passes the time, so every case is testable."""

    def __init__(self, warn_c=DEFAULT_WARN_C, trip_c=DEFAULT_TRIP_C, hb_timeout=DEFAULT_HB_TIMEOUT_S,
                 max_runtime=DEFAULT_MAX_RUNTIME_S):
        if not (warn_c < trip_c):
            raise ValueError("warn must be below trip")
        self.warn_c = warn_c
        self.trip_c = trip_c
        self.hb_timeout = hb_timeout
        self.max_runtime = max_runtime
        self.armed = False
        self.last_hb = None
        self.load_start = None
        self.quit_reason = None
        self.last_level = None
        self.history = collections.deque(maxlen=60)

    def feed(self, line, now):
        """Returns [(kind, text)] with kind in info, warn, quit. Sets quit_reason when the VM must stop."""
        parsed = parse_safety_line(line)
        if parsed is None:
            return []
        if self.quit_reason is not None:
            return []
        self.history.append((now, parsed["raw"]))
        if parsed["kind"] == "bad":
            return [("warn", "malformed safety line (ignored, does not refresh the heartbeat): " + parsed["raw"])]
        if parsed["kind"] == "event":
            ev = parsed["event"]
            if ev in ("TRIP", "START-FAILED"):
                return self._quit("kext-event:" + ev + ":" + parsed["fields"].get("reason", "-"))
            return [("info", parsed["raw"])]
        state = parsed["state"]
        if state == "STOP":
            self.armed = False
            return [("info", "kext stopped cleanly (state=STOP): heartbeat watch disarmed")]
        out = []
        if not self.armed:
            self.armed = True
            self.load_start = now
            out.append(("info", "heartbeat watch armed on the first heartbeat"))
        self.last_hb = now
        if state == "TRIP":
            return out + self._quit("kext-trip:" + parsed["reason"])
        hot = parsed["hot"]
        if hot is not None and hot >= self.trip_c:
            return out + self._quit("host-temp:%dC>=%dC" % (hot, self.trip_c))
        level = state
        if hot is not None and hot >= self.warn_c:
            level = "WARN"
        if level != self.last_level and level in ("WARN",):
            out.append(("warn", "level %s hotspot=%s reason=%s" % (level, hot, parsed["reason"])))
        self.last_level = level
        return out

    def tick(self, now):
        if self.quit_reason is not None or not self.armed:
            return []
        if self.last_hb is not None and now - self.last_hb > self.hb_timeout:
            return self._quit("heartbeat-lost:%.1fs" % (now - self.last_hb))
        if self.max_runtime and self.load_start is not None and now - self.load_start > self.max_runtime:
            return self._quit("max-runtime:%.0fs" % (now - self.load_start))
        return []

    def _quit(self, reason):
        self.quit_reason = reason
        return [("quit", reason)]


# ---------------------------------------------------------------- I/O ----------------------------------------------------------
class Log:
    def __init__(self, path):
        self.path = pathlib.Path(path) if path else None
        self.fh = None
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.fh = open(self.path, "a", encoding="utf-8")

    def __call__(self, msg):
        stamp = datetime.datetime.now().isoformat(timespec="seconds")
        line = "%s gpu-safety-watchdog: %s" % (stamp, msg)
        if self.fh:
            self.fh.write(line + "\n")
            self.fh.flush()
        print(line, flush=True)

    def close(self):
        if self.fh:
            self.fh.close()
            self.fh = None


def read_new(path, offset):
    """New text since offset. Handles a missing file and truncation (QEMU truncates the serial log when it starts)."""
    try:
        size = os.path.getsize(path)
    except FileNotFoundError:
        return "", offset
    if size < offset:
        offset = 0
    if size == offset:
        return "", offset
    with open(path, "rb") as fh:
        fh.seek(offset)
        data = fh.read(size - offset)
    return data.decode("utf-8", "replace"), offset + len(data)


def qemu_pids(qmp_path):
    """PIDs of a QEMU process whose command line names this QMP socket (no privilege needed: same user)."""
    pids = []
    me = os.getpid()
    needle = str(qmp_path)
    for name in os.listdir("/proc"):
        if not name.isdigit() or int(name) == me:
            continue
        try:
            with open("/proc/%s/cmdline" % name, "rb") as fh:
                args = [a.decode("utf-8", "replace") for a in fh.read().split(b"\0") if a]
        except OSError:
            continue
        if args and "qemu" in os.path.basename(args[0]) and any(needle in a for a in args):
            pids.append(int(name))
    return pids


def _qmp_reply(fh):
    for _ in range(50):
        line = fh.readline()
        if not line:
            return None
        msg = json.loads(line.decode("utf-8", "replace"))
        if "return" in msg or "error" in msg:
            return msg
    return None


def qmp_quit(qmp_path, timeout=5.0):
    """QMP handshake, then quit. Returns the reply (None when QEMU closed the socket first, which also means it is quitting)."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect(str(qmp_path))
        fh = sock.makefile("rwb")
        fh.readline()                                              # greeting
        fh.write(b'{"execute": "qmp_capabilities"}\n')
        fh.flush()
        _qmp_reply(fh)
        fh.write(b'{"execute": "quit"}\n')
        fh.flush()
        return _qmp_reply(fh)
    finally:
        sock.close()


def write_report(events_dir, reason, wd, serial_path, qmp_result, thresholds):
    stamp = datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", reason)[:60]
    d = pathlib.Path(events_dir) / ("%s-%s" % (stamp, slug))
    d.mkdir(parents=True, exist_ok=True)
    report = {
        "reason": reason,
        "time": datetime.datetime.now().isoformat(timespec="seconds"),
        "thresholds_c": thresholds,
        "heartbeat_history": [raw for _, raw in wd.history],
        "qmp_quit_reply": qmp_result,
        "note": "The host stopped the VM with QMP quit. vfio-pci closes the GPU when QEMU exits; the kernel resets it.",
    }
    (d / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    try:
        text, _ = read_new(serial_path, 0)
        (d / "serial-tail.txt").write_text("\n".join(text.splitlines()[-300:]) + "\n", encoding="utf-8")
    except OSError:
        pass
    return d


def stop_vm(qmp, dry_run, log, alive_fn, quit_fn=qmp_quit, sleep=time.sleep, clock=time.monotonic):
    """Asks QEMU to quit and waits. SIGTERM only as a second step, never SIGKILL. Returns the QMP reply."""
    if dry_run:
        log("DRY-RUN: would send QMP quit to %s (not sent)" % qmp)
        return {"dry_run": True}
    reply = None
    try:
        reply = quit_fn(qmp)
        log("QMP quit sent; reply %s" % json.dumps(reply))
    except (OSError, ValueError) as exc:
        log("QMP quit failed (%s); waiting for QEMU to exit on its own" % exc)
    deadline = clock() + 15.0
    while alive_fn() and clock() < deadline:
        sleep(0.25)
    if alive_fn():
        pids = qemu_pids(qmp)
        log("QEMU still running 15 s after quit (pids %s): SIGTERM" % pids)
        for pid in pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError as exc:
                log("SIGTERM pid %d: %s" % (pid, exc))
        deadline = clock() + 10.0
        while alive_fn() and clock() < deadline:
            sleep(0.25)
        if alive_fn():
            log("QEMU survived SIGTERM: manual intervention needed (no SIGKILL sent by the watchdog)")
    else:
        log("QEMU has exited; the GPU is released (vfio-pci reset on close)")
    return reply


def run_watch(serial, qmp, wd, log, *, dry_run=False, events_dir=DEFAULT_EVENTS, attach_timeout=900.0,
              poll=0.25, alive_fn=None, quit_fn=qmp_quit, sleep=time.sleep, clock=time.monotonic):
    """Main loop. Returns EXIT_QUIT after a stop request, EXIT_OK when the VM ends by itself or never starts."""
    if alive_fn is None:
        alive_fn = lambda: bool(qemu_pids(qmp))  # noqa: E731
    thresholds = {"warn_c": wd.warn_c, "trip_c": wd.trip_c, "hb_timeout_s": wd.hb_timeout, "max_runtime_s": wd.max_runtime}
    t0 = clock()
    while not (os.path.exists(qmp) and stat.S_ISSOCK(os.stat(qmp).st_mode)):
        if clock() - t0 > attach_timeout:
            log("no QEMU socket %s within %.0f s: nothing to watch, exiting" % (qmp, attach_timeout))
            return EXIT_OK
        sleep(poll)
    log("QEMU socket present: following %s" % serial)
    offset = 0
    partial = ""
    gone = 0
    while True:
        now = clock()
        chunk, offset = read_new(serial, offset)
        if chunk:
            lines = (partial + chunk).split("\n")
            partial = lines.pop()
            for line in lines:
                for kind, text in wd.feed(line, now):
                    if kind == "quit":
                        log("STOP REQUEST: %s" % text)
                    elif kind == "warn":
                        log("WARN: %s" % text)
                    else:
                        log(text)
                if wd.quit_reason is not None:
                    break
        if wd.quit_reason is None:
            for kind, text in wd.tick(now):
                log("STOP REQUEST: %s" % text)
        if wd.quit_reason is not None:
            qmp_result = stop_vm(qmp, dry_run, log, alive_fn, quit_fn=quit_fn, sleep=sleep, clock=clock)
            report = write_report(events_dir, wd.quit_reason, wd, serial, qmp_result, thresholds)
            log("event report: %s" % report)
            return EXIT_QUIT
        if alive_fn():
            gone = 0
        else:
            gone += 1
            if gone >= 8:
                log("QEMU is gone and the serial log is quiet: the VM ended by itself, watchdog done")
                return EXIT_OK
        sleep(poll)


# ---------------------------------------------------------------- scenarios (fake serial + fake QMP) -------------------------
SCENARIOS = {
    # name: (lines written by the fake kext as (delay_s, line), expected quit reason prefix or None, hb_timeout, max_runtime)
    "ok": ([("OK", 30)] * 12 + [("STOP", None)], None, 10.0, 0),
    "warn": ([("WARN", 77)] * 3 + [("OK", 30)] * 2, None, 10.0, 0),
    "trip": ([("OK", 30)] * 3 + [("TRIP", 81, "trip-temp")], "kext-trip:trip-temp", 10.0, 0),
    "lost": ([("OK", 30)] * 3, "heartbeat-lost", 0.6, 0),
    "hot": ([("OK", 81)], "host-temp:81C", 10.0, 0),
    "stop": ([("OK", 30)] * 2 + [("STOP", None)], None, 0.6, 0),
    "maxrt": ([("OK", 30)] * 40, "max-runtime", 10.0, 0.5),
    "malformed": ([("BAD", None)] * 2 + [("OK", 30)] * 2, None, 10.0, 0),
    "nosensor": ([("TRIP", None, "no-sensor")], "kext-trip:no-sensor", 10.0, 0),
}


def _hb_line(i, state, hot, reason="none"):
    hot_s = "na" if hot is None else str(hot)
    return ("N4X-SAFETY t=%d hotspot=%s edge=na mem=na ppt=na state=%s reason=%s proto=1 thm=0x1e000000"
            % (1000 * i, hot_s, state, reason))


def _fake_qmp_server(path, record):
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(str(path))
    srv.listen(4)
    srv.settimeout(0.2)
    stop = threading.Event()

    def serve():
        while not stop.is_set():
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            conn.settimeout(2.0)
            try:
                fh = conn.makefile("rwb")
                fh.write(b'{"QMP": {"version": {}, "capabilities": []}}\n')
                fh.flush()
                for line in fh:
                    cmd = json.loads(line.decode())
                    record.append(cmd.get("execute"))
                    fh.write(b'{"return": {}}\n')
                    fh.flush()
                    if cmd.get("execute") == "quit":
                        record.append("quit-received")
                        break
            except (OSError, ValueError):
                pass
            finally:
                conn.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()

    def close():
        stop.set()
        thread.join(2.0)
        srv.close()

    return close


def run_scenario(name, workdir=None, poll=0.05):
    """Runs one scenario end to end. Returns (ok, detail). The fake kext writes lines to a fake serial log; the fake QEMU
    listens on a unix socket and 'exits' when it receives quit. The real loop (run_watch) decides and acts."""
    lines, expect, hb_timeout, max_runtime = SCENARIOS[name]
    base = pathlib.Path(workdir or tempfile.mkdtemp(prefix="gsw-"))
    base.mkdir(parents=True, exist_ok=True)
    serial = base / "serial.log"
    qmp = base / "qmp.sock"
    events = base / "events"
    logpath = base / "watchdog.log"
    if qmp.exists():
        qmp.unlink()
    serial.write_text("", encoding="utf-8")
    received = []
    qemu_alive = {"up": True}
    close_srv = _fake_qmp_server(qmp, received)

    def quit_fn(path):
        reply = qmp_quit(path)
        qemu_alive["up"] = False
        return reply

    def writer():
        i = 0
        time.sleep(0.2)
        with open(serial, "a", encoding="utf-8") as fh:
            for item in lines:
                kind = item[0]
                if kind == "STOP":
                    i += 1
                    fh.write(_hb_line(i, "STOP", None) + "\n")
                elif kind == "BAD":
                    fh.write("N4X-SAFETY garbage without fields\n")
                elif kind == "TRIP":
                    i += 1
                    reason = item[2] if len(item) > 2 else "trip-temp"
                    fh.write(_hb_line(i, "TRIP", item[1] if item[1] else None, reason) + "\n")
                else:
                    i += 1
                    fh.write(_hb_line(i, kind, item[1], "none" if kind == "OK" else "warn-temp") + "\n")
                fh.flush()
                time.sleep(0.05)
        # After the scripted lines the fake kext goes silent: the 'lost' case needs this, the others end by the VM exit below.
        if name not in ("lost",):
            time.sleep(0.5)
            qemu_alive["up"] = False

    wd = Watchdog(hb_timeout=hb_timeout, max_runtime=max_runtime)
    log = Log(logpath)
    try:
        t = threading.Thread(target=writer, daemon=True)
        t.start()
        rc = run_watch(serial, qmp, wd, log, dry_run=False, events_dir=events, attach_timeout=5.0, poll=poll,
                       alive_fn=lambda: qemu_alive["up"], quit_fn=quit_fn)
        t.join(10.0)
    finally:
        log.close()
        close_srv()
    got = wd.quit_reason
    if expect is None:
        ok = got is None and "quit-received" not in received
    else:
        ok = got is not None and got.startswith(expect) and "quit-received" in received and rc == EXIT_QUIT
    detail = "quit=%s qmp=%s rc=%s" % (got, received, rc)
    return ok, detail


# ---------------------------------------------------------------- unit cases (no I/O, fake clock) ----------------------------
def unit_cases():
    failures = []

    def check(cond, what):
        if not cond:
            failures.append(what)

    w = Watchdog()
    check(w.feed(_hb_line(1, "OK", 30), 0.0) == [("info", "heartbeat watch armed on the first heartbeat")], "first heartbeat arms")
    check(w.tick(9.0) == [], "9 s without heartbeat is inside the 10 s budget")
    check(w.feed(_hb_line(2, "OK", 40), 9.0) == [] and w.quit_reason is None, "OK keeps the VM running")
    q = w.tick(20.0)
    check(q and q[0][0] == "quit" and q[0][1].startswith("heartbeat-lost"), "heartbeat lost after 10 s quits")

    w = Watchdog()
    w.feed(_hb_line(1, "OK", 30), 0.0)
    out = w.feed(_hb_line(2, "TRIP", 40, "trip-temp"), 1.0)
    check(out and out[-1][0] == "quit" and w.quit_reason == "kext-trip:trip-temp", "TRIP quits at once")

    w = Watchdog()
    w.feed(_hb_line(1, "OK", 30), 0.0)
    out = w.feed(_hb_line(2, "OK", 80), 1.0)
    check(w.quit_reason == "host-temp:80C>=80C", "host threshold quits even when the kext says OK")

    w = Watchdog()
    w.feed(_hb_line(1, "OK", 30), 0.0)
    out = w.feed(_hb_line(2, "WARN", 77, "warn-temp"), 1.0)
    check(w.quit_reason is None and any(k == "warn" for k, _ in out), "WARN logs, does not quit")

    w = Watchdog()
    w.feed(_hb_line(1, "OK", 30), 0.0)
    w.feed(_hb_line(2, "STOP", None), 1.0)
    check(w.tick(60.0) == [] and w.quit_reason is None, "a clean STOP disarms the timeout")

    w = Watchdog(max_runtime=5.0)
    w.feed(_hb_line(1, "OK", 30), 0.0)
    w.feed(_hb_line(2, "OK", 30), 4.0)
    q = w.tick(6.0)
    check(q and q[0][1].startswith("max-runtime"), "max runtime quits")

    w = Watchdog()
    w.feed(_hb_line(1, "OK", 30), 0.0)
    out = w.feed("N4X-SAFETY garbage", 1.0)
    check(out and out[0][0] == "warn" and w.last_hb == 0.0, "a malformed line warns and does not refresh the heartbeat")

    w = Watchdog()
    out = w.feed("N4X-SAFETY event=TRIP reason=sensor-invalid hotspot=na thm=0xffffffff", 0.0)
    check(out and w.quit_reason == "kext-event:TRIP:sensor-invalid", "event=TRIP quits")

    p = parse_safety_line("12.3 N4X-SAFETY t=5 hotspot=-5 edge=na mem=na ppt=na state=WARN reason=warn-temp proto=0 thm=0x0")
    check(p and p["kind"] == "hb" and p["hot"] == -5 and p["state"] == "WARN", "parser: negative temperature, kernel prefix")
    check(parse_safety_line("no marker here") is None, "parser: non-safety line ignored")
    check(parse_safety_line("N4X-SAFETY t=1 hotspot=x state=OK")["kind"] == "bad", "parser: non-numeric hotspot is bad")
    check(parse_safety_line("N4X-SAFETY t=1 hotspot=30 state=MAYBE")["kind"] == "bad", "parser: unknown state is bad")
    return failures


def selftest(verbose=True):
    failures = unit_cases()
    for name in SCENARIOS:
        ok, detail = run_scenario(name)
        if verbose:
            print("scenario %-9s %s  %s" % (name, "PASS" if ok else "FAIL", detail))
        if not ok:
            failures.append("scenario " + name + ": " + detail)
    if verbose:
        print("unit cases: %s" % ("PASS" if not [f for f in failures if not f.startswith("scenario")] else "FAIL"))
    return failures


# ---------------------------------------------------------------- command line ------------------------------------------------
def _pidfile_write(path):
    if path:
        pathlib.Path(path).write_text(str(os.getpid()) + "\n", encoding="utf-8")


def _pidfile_remove(path):
    if path:
        try:
            if pathlib.Path(path).read_text().strip() == str(os.getpid()):
                pathlib.Path(path).unlink()
        except OSError:
            pass


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--serial", help="seriale della VM (diagnostics/serial.log)")
    ap.add_argument("--qmp", help="socket QMP di QEMU (qmp.sock)")
    ap.add_argument("--log", help="log del watchdog")
    ap.add_argument("--pidfile", help="file con il PID del watchdog (per --stop-watchdog)")
    ap.add_argument("--events-dir", default=str(DEFAULT_EVENTS), help="report degli stop (default: research/hw_dump/gpu_safety_events)")
    ap.add_argument("--warn-c", type=int, default=DEFAULT_WARN_C)
    ap.add_argument("--trip-c", type=int, default=DEFAULT_TRIP_C)
    ap.add_argument("--hb-timeout", type=float, default=DEFAULT_HB_TIMEOUT_S)
    ap.add_argument("--max-runtime", type=float, default=float(os.environ.get("N4X_SAFETY_MAX_S", DEFAULT_MAX_RUNTIME_S)),
                    help="secondi dal primo heartbeat (0 = nessun limite); default 3600 o N4X_SAFETY_MAX_S")
    ap.add_argument("--attach-timeout", type=float, default=900.0)
    ap.add_argument("--poll", type=float, default=0.25)
    ap.add_argument("--dry-run", action="store_true", help="registra lo stop ma non invia QMP quit")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--scenario", choices=sorted(SCENARIOS), help="un solo scenario con seriale e QMP finti")
    args = ap.parse_args(argv)

    if args.selftest:
        failures = selftest()
        print("RESULT:", "PASS" if not failures else "FAIL (%d)" % len(failures))
        return 0 if not failures else 1
    if args.scenario:
        ok, detail = run_scenario(args.scenario)
        print("scenario %s: %s (%s)" % (args.scenario, "PASS" if ok else "FAIL", detail))
        return 0 if ok else 1
    if not (args.serial and args.qmp and args.log):
        ap.error("--serial, --qmp and --log are required (or use --selftest / --scenario)")
    if not (args.warn_c < args.trip_c) or not (50 <= args.warn_c and args.trip_c <= 100):
        ap.error("thresholds: 50 <= warn < trip <= 100")

    log = Log(args.log)
    stopping = {"sig": None}

    def on_term(signum, _frame):
        stopping["sig"] = signum
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, on_term)
    signal.signal(signal.SIGINT, on_term)
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    _pidfile_write(args.pidfile)
    rc = 1
    try:
        log("READY pid=%d warn=%d trip=%d hb_timeout=%.1f max_runtime=%.0f dry_run=%s serial=%s qmp=%s" % (
            os.getpid(), args.warn_c, args.trip_c, args.hb_timeout, args.max_runtime, args.dry_run, args.serial, args.qmp))
        wd = Watchdog(warn_c=args.warn_c, trip_c=args.trip_c, hb_timeout=args.hb_timeout, max_runtime=args.max_runtime)
        rc = run_watch(pathlib.Path(args.serial), pathlib.Path(args.qmp), wd, log, dry_run=args.dry_run,
                       events_dir=pathlib.Path(args.events_dir), attach_timeout=args.attach_timeout, poll=args.poll)
    except SystemExit as exc:
        log("terminated by signal %s (explicit stop; the VM is not touched by this exit)" % stopping["sig"])
        rc = exc.code if isinstance(exc.code, int) else 1
    finally:
        _pidfile_remove(args.pidfile)
        log("exit rc=%s" % rc)
        log.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
