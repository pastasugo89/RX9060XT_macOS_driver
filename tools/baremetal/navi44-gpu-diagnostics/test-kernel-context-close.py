#!/usr/bin/env python3
"""Run the actual kernel close body and retirement callbacks with controlled IO.

No kext is loaded. MMIO, locks, waits and allocation releases are recorded stubs;
the real close body must order both address-space invalidations before freeing.
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
start = source.index('struct ContextRetireEnv {')
end = source.index('\n// ---- BOs', start)
close = source[start:end]
prefix = r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <vector>
#include "production_context_retire.h"
#include "native_g2_pure.h"
using namespace n48native::s1c;
struct IOLock { bool held; };
static IOLock registryLock{}, sessionLock{};
static IOLock *gCliLock=&registryLock;
static void IOLockLock(IOLock *l) { assert(!l->held); l->held=true; }
static void IOLockUnlock(IOLock *l) { assert(l->held); l->held=false; }
enum { kBoGtt=3, kBoHost=4, kRelClosing=2 };
struct Bo { uint8_t kind; uint64_t size; };
struct Session {
 IOLock *lock; uint32_t id,slot,vmid; bool ws,open,hello;
 uint8_t boUsed[N48N_MAX_BOS]; Bo bo[N48N_MAX_BOS];
 FenceSlot fslot[N48N_FENCE_SLOTS]; uint64_t emitted; uint32_t ptPages;
};
static Session session;
struct N1cRef { uint32_t slot,id; };
struct Device {};
struct Context { Device *dev; struct { uint64_t gart_pt_vram_offset; } gmc; };
static Device device;
static Context context{&device,{0x10000}}, *gCtx=&context;
struct FenceWindow { uint64_t gartOff; };
static FenceWindow gWin[8];
static struct { uint64_t pa; } gPark{0x8000};
static uint32_t gScanOwner,gSessWs,gWsId,gOpenFlag;
static uint8_t gSlotState[8];
static bool multiProfile,workReady,rootAck,fenceAck,isHung,hadFences,privateParked,fenceFlushed;
static unsigned privateCalls,fenceCalls,cleared,released,ptReleased;
enum Event { PARK, CLEAR, HDP, FENCE_FLUSH, BO_FREE, PT_FREE };
static std::vector<Event> events;
static bool multi_on() { return multiProfile; }
static bool hung_now() { return isHung; }
static bool own_wait(Session *s) { assert(s==&session); assert(!registryLock.held); return workReady; }
static Session *sess_lock(const N1cRef &r,bool hello) {
 (void)hello; if(!session.open || r.id!=session.id)return nullptr;
 IOLockLock(session.lock); return &session;
}
static void scan_teardown(Session *,const char *,uint64_t r[2]) { r[0]=1; r[1]=0; }
namespace n48dcn { static void modeHoldSessionClosed(uint32_t) {} }
static uint32_t program_root(uint32_t vmid,uint64_t root) {
 assert(sessionLock.held && registryLock.held && workReady && !isHung);
 assert(vmid==session.vmid && root==gPark.pa); ++privateCalls; events.push_back(PARK);
 if(!rootAck) { isHung=true; return kTimeout; } privateParked=true; return kOk;
}
static bool session_park_locked(Session *s) { return program_root(s->vmid,gPark.pa)==kOk; }
static void bar0_memcpy_to_vram(Device &,uint64_t offset,const void *data,size_t size) {
 assert(privateParked && rootAck && sessionLock.held && registryLock.held);
 assert(offset>=context.gmc.gart_pt_vram_offset && size==8 && *static_cast<const uint64_t *>(data)==0);
 assert(!released && !ptReleased); ++cleared; events.push_back(CLEAR);
}
static void amdgpu_hdp_flush(Device &) { assert(cleared && !released && !ptReleased); events.push_back(HDP); }
static uint32_t flush_vmid(uint32_t vmid) {
 assert(vmid==0 && cleared && !events.empty() && events.back()==HDP); ++fenceCalls; events.push_back(FENCE_FLUSH);
 if(!fenceAck) { isHung=true; return kTimeout; } fenceFlushed=true; return kOk;
}
static void assert_can_free() {
 assert(privateParked && rootAck && workReady && (!hadFences || fenceFlushed));
 assert(sessionLock.held && registryLock.held);
 for(const auto &f:session.fslot)assert(!f.used);
}
static void bo_release(Session *s,uint32_t h,int mode) {
 assert(s==&session && mode==kRelClosing && s->boUsed[h]); assert_can_free();
 s->boUsed[h]=0; ++released; events.push_back(BO_FREE);
}
static void pt_release_blocks(Session *s) {
 assert(s==&session && released==3); assert_can_free(); ++ptReleased; events.push_back(PT_FREE);
}
static bool OSCompareAndSwap(uint32_t before,uint32_t after,uint32_t *p) {
 if(*p!=before)return false; *p=after; return true;
}
static void record_log(const char *,...) {}
#define N1C_LOG(...) record_log(__VA_ARGS__)
'''
suffix = r'''
int main() {
 unsigned cases=0;
 for(int multi=0;multi<2;multi++)for(int ws=0;ws<2;ws++)for(int fences=0;fences<2;fences++)for(int fault=0;fault<4;fault++) {
  std::memset(&session,0,sizeof session); std::memset(gSlotState,0,sizeof gSlotState);
  multiProfile=multi; workReady=fault!=1; rootAck=fault!=2; fenceAck=fault!=3;
  hadFences=fences; privateParked=fenceFlushed=isHung=false;
  privateCalls=fenceCalls=cleared=released=ptReleased=0; events.clear();
  session.lock=&sessionLock; session.id=91; session.vmid=8; session.ws=ws; session.open=session.hello=true;
  session.emitted=12; session.ptPages=4; gScanOwner=gWsId=91; gSessWs=ws; gOpenFlag=1;
  for(unsigned i=1;i<=3;i++) { session.boUsed[i]=1; session.bo[i]={static_cast<uint8_t>(i==1?kBoGtt:i==2?kBoHost:1),4096}; }
  if(fences) { session.fslot[0]={1,0,1}; session.fslot[3]={1,1,1}; }
  n1c_close({0,91},"test");
  const bool success=workReady && rootAck && (!fences || fenceAck);
  assert(!registryLock.held && !sessionLock.held && !session.open && !session.hello && !gOpenFlag);
  assert(gSlotState[0]==(success?n48native::g2::kSlotFree:n48native::g2::kSlotDead));
  assert(released==(success?3u:0u) && ptReleased==static_cast<unsigned>(success));
  assert(privateCalls==static_cast<unsigned>(workReady));
  assert(fenceCalls==static_cast<unsigned>(workReady && rootAck && fences));
  assert(cleared==(workReady && rootAck && fences?2u:0u));
  if(!success) { for(unsigned i=1;i<=3;i++)assert(session.boUsed[i]); if(fences)assert(session.fslot[0].used && session.fslot[3].used); }
  const auto before=events.size(); n1c_close({0,91},"duplicate"); assert(events.size()==before);
  ++cases;
 }
 std::printf("PASS: %u actual kernel close paths; private root and VMID-0 ACK precede every free, failed retirement quarantines resources, duplicate close is inert. MMIO is simulated.\n",cases);
}
'''
with tempfile.TemporaryDirectory(prefix='navi44-kernel-close-') as directory:
    tmp = Path(directory)
    (tmp / 'probe.cpp').write_text(prefix + close + suffix)
    subprocess.run(['clang++', '-std=c++17', '-O1', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                    '-I'+str(headers), '-I'+str(headers.parent), str(tmp / 'probe.cpp'), '-o', str(tmp / 'probe')], check=True)
    subprocess.run([str(tmp / 'probe')], check=True)
