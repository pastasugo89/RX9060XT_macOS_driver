#include <cassert>
#include <cstdio>
#include "production_vm_lease_pure.h"
using namespace n48production;

static Ticket bind(Slot *slots, Request r, uint64_t retired) {
    Plan p = plan(slots, r, retired);
    assert(p.decision == Decision::Bind);
    Ticket t{};
    assert(claim(slots, p, r, retired, &t));
    assert(finish(slots, t, true));
    return t;
}

int main() {
    Slot slots[kHardwareSlots]{};
    assert(vmid(0) == 8 && vmid(7) == 15 && vmid(8) == UINT32_MAX);
    assert(plan(slots, {0,4096,false}, 0).decision == Decision::Invalid);
    assert(plan(slots, {1,4097,false}, 0).decision == Decision::Invalid);
    Ticket compositor = bind(slots, {1,4096,true}, 0);
    assert(submitted(slots, compositor, 1));
    Ticket apps[7]{};
    for (unsigned i=0;i<7;++i) {
        apps[i]=bind(slots,{i+2,(i+2)*4096ull,false},0);
        assert(apps[i].slot != 0);
        assert(submitted(slots,apps[i],i+2));
    }
    // All app hardware busy: wait for a fence; never reclaim the compositor.
    auto waiting=plan(slots,{100,409600,false},1);
    assert(waiting.decision==Decision::WaitForRetirement && waiting.waitSequence==2);
    auto wrongRole=plan(slots,{1,4096,false},8);
    assert(wrongRole.decision==Decision::Invalid);
    Ticket ninth=bind(slots,{100,409600,false},2);
    assert(ninth.slot==apps[0].slot);
    assert(!submitted(slots,apps[0],9)); // stale owner cannot submit after a rebind
    assert(!finish(slots,apps[0],true));
    assert(submitted(slots,ninth,9));
    Ticket parked{};
    assert(!begin_release(slots,ninth,8,&parked));
    assert(begin_release(slots,ninth,9,&parked));
    assert(slots[ninth.slot].state==SlotState::Binding);
    assert(slots[ninth.slot].root==409600); // old root retained until park ACK
    assert(!submitted(slots,ninth,10));
    assert(finish(slots,parked,true));
    assert(slots[ninth.slot].state==SlotState::Empty);
    assert(!finish(slots,parked,true)); // duplicate callback rejected

    // A stale decision and two concurrent acquisitions cannot steal a binding.
    Request a{101,413696,false}, b{102,417792,false};
    auto pa=plan(slots,a,9), pb=plan(slots,b,9);
    Ticket ta{},tb{};
    assert(claim(slots,pa,a,9,&ta));
    assert(!claim(slots,pb,b,9,&tb));
    assert(plan(slots,a,9).decision==Decision::BusyBinding);
    assert(finish(slots,ta,false));
    assert(slots[ta.slot].state==SlotState::Quarantined);
    assert(slots[ta.slot].pendingRoot==a.root);
    assert(plan(slots,a,9).decision==Decision::Unavailable);

    // Pending owners must be found before a lower-numbered empty slot is picked.
    Slot pending[kHardwareSlots]{};
    pending[4]={SlotState::Binding,55,0x10000,0,5,56,0x20000};
    assert(plan(pending,{56,0x20000,false},0).decision==Decision::BusyBinding);
    assert(plan(pending,{56,0x30000,false},0).decision==Decision::Invalid);
    pending[4].state=SlotState::Quarantined;
    assert(plan(pending,{56,0x20000,false},0).decision==Decision::Unavailable);

    // One thousand different logical contexts, seven app hardware bindings.
    Slot stress[kHardwareSlots]{};
    auto ws=bind(stress,{1,4096,true},0);
    uint64_t retired=0;
    for(uint64_t i=2;i<1002;++i) {
        auto t=bind(stress,{i,i*4096,false},retired);
        assert(submitted(stress,t,i));
        retired=i;
        assert(stress[0].context==ws.context && stress[0].generation==ws.generation);
    }
    // Uncertain MMIO means quarantine, including retaining both page tables.
    Slot failure[kHardwareSlots]{};
    auto old=bind(failure,{2,8192,false},0);
    for(unsigned i=2;i<kHardwareSlots;++i) failure[i].state=SlotState::Quarantined;
    assert(submitted(failure,old,1));
    Request replacement{3,12288,false};
    Ticket update{};
    auto p=plan(failure,replacement,1);
    assert(claim(failure,p,replacement,1,&update));
    assert(finish(failure,update,false));
    assert(failure[1].root==8192 && failure[1].pendingRoot==12288);
    assert(plan(failure,{4,16384,false},1).decision==Decision::Unavailable);
    puts("PASS: VMID leasing policy, 1000 logical contexts, retirement, stale tickets, concurrent binding, compositor reservation, park ACK and quarantine. Kernel integration not tested.");
}
