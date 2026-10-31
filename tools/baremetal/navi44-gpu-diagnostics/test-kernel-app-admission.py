#!/usr/bin/env python3
"""Execute the kernel's application budget (native_s1c.cpp app_budget_locked / app_budget_refused_log) and check its wiring in n1c_open.

Admission of an application no longer needs an allow-list entry in the 64-context profile; the table is shared by the budget in
native_g4_pure.h (reserve for WindowServer and system processes, per-process cap, per-uid cap, kIOReturnNoResources on refusal).
The two kernel functions are extracted from the real source and compiled with ASan/UBSan against a model of the record table; the
pure header is the real one. Legacy profiles are checked by source: the budget is reached only through production_on().
"""
from pathlib import Path
import argparse
import subprocess
import tempfile

root = Path(__file__).resolve().parents[3]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--kernel-source', type=Path, default=root / 'cobalt64/src/navi48-bringup')
args = parser.parse_args()
src = args.kernel_source.resolve()
headers = src / 'src/amd'
s1c = (headers / 'native_s1c.cpp').read_text()
client = (src / 'src/Navi48NativeClient.cpp').read_text()
failures = []


def check(ok, what):
    if not ok:
        failures.append(what)


def between(text, start_marker, end_marker):
    a = text.index(start_marker)
    b = text.index(end_marker, a)
    return text[a:b] + '\n'


def function_body(text, signature):
    start = text.index(signature)
    opening = text.index('{', start)
    end, depth = opening + 1, 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end] + '\n'


# the kernel's real budget functions (table scratch + admit wrapper + refusal log)
budget_src = between(s1c, 'static n48native::g4::budget::Use gBudgetUse[kMaxSessions];', 'static __attribute__((noinline)) void open_refused_log(')

prefix = r'''
#define N48_MAX_NATIVE_SESSIONS 8
#define N48_MAX_LOGICAL_CONTEXTS 64
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <cassert>
#include "native_g4_pure.h"
using namespace n48native;
using namespace n48native::g2;
#define N1C_LOG(...) std::printf(__VA_ARGS__), std::printf("\n")
#define __attribute__(x)
struct Session { bool app; uint32_t pid, uid; };
static Session sessTable[kMaxSessions];
static Session *slot_ptr(uint32_t i) { return sessTable[i].pid || sessTable[i].app ? &sessTable[i] : nullptr; }
static uint8_t gSlotState[kMaxSessions];
struct N1cOpener { bool app; uint32_t pid; uint32_t uid; };
'''
body = r'''
static int gFail = 0;
static void expect(bool ok, const char *what) { if (!ok) { gFail++; std::printf("FAIL: %s\n", what); } }
static void reset() { for (uint32_t i = 0; i < kMaxSessions; i++) { gSlotState[i] = kSlotFree; sessTable[i] = Session{false, 0, 0}; } }
static void open_record(uint32_t i, uint32_t pid, uint32_t uid, bool app) { gSlotState[i] = kSlotOpen; sessTable[i] = Session{app, pid, uid}; }
int main() {
    using namespace n48native::g4::budget;
    // 1. sequential applications, each its own process and one of ten uids: exactly 55 admitted, the 56th refused by the reserve
    reset();
    uint32_t admitted = 0, firstRefused = 99;
    Verdict refusal = kVerdictOk;
    for (uint32_t k = 0; k < kMaxSessions; k++) {
        const N1cOpener who{ true, 2000u + k, 501u + (k % 10u) };
        const Verdict v = app_budget_locked(who);
        if (v != kVerdictOk) { if (firstRefused == 99) { firstRefused = k; refusal = v; } continue; }
        uint32_t slot = 0; while (gSlotState[slot] != kSlotFree) slot++;
        open_record(slot, who.pid, who.uid, true);
        admitted++;
    }
    expect(admitted == 55, "applications admitted into an empty table: 55");
    expect(firstRefused == 55 && refusal == kReservedForSystem, "the 56th application is refused by the reserve");
    // 2. system and WindowServer opens take the 9 kept records; the budget never refuses them
    uint32_t sys = 0;
    for (uint32_t i = 0; i < kMaxSessions; i++) if (gSlotState[i] == kSlotFree) {
        expect(admit(nullptr, 0, kMaxSessions, false, 1u, 0u, 0u) == kVerdictOk, "a system open is never refused by the budget");
        open_record(i, 1u, 0u, false); sys++;
    }
    expect(sys == 9, "nine records are kept for WindowServer and system processes");
    // 3. per process: a ninth record of one pid is refused, another pid of the same uid is not
    reset();
    for (uint32_t k = 0; k < 8; k++) open_record(k, 3000u, 501u, true);
    expect(app_budget_locked(N1cOpener{ true, 3000u, 501u }) == kPerPidLimit, "per-process cap: 8 records of one pid, the 9th is refused");
    expect(app_budget_locked(N1cOpener{ true, 3001u, 501u }) == kVerdictOk, "per-process cap does not block another process");
    // 4. per uid: 32 records of one uid; a new process of that uid is refused; another uid is not
    reset();
    for (uint32_t k = 0; k < 32; k++) open_record(k, 4000u + k / 2u, 600u, true);
    expect(app_budget_locked(N1cOpener{ true, 4100u, 600u }) == kPerUidLimit, "per-uid cap: 32 records per uid");
    expect(app_budget_locked(N1cOpener{ true, 4100u, 601u }) == kVerdictOk, "per-uid cap does not block another uid");
    // 5. records that are closed (DEAD or Free) do not count; the closed app role does not count
    reset();
    for (uint32_t k = 0; k < 8; k++) { open_record(k, 5000u, 501u, true); gSlotState[k] = kSlotDead; }
    expect(app_budget_locked(N1cOpener{ true, 5000u, 501u }) == kVerdictOk, "DEAD records do not count against the process cap");
    // 6. the refusal code and text: the kext returns kIOReturnNoResources (0xe00002be), distinct from ExclusiveAccess
    expect(s1c::kNoResources == 0xe00002beu && s1c::kNoResources != s1c::kExclusive, "budget refusals use kIOReturnNoResources");
    for (uint32_t v = 1; v <= 4; v++) expect(std::strcmp(verdict_text((Verdict)v), "?") != 0, "every budget refusal has a text");
    // 7. refusal log path compiles and runs
    app_budget_refused_log(N1cOpener{ true, 1u, 501u }, kReservedForSystem);
    return gFail == 0 ? 0 : 1;
}
'''

