#!/usr/bin/env python3
"""Run actual QueryInfo/session-lock code against concurrent close/reopen threads.

IOKit mutexes are represented by real host mutexes; allocators, registers and
fence counters are controlled stubs that require their designated locks. No GPU
is accessed. This does not qualify actual IOUserClient concurrency on macOS.
"""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile

root = Path(__file__).resolve().parents[3]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--kernel-source', type=Path, default=root / 'cobalt64/src/navi48-bringup')
headers = parser.parse_args().kernel_source.resolve() / 'src/amd'
source = (headers / 'native_s1c.cpp').read_text()
build = re.search(r'kN1cKextBuild = (\d+);', (headers / 'native_s1c.h').read_text()).group(1)


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
#include <atomic>
#include <cassert>
#include <condition_variable>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <mutex>
#include <thread>
#include "native_g4_pure.h"
using namespace n48native;
using namespace n48native::s1c;
using IOReturn=uint32_t;
constexpr IOReturn kIOReturnNotReady=kNotReady,kIOReturnSuccess=0;
constexpr uint32_t kN1cKextBuild=BUILD_NUMBER,kArenaBlockBytes=16384;
struct IOLock { unsigned rank; std::mutex mutex; };
static IOLock sessionLock{0,{}},registryLock{1,{}},ringLock{2,{}};
static IOLock *gCliLock=&registryLock,*gRingLock=&ringLock;
static thread_local unsigned held;
static thread_local bool queryThread;
static std::atomic<bool> watchAttempt{},queryAttempted{},pauseQuery{},queryInside{},continueQuery{},closeAttempted{},closeDone{};
static std::mutex gate;
static std::condition_variable changed;
static void signal(std::atomic<bool> &value) {
 std::lock_guard<std::mutex> guard(gate); value.store(true); changed.notify_all();
}
static void await(std::atomic<bool> &value) {
 std::unique_lock<std::mutex> guard(gate); changed.wait(guard,[&]{return value.load();});
}
static void IOLockLock(IOLock *l) {
 assert((held & ~((1u<<l->rank)-1u))==0);
 if(queryThread && l==&sessionLock && watchAttempt.load())signal(queryAttempted);
 l->mutex.lock();held|=1u<<l->rank;
}
static void IOLockUnlock(IOLock *l) {
 assert(held&(1u<<l->rank));held&=~(1u<<l->rank);l->mutex.unlock();
}
struct N1cRef {uint32_t slot,id;};
struct Session {IOLock *lock;bool open,hello,ws,app;uint32_t id,vmid,nblk;uint64_t gttUsed;};
static Session session{&sessionLock,true,true,false,true,42,9,2,5};
static Session *slot_ptr(uint32_t slot) {return slot==0?&session:nullptr;}
struct Pool {
 uint64_t total,free;bool active;
 uint64_t size() const {assert((held&3)==3);return total;}
 uint64_t bytes_free() const {assert((held&3)==3);return free;}
 bool is_inited() const {assert((held&3)==3);return active;}
};
struct IPVersion {uint32_t major,minor,rev;};
enum class IPBlock {GC};
struct IP {
 IPVersion getVersion(IPBlock) const {
  assert((held&3)==3);
  if(pauseQuery.load()) {signal(queryInside);await(continueQuery);}
  return {12,0,0};
 }
};
struct Device {IP ip;};static Device device;
struct BringupContext {Device *dev;struct {uint32_t ring_size_dwords;}cp;struct {Pool vram_alloc,vram_alloc_hi;}gmc;};
static BringupContext context{&device,{4096},{{1024,700,true},{2048,900,true}}},*gCtx=&context;
static uint64_t gWc=0x12345678abcdef12ull,gVramOthers=100;
static bool dynamic=true,hung=false,multi=true;
static bool production_on(){return dynamic;}
static bool multi_on(){return multi;}
static bool hung_now(){assert((held&3)==3);return hung;}
static uint64_t emitted_now(){assert(held==7);return 101;}
static uint64_t retired_now(uint64_t em){assert(held==7 && em==101);return 99;}
static uint64_t vram_total(){return gCtx->gmc.vram_alloc.size()+gCtx->gmc.vram_alloc_hi.size();}
struct NativeState {bool positivePass;uint32_t gate;};
static NativeState native_s1b_state(){return {true,kGateOn};}
static uint32_t read_register(){assert((held&3)==3);return 0x77;}
#define SOC15_REG_OFFSET_BIDX(...) 0u
#define RREG32(...) read_register()
'''.replace('BUILD_NUMBER', build)

body = ''.join(function(signature) for signature in (
    'static Session *sess_lock(', 'static inline void sess_unlock(', 'IOReturn n1c_query_info('))

main = r'''
static void reset() {
 assert(held==0);session={&sessionLock,true,true,false,true,42,9,2,5};
 gCtx=&context;gCliLock=&registryLock;dynamic=true;hung=false;multi=true;
 context.gmc.vram_alloc={1024,700,true};context.gmc.vram_alloc_hi={2048,900,true};gVramOthers=100;
 watchAttempt=false;queryAttempted=false;pauseQuery=false;queryInside=false;continueQuery=false;closeAttempted=false;closeDone=false;
}
static void replace_session() {
 signal(closeAttempted);IOLockLock(&sessionLock);IOLockLock(gCliLock);
 session.id=43;session.ws=true;session.app=false;session.gttUsed=700;session.nblk=7;
 context.gmc.vram_alloc.free=3;gVramOthers=200;
 IOLockUnlock(gCliLock);IOLockUnlock(&sessionLock);signal(closeDone);
}
int main() {
 n48n_info info{};
 reset();assert(n1c_query_info({0,42},&info)==0 && held==0);
 assert(info.kext_build==kN1cKextBuild && info.abi_version==1);
 assert(info.gtt_used==5 && info.pt_used==2*16384 && info.vram_vis_free==700);
 assert(info.seq_emitted==101 && info.seq_retired==99);
 assert(info.reserved[0]==0xabcdef12 && info.reserved[1]==0x12345678);
 assert(info.vmid==N48N_VMID_DYNAMIC && (info.flags&N48N_INFO_DYNAMIC_VMID));
 const auto budget=n48native::g4::budget_report(true,false,true,100,3072,1600);
 uint32_t packed[8]{};n48native::g4::budget_pack(budget,packed);
 for(unsigned i=3;i<8;++i)assert(info.reserved[i]==packed[i]);
 dynamic=false;hung=true;session.ws=true;session.app=false;context.gmc.vram_alloc_hi.active=false;
 assert(n1c_query_info({0,42},&info)==0 && held==0);
 assert(info.vmid==9 && !(info.flags&N48N_INFO_DYNAMIC_VMID) && (info.flags&N48N_INFO_HUNG));
 assert(info.vram_hi_total==0 && info.vram_hi_free==0);
 for(unsigned i=3;i<8;++i)assert(info.reserved[i]==0);
 // A stale or unready query cannot disclose the replacement owner's counters.
 reset();std::memset(&info,0xa5,sizeof(info));const n48n_info untouched=info;
 for(N1cRef bad: {N1cRef{0,0},N1cRef{0,43},N1cRef{1,42}}) {
  assert(n1c_query_info(bad,&info)==kIOReturnNotReady && held==0);
  assert(std::memcmp(&info,&untouched,sizeof(info))==0);
 }
 session.hello=false;assert(n1c_query_info({0,42},&info)==kIOReturnNotReady && held==0);
 reset();gCliLock=nullptr;assert(n1c_query_info({0,42},&info)==kIOReturnNotReady);
 reset();gCtx=nullptr;assert(n1c_query_info({0,42},&info)==kIOReturnNotReady);
 // Close/reopen wins while QueryInfo is waiting for the real session mutex.
 reset();watchAttempt=true;IOLockLock(&sessionLock);IOReturn result=0;
 std::thread waiting([&]{queryThread=true;result=n1c_query_info({0,42},&info);assert(held==0);});
 await(queryAttempted);session.id=43;session.gttUsed=900;IOLockUnlock(&sessionLock);
 waiting.join();assert(result==kIOReturnNotReady);
 // QueryInfo wins: replacement must wait until the entire old-owner snapshot ends.
 reset();pauseQuery=true;
 std::thread query([&]{queryThread=true;result=n1c_query_info({0,42},&info);assert(held==0);});
 await(queryInside);std::thread closing(replace_session);await(closeAttempted);
 assert(!closeDone.load());signal(continueQuery);query.join();closing.join();
 assert(result==0 && closeDone.load());
 assert(info.gtt_used==5 && info.pt_used==2*16384 && info.vram_vis_free==700);
 for(unsigned i=3;i<8;++i)assert(info.reserved[i]==packed[i]);
 pauseQuery=false;assert(n1c_query_info({0,42},&info)==kIOReturnNotReady);
 assert(n1c_query_info({0,43},&info)==0 && info.gtt_used==700 && info.pt_used==7*16384);
 assert(info.vram_vis_free==3 && held==0);
 std::puts("PASS: actual QueryInfo/session-lock code with real close/reopen threads; identity, allocator/budget/ring snapshots, legacy/dynamic VMIDs and error paths. MMIO/IOKit runtime untested.");
}
'''

with tempfile.TemporaryDirectory(prefix='navi44-query-info-') as directory:
    tmp = Path(directory)
    (tmp / 'probe.cpp').write_text(prefix + body + main)
    subprocess.run(['clang++', '-std=c++17', '-O1', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                    '-I'+str(headers), '-I'+str(headers.parent),
                    str(tmp / 'probe.cpp'), '-o', str(tmp / 'probe')], check=True)
    subprocess.run([str(tmp / 'probe')], check=True, timeout=15)
