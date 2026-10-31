#!/usr/bin/env python3
"""Run actual WaitSeq code through close/reopen interleavings on one record.

The source function runs with controlled snapshots, sleeps and a hang detector.
This verifies identity/cancellation semantics without invoking IOKit or a GPU.
"""
from pathlib import Path
import argparse
import subprocess
import tempfile

root = Path(__file__).resolve().parents[3]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--kernel-source', type=Path, default=root / 'cobalt64/src/navi48-bringup')
headers = parser.parse_args().kernel_source.resolve() / 'src/amd'
source = (headers / 'native_s1c.cpp').read_text()
start = source.index('struct WaitSnapshot {')
end = source.index('\n// ---- ABI 1.1:', start)
wait = source[start:end]
prefix = r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include "native_g2_pure.h"
using namespace n48native::s1c;
using IOReturn=uint32_t;
constexpr IOReturn kIOReturnSuccess=kOk,kIOReturnNotReady=kNotReady,kIOReturnAborted=kAborted,kIOReturnTimeout=kTimeout;
struct N1cRef { uint32_t slot,id; };
struct Session { uint32_t id; bool open,hello,poisoned; uint64_t emitted; };
static Session session;
enum Race { NONE, INITIAL_SNAPSHOT, RETIREMENT_SNAPSHOT, LOOP_POISON_READ, SLEEP_CLOSE, SLEEP_REOPEN, HANG_CHECK, SAME_OWNER_SUBMIT };
static Race race;
static uint64_t emitted,retired,now;
static unsigned poisonReads,sleeps,polls;
static bool hang,detected,mutated;
static bool registryHeld,pendingMutation,pendingReopen;
struct IOLock {};
static IOLock registry,*gCliLock=&registry;
static void replace(bool reopen) {
 if(registryHeld) { pendingMutation=true; pendingReopen=reopen; return; }
 assert(!mutated); mutated=true; session.open=false;
 if(reopen) { session={42,true,true,false,100}; emitted=retired=100; }
}
static void IOLockLock(IOLock *) { assert(!registryHeld); registryHeld=true; }
static void IOLockUnlock(IOLock *) {
 assert(registryHeld); registryHeld=false;
 if(pendingMutation) { pendingMutation=false; replace(pendingReopen); }
}
static Session *sess_peek(const N1cRef &r) {
 return r.slot==0 && r.id && session.open && session.id==r.id?&session:nullptr;
}
static Session *slot_ptr(uint32_t slot) { return slot==0?&session:nullptr; }
static bool sess_poisoned(const Session *s) {
 ++poisonReads;
 if(race==LOOP_POISON_READ && poisonReads==2)replace(true);
 return s->poisoned;
}
static uint64_t emitted_now() {
 if(race==INITIAL_SNAPSHOT && !mutated)replace(true);
 return emitted;
}
static uint64_t retired_now(uint64_t em) {
 if(race==RETIREMENT_SNAPSHOT && !mutated)replace(true);
 return retired<em?retired:em;
}
static uint64_t now_ns() { now+=1000; return now; }
static bool hung_now() { return hang; }
static bool hang_poll() { assert(!registryHeld); ++polls; if(race==HANG_CHECK && !mutated)replace(true); return detected; }
static void step(unsigned ns) {
 assert(!registryHeld);
 now+=ns; ++sleeps;
 if(race==SLEEP_CLOSE && !mutated)replace(false);
 if(race==SLEEP_REOPEN && !mutated)replace(true);
 if(race==SAME_OWNER_SUBMIT && !mutated) { mutated=true; session.emitted=6; emitted=11; retired=5; }
}
static void IODelay(unsigned us) { step(us*1000); }
static void IOSleep(unsigned ms) { step(ms*1000000); }
'''
suffix = r'''
static void reset(Race r) {
 session={41,true,true,false,5}; race=r;
 emitted=10; retired=0; now=1000; poisonReads=sleeps=polls=0; hang=detected=mutated=false;
 assert(!registryHeld); pendingMutation=pendingReopen=false;
}
int main() {
 const N1cRef ref{0,41};
 for(Race r:{INITIAL_SNAPSHOT,RETIREMENT_SNAPSHOT,LOOP_POISON_READ,SLEEP_CLOSE,SLEEP_REOPEN}) {
  reset(r); uint64_t out[3]={91,92,93};
  assert(n1c_wait(ref,N48N_SEQ_LAST,1000000,out)==kAborted);
  assert(mutated && !polls && out[0]==91 && out[1]==92 && out[2]==93);
 }
 for(unsigned signal=0;signal<2;signal++) {
  reset(HANG_CHECK); detected=signal; uint64_t out[3]={91,92,93};
  assert(n1c_wait(ref,N48N_SEQ_LAST,0,out)==kAborted);
  assert(polls==1 && mutated && out[0]==91 && out[1]==92 && out[2]==93);
 }
 reset(NONE); retired=5; uint64_t out[3]={};
 assert(n1c_wait(ref,N48N_SEQ_LAST,0,out)==kOk && out[0]==0 && out[1]==5 && out[2]==10 && !polls);
 reset(NONE); assert(n1c_wait(ref,0,0,out)==kOk && out[0]==0 && !polls);
 reset(SAME_OWNER_SUBMIT);
 assert(n1c_wait(ref,N48N_SEQ_LAST,1000000,out)==kOk && mutated && out[0]==0 && out[1]==5 && out[2]==11 && !polls);
 reset(NONE); assert(n1c_wait(ref,11,0,out)==kBadArg && !polls);
 reset(NONE); session.poisoned=true; assert(n1c_wait(ref,5,0,out)==kAborted && !polls);
 reset(NONE); hang=true; assert(n1c_wait(ref,5,0,out)==kAborted && !polls);
 reset(NONE); detected=true; assert(n1c_wait(ref,5,0,out)==kTimeout && polls==1);
 reset(NONE); assert(n1c_wait(ref,5,0,out)==kOk && out[0]==1 && polls==1);
 reset(NONE); session.open=false; assert(n1c_wait(ref,5,0,out)==kNotReady);
 reset(NONE); session.id=42; assert(n1c_wait(ref,5,0,out)==kNotReady);
 reset(NONE); session.hello=false; assert(n1c_wait(ref,5,0,out)==kNotReady);
 reset(NONE); gCliLock=nullptr; assert(n1c_wait(ref,5,0,out)==kNotReady); gCliLock=&registry;
 reset(NONE); assert(n1c_wait({1,41},5,0,out)==kNotReady);
 reset(NONE); assert(n1c_wait({0,0},5,0,out)==kNotReady);
 std::puts("PASS: 21 actual WaitSeq paths; close/reopen at snapshots, sleep and hang check abort without reporting a new identity; LAST stays fixed across same-owner submits, normal completion/timeout/errors preserved. IOKit concurrency untested.");
}
'''
with tempfile.TemporaryDirectory(prefix='navi44-kernel-wait-') as directory:
    tmp = Path(directory)
    (tmp / 'probe.cpp').write_text(prefix + wait + suffix)
    subprocess.run(['clang++', '-std=c++17', '-O1', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                    '-include', 'initializer_list', '-I'+str(headers), '-I'+str(headers.parent),
                    str(tmp / 'probe.cpp'), '-o', str(tmp / 'probe')], check=True)
    subprocess.run([str(tmp / 'probe')], check=True)
