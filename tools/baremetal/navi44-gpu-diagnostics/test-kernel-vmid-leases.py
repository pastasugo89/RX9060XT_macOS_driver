#!/usr/bin/env python3
"""Execute actual kernel VMID binding, submit, ring publication and park functions.

The test supplies 64 Session records and simulates MMIO, time, retirement and
locks. It uses the real lease, G2/G5, PM4 building and ring-writing code. It is
not a live IOAccel open test or proof of GFX12 MMIO ordering on the physical GPU.
"""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[3]
headers = root / 'cobalt64/src/navi48-bringup/src/amd'
source = (headers / 'native_s1c.cpp').read_text()


def function(signature):
    start = source.index(signature)
    opening = source.index('{', start)
    end, depth = opening + 1, 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end] + '\n'


prefix = r'''
#define N48_MAX_NATIVE_SESSIONS 8
#define N48_MAX_LOGICAL_CONTEXTS 64
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include "native_g2_pure.h"
#include "native_g5_pure.h"
#include "production_vm_lease_pure.h"
using namespace n48native::s1c;
constexpr uint32_t kIOReturnInternalError=0xdead;
constexpr uint32_t kCPWBOffsetWptr=0x40,kCPDoorbellStride=8;
struct IOLock { unsigned rank; bool held; };
static IOLock registry{1,false},ringLock{2,false},hangLock{3,false};
static IOLock *gCliLock=&registry,*gRingLock=&ringLock,*gHangLock=&hangLock;
static void IOLockLock(IOLock *l) {
 assert(!l->held);
 if(l->rank==1)assert(!ringLock.held && !hangLock.held);
 if(l->rank==2)assert(!hangLock.held);
 l->held=true;
}
static void IOLockUnlock(IOLock *l) { assert(l->held); l->held=false; }
struct Session { uint32_t slot,id,vmid; bool ws,poisoned; uint64_t rootPa,emitted; n48production::Ticket lease; };
static Session sessions[64];
static n48production::Slot gHardwareBindings[n48production::kHardwareSlots];
static uint32_t words[4096],rptr;
alignas(8) static uint8_t writeback[512];
struct DeviceContext {};
struct CPContext { uint32_t ring_ptr_mask,ring_size_dwords,*rptr_cpu,wptr; void *ring_cpu,*wb_cpu; uint64_t wb_bus; uint32_t doorbell_index; };
struct Context { DeviceContext *dev; CPContext cp; };
static DeviceContext device;
static Context context{&device,{4095,4096,&rptr,0,words,writeback,0x100000,2}},*gCtx=&context;
static uint64_t gWc,gEmitted,simRetired,simNow,hardwareRoot[8],gWsLastNs,gG5Since[64];
static uint32_t gWsId,gRecovering;
static Hang gHang;
static n48native::g2::OwnerLog gOwners;
static n48native::g5::Stat gG5;
static n48native::g5::AdmitIn gG5In;
static uint32_t gSubmitBuf[280];
static struct { uint64_t pa; } gPark{0xf00000};
static bool fairOn,autoRetire,geometryOk,rootAck;
static unsigned geometryCalls,programCalls,flushCalls,doorbells,waits,stallCalls;
static uint32_t lastFlushed;
static bool production_on() { return true; }
static bool g5_on() { return fairOn; }
static uint32_t g5_credit() { return 1; }
static bool sess_poisoned(const Session *s) { return s->poisoned; }
static bool hung_now() { return gHang.hung; }
static uint64_t now_ns() { simNow+=1000; return simNow; }
static uint64_t emitted_now() { return gEmitted; }
static uint64_t retired_now(uint64_t emitted) { return simRetired<emitted?simRetired:emitted; }
static void retire_all() { simRetired=gEmitted; rptr=context.cp.wptr; }
static void wait_step(unsigned ns) {
 assert(!registry.held && !ringLock.held && !hangLock.held);
 simNow+=ns; ++waits; if(autoRetire)retire_all();
}
static void IODelay(unsigned us) { wait_step(us*1000); }
static void IOSleep(unsigned ms) { wait_step(ms*1000000); }
static void sysmem_rmb() {}
static void sysmem_wmb() {}
static void amdgpu_hdp_flush(DeviceContext &) {}
static void hang_from_wait() { gHang.hung=true; }
static uint32_t stall_from_wait() { assert(!registry.held && !ringLock.held); ++stallCalls; return 0; }
static uint32_t ctx_prepare(uint32_t slot,uint32_t vmid,bool *ok) {
 assert(registry.held && ringLock.held && slot<8 && vmid==slot+8); ++geometryCalls; *ok=geometryOk; return 0;
}
static uint32_t program_root(uint32_t vmid,uint64_t root) {
 assert(registry.held && ringLock.held && vmid>=8 && vmid<=15);
 const auto &s=gHardwareBindings[vmid-8];
 assert(s.state==n48production::SlotState::Binding && s.lastSequence<=simRetired);
 assert(root==(s.pendingContext?s.pendingRoot:gPark.pa));
 hardwareRoot[vmid-8]=root; ++programCalls;
 return rootAck?kOk:kTimeout;
}
static uint32_t flush_vmid(uint32_t vmid) {
 assert(registry.held && vmid>=8 && vmid<=15); ++flushCalls; lastFlushed=vmid; return kOk;
}
static void WDOORBELL64(DeviceContext &,uint64_t off,uint64_t value) {
 assert(registry.held && ringLock.held && off==context.cp.doorbell_index*kCPDoorbellStride);
 assert(value==gWc && *reinterpret_cast<uint64_t *>(writeback+kCPWBOffsetWptr)==value);
 const auto &entry=gOwners.e[gEmitted%n48native::g2::kOwnerN];
 assert(entry.seq==gEmitted && entry.slot<64 && entry.sessId==sessions[entry.slot].id);
 const auto &s=sessions[entry.slot]; const auto &b=gHardwareBindings[s.lease.slot];
 assert(b.context==s.id && b.generation==s.lease.generation && b.lastSequence==gEmitted && s.emitted==gEmitted);
 assert(b.root==s.rootPa && hardwareRoot[s.lease.slot]==s.rootPa);
 assert(((words[(entry.startWc+6)&4095]>>24)&15)==s.vmid);
 ++doorbells;
}
static uint32_t RDOORBELL32(DeviceContext &,uint64_t) { return 0; }
static void record_log(const char *,...) {}
#define N1C_LOG(...) record_log(__VA_ARGS__)
static uint32_t session_bind_locked(Session *,uint64_t);
'''
suffix = r'''
static void reset() {
 assert(!registry.held && !ringLock.held && !hangLock.held);
 std::memset(sessions,0,sizeof sessions); std::memset(gHardwareBindings,0,sizeof gHardwareBindings);
 std::memset(&gOwners,0,sizeof gOwners); std::memset(&gHang,0,sizeof gHang); std::memset(&gG5,0,sizeof gG5);
 std::memset(gG5Since,0,sizeof gG5Since); std::memset(hardwareRoot,0,sizeof hardwareRoot);
 gWc=gEmitted=simRetired=gWsLastNs=0; simNow=1000; rptr=context.cp.wptr=0; gWsId=1; gRecovering=0;
 geometryCalls=programCalls=flushCalls=doorbells=waits=stallCalls=0;
 fairOn=autoRetire=false; geometryOk=rootAck=true;
 uint8_t state[64]={};
 for(unsigned i=0;i<64;++i) {
  auto pick=n48native::g2::open_pick(true,state,i,i==0,false,true,i!=0,true);
  assert(pick.rc==kOk && pick.slot==i); state[i]=n48native::g2::kSlotOpen;
  sessions[i]={i,i+1,N48N_VMID_DYNAMIC,i==0,false,(i+1ull)*4096,0,{n48production::kNoHardwareSlot,0,0}};
 }
 assert(n48native::g2::open_pick(true,state,64,false,false,true,true,true).rc==kExclusive);
 // Without virtualization, even a 64-record build keeps legacy admission at 8.
 std::memset(state,0,sizeof state); for(unsigned i=0;i<8;++i)state[i]=n48native::g2::kSlotOpen;
 assert(n48native::g2::open_pick(true,state,8,false,false,true,true,false).rc==kExclusive);
 assert(n48native::g2::open_pick(true,state,8,false,false,false,true,true).rc==kExclusive);
 assert(n48native::g2::vmid_of_slot(8)==UINT32_MAX);
 for(unsigned i=0;i<64;++i) {
  assert(n48native::g2::args_ok(n48native::g2::kActSessStat,32+i));
  assert(n48native::g2::stat_page_slot(32+i)==i);
 }
 for(unsigned i=6;i<=9;++i)assert(n48native::g2::stat_page_slot(i)==i-2);
 assert(!n48native::g2::args_ok(n48native::g2::kActSessStat,96));
 assert(!n48native::g2::args_ok(n48native::g2::kActSessStat,UINT64_MAX));
 for(const auto &b:gHardwareBindings)assert(b.state==n48production::SlotState::Empty);
}
static uint32_t submit(unsigned i,uint64_t *out) {
 const uint64_t va=0x10000; const uint32_t size=16;
 return ring_submit_production(&sessions[i],&va,&size,1,false,0,out);
}
int main() {
 static_assert(n48native::g2::kMaxSessions==64 && n48native::g2::kHardwareSessions==8);
 reset(); uint64_t seq=0;
 for(unsigned i=0;i<8;++i)assert(submit(i,&seq)==kOk && seq==i+1);
 const auto wsTicket=sessions[0].lease;
 const auto oldTicket=sessions[1].lease;
 const uint64_t oldRoot=sessions[1].rootPa;
 // Seven outstanding app bindings force an actual scheduler wait, with both
 // locks released. The retired slot can then serve the ninth logical context.
 autoRetire=true;
 for(unsigned i=8;i<64;++i)assert(submit(i,&seq)==kOk && seq==i+1 && sessions[i].vmid>=9 && sessions[i].vmid<=15);
 assert(waits && doorbells==64);
 const auto guilty=n48native::g2::guilty_of(gOwners,simRetired,gEmitted);
 assert(guilty.known && guilty.slot==simRetired && guilty.slot>7 && guilty.sessId==guilty.slot+1);
 assert(gHardwareBindings[0].context==1 && gHardwareBindings[0].generation==wsTicket.generation);
 for(unsigned i=0;i<64;++i)assert(sessions[i].rootPa==(i+1ull)*4096);
 // Old logical owners must not invalidate or park their former VMID after reuse.
 IOLockLock(gCliLock); const auto writes=programCalls,flushes=flushCalls;
 assert(session_flush_locked(&sessions[1])==kOk && flushCalls==flushes);
 assert(session_park_locked(&sessions[1]) && programCalls==writes && sessions[1].rootPa==oldRoot);
 assert(session_flush_locked(&sessions[63])==kOk && flushCalls==flushes+1 && lastFlushed==sessions[63].vmid);
 IOLockUnlock(gCliLock);
 // The real ring writer rejects a stale ticket before touching the ring or seq.
 sessions[1].lease=oldTicket;
 uint32_t dw[15]={}; const auto beforeWc=gWc,beforeEmitted=gEmitted;
 IOLockLock(gCliLock); IOLockLock(gRingLock);
 assert(ring_put_locked(dw,15,gEmitted+1,1,2,&sessions[1])==kNotReady);
 IOLockUnlock(gRingLock); IOLockUnlock(gCliLock);
 assert(gWc==beforeWc && gEmitted==beforeEmitted && doorbells==64);
 IOLockLock(gCliLock);
 assert(!session_park_locked(&sessions[63])); // last submission still pending
 retire_all(); assert(session_park_locked(&sessions[63]));
 IOLockUnlock(gCliLock);

 reset(); sessions[0].ws=false; sessions[1].ws=true; gWsId=2;
 assert(submit(0,&seq)==kOk && sessions[0].vmid==9);
 assert(submit(1,&seq)==kOk && sessions[1].vmid==8);
 retire_all();
 IOLockLock(gCliLock); assert(session_park_locked(&sessions[1])); IOLockUnlock(gCliLock);
 const auto oldWs=sessions[1].lease;
 sessions[1].id=65; sessions[1].rootPa=0x900000; sessions[1].emitted=0; gWsId=65;
 assert(submit(1,&seq)==kOk && sessions[1].vmid==8 && sessions[1].lease.generation!=oldWs.generation);
 assert(gHardwareBindings[1].context==1); // another live logical context survives compositor replacement

 reset(); fairOn=true; autoRetire=true;
 assert(submit(0,&seq)==kOk && submit(1,&seq)==kOk);
 const auto fairWaits=waits;
 assert(submit(2,&seq)==kOk && waits>fairWaits);
 assert(gG5Since[2]==0);

 reset(); for(unsigned i=0;i<8;++i)assert(submit(i,&seq)==kOk);
 assert(submit(8,&seq)==kTimeout && doorbells==8 && stallCalls==1);
 assert(sessions[8].lease.slot==n48production::kNoHardwareSlot);

 reset(); geometryOk=false;
 assert(submit(0,&seq)==kNotReady && gHang.hung && !programCalls && !doorbells);
 assert(gHardwareBindings[0].state==n48production::SlotState::Quarantined && gHardwareBindings[0].pendingRoot==4096);

 reset(); assert(submit(1,&seq)==kOk); retire_all();
 for(unsigned i=2;i<8;++i)gHardwareBindings[i].state=n48production::SlotState::Quarantined;
 rootAck=false;
 assert(submit(2,&seq)==kNotReady && gHang.hung && doorbells==1);
 const auto &q=gHardwareBindings[1];
 assert(q.state==n48production::SlotState::Quarantined && q.root==8192 && q.pendingRoot==12288);
 IOLockLock(gCliLock);
 assert(session_flush_locked(&sessions[1])==kNotReady && session_flush_locked(&sessions[2])==kNotReady);
 assert(!session_park_locked(&sessions[1]) && !session_park_locked(&sessions[2]));
 IOLockUnlock(gCliLock);

 reset(); gEmitted=simRetired=UINT64_MAX;
 assert(submit(0,&seq)==kNoResources && !programCalls && !doorbells);
 std::puts("PASS: actual kernel binder/scheduler/ring writer/flush/park serve 64 logical records with eight VMIDs; check PM4 VMID and ownership before every doorbell, lock-free waits, stale owners, retirement, fairness, timeout, quarantine and sequence exhaustion. Simulated MMIO; live IOAccel/GPU untested.");
}
'''
pieces = [prefix,
          function('static uint32_t ring_put_locked('),
          function('__attribute__((noinline)) static void g5_fill_in_locked('),
          function('static uint32_t ring_submit_production('),
          function('static uint32_t session_bind_locked(Session *s, uint64_t retired) {'),
          function('static uint32_t session_flush_locked(Session *s) {'),
          function('static bool session_park_locked(Session *s) {'),
          suffix]
with tempfile.TemporaryDirectory(prefix='navi44-kernel-leases-') as directory:
    tmp = Path(directory)
    (tmp / 'probe.cpp').write_text('\n'.join(pieces))
    subprocess.run(['clang++', '-std=c++17', '-O1', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                    '-I'+str(headers), '-I'+str(headers.parent),
                    str(tmp / 'probe.cpp'), '-o', str(tmp / 'probe')], check=True)
    subprocess.run([str(tmp / 'probe')], check=True)