with tempfile.TemporaryDirectory(prefix='app-admission-') as tmp:
    tmp_path = Path(tmp)
    driver = tmp_path / 'driver.cpp'
    driver.write_text(prefix + budget_src + body)
    exe = tmp_path / 'driver'
    compile_cmd = ['clang++', '-std=c++17', '-O1', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                   '-I', str(headers), '-I', str(src / 'src'), str(driver), '-o', str(exe)]
    comp = subprocess.run(compile_cmd, capture_output=True, text=True)
    if comp.returncode != 0:
        print(comp.stderr[-4000:])
        raise SystemExit('FAIL: the kernel budget functions do not compile against the pure header')
    run = subprocess.run([str(exe)], capture_output=True, text=True)
    if run.returncode != 0:
        failures.append('driver failed: ' + (run.stdout + run.stderr)[-800:])

# 8. wiring in the real kernel source (legacy profiles: the budget is reached only through production_on())
n1c_open = function_body(s1c, 'IOReturn n1c_open(BringupContext &ctx, bool ws, N1cRef *out, const N1cOpener *who) {')
order = ['if (pk.rc != kOk) { open_refused_log(', 'production_on() && who != nullptr && who->app', 'app_budget_locked(*who)',
         'app_budget_refused_log(*who, bv); rc = kIOReturnNoResources; break;', 'if (gSessSeqCounter == UINT32_MAX)']
pos = [n1c_open.find(t) for t in order]
check(all(p >= 0 for p in pos) and pos == sorted(pos), 'n1c_open: budget after the table choice, before any record, refusal NoResources')
check('s->pid = who != nullptr' in n1c_open and 's->app = who != nullptr && who->app;' in n1c_open, 'n1c_open records pid, uid and app role')
ac = function_body(s1c, 'bool n1c_app_allowed(const char *comm, bool *struckOut) {')
check('app_admit_profile(logical, listed' in ac and 'const bool logical = production_on();' in ac, 'allow-list not required in the 64-context profile')
check('uc->openerPid = ' in client or 'openerPid = (uint32_t)proc_selfpid();' in client, 'initWithTask records the opener process')
cr = function_body(client, 'IOReturn IOAccelNavi48NativeClient::create(')
check('const amdgpu::N1cOpener who { uc->appSession, uc->openerPid, uc->openerUid };' in cr and
      'amdgpu::n1c_open(*owner->bringupContext(), uc->wsSession, &ref, &who);' in cr, 'create passes the opener to n1c_open')

if failures:
    for f in failures:
        print('FAIL:', f)
    raise SystemExit(1)
print('PASS: 64-context admission: applications need no allow-list entry; 55 application records with 9 kept for WindowServer and system; '
      'per-process 8, per-uid 32; refusals kIOReturnNoResources; the real kernel budget functions and n1c_open wiring are checked. Host model, not live IOKit.')
