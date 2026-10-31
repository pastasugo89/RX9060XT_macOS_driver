#!/usr/bin/env python3
"""Exercise the actual normal BO release block with failed TLB acknowledgments.

MMIO, backing allocations and descriptors are tracked stubs. This checks that
uncertain translation cannot recycle GTT, host imports or either VRAM pool.
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
marker = '} else if (mode == kRelNormal) {'
start = source.index(marker, source.index('static void bo_release(Session *s, uint32_t h, RelMode mode) {')) + len(marker)
end = source.index('\n    } else {', start)
block = source[start:end]
prefix = r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include "native_s1c_pure.h"
#include "native_hostimport_pure.h"
using namespace n48native::s1c;
enum { kBoVis=1,kBoHi=2,kBoGtt=3,kBoHost=4 };
static unsigned freed,budgetFreed,sysFreed,hostFreed,descriptorReleased,unmapped,cleared,privateFlush,fenceFlush;
static bool privateAck,fenceAck;
struct Descriptor { void release() { ++descriptorReleased; } };
struct Allocation {};
struct Pool { void free(Allocation &) { ++freed; } };
struct Bo { unsigned kind; Descriptor *vmd; int sm; Allocation a; };
struct Session { uint64_t rootPa; VaEnt maps[kMaxMaps]; FenceSlot fslot[N48N_FENCE_SLOTS]; unsigned vmid; };
static Session session;
struct PtMem { Session *s; };
struct Window { uint64_t gartOff; };
struct Device {};
struct Context { Device *dev; struct { Pool vram_alloc,vram_alloc_hi; uint64_t gart_pt_vram_offset; } gmc; };
static Device device;
static Context context{&device,{{},{},0x10000}}, *gCtx=&context;
static void pt_unmap(uint64_t,uint64_t,uint64_t,PtMem &) { ++unmapped; }
static void amdgpu_hdp_flush(Device &) {}
static uint32_t flush_vmid(unsigned vmid) {
 if(!vmid) { assert(cleared); ++fenceFlush; return fenceAck?kOk:kTimeout; }
 assert(vmid==8 && unmapped); ++privateFlush; return privateAck?kOk:kTimeout;
}
static uint32_t session_flush_locked(Session *s) { return flush_vmid(s->vmid); }
static void bar0_memcpy_to_vram(Device &,uint64_t,const void *p,size_t size) { assert(size==8 && !*static_cast<const uint64_t *>(p)); ++cleared; }
static void budget_release(Bo &) { ++budgetFreed; }
static void sys_release(Bo &) { ++sysFreed; }
static void host_release(Bo &) { ++hostFreed; }
static void sysmem_free(int) { ++freed; }
static void normal_release(Session *s,Bo &b,uint32_t h,const Window &win) {
'''
suffix = r'''
}
int main() {
 unsigned tested=0;
 for(unsigned kind=kBoVis;kind<=kBoHost;++kind)for(unsigned mapped=0;mapped<2;++mapped)
 for(unsigned fences=0;fences<(kind==kBoGtt?2u:1u);++fences)
 for(unsigned ack=0;ack<4;++ack) {
  std::memset(&session,0,sizeof session); session.rootPa=0x1000; session.vmid=8;
  if(mapped)session.maps[0]={0x10000,4096,0,5,0};
  if(fences)session.fslot[0]={5,0,1};
  privateAck=ack&1; fenceAck=ack&2;
  freed=budgetFreed=sysFreed=hostFreed=descriptorReleased=unmapped=cleared=privateFlush=fenceFlush=0;
  Descriptor descriptor;
  Bo b{kind,&descriptor,0,{}};
  normal_release(&session,b,5,Window{0});
  const bool releasable=(!mapped || privateAck) && (!fences || fenceAck);
  assert(unmapped==mapped && privateFlush==mapped && fenceFlush==fences && cleared==fences);
  assert(descriptorReleased==1 && b.vmd==nullptr);
  assert(freed==static_cast<unsigned>(releasable && kind!=kBoHost));
  assert(hostFreed==static_cast<unsigned>(releasable && kind==kBoHost));
  assert(sysFreed==static_cast<unsigned>(releasable && (kind==kBoGtt || kind==kBoHost)));
  assert(budgetFreed==static_cast<unsigned>(releasable && (kind==kBoVis || kind==kBoHi)));
  ++tested;
 }
 std::printf("PASS: %u actual BO-release paths; failed private or fence TLB ACK retains backing memory and budgets in both VRAM pools, GTT and host imports. MMIO is simulated.\n",tested);
}
'''
with tempfile.TemporaryDirectory(prefix='navi44-kernel-bo-release-') as directory:
    tmp = Path(directory)
    (tmp / 'probe.cpp').write_text(prefix + block + suffix)
    subprocess.run(['clang++', '-std=c++17', '-O1', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                    '-I'+str(headers), '-I'+str(headers.parent),
                    str(tmp / 'probe.cpp'), '-o', str(tmp / 'probe')], check=True)
    subprocess.run([str(tmp / 'probe')], check=True)
