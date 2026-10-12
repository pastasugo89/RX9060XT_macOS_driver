#!/usr/bin/env python3
"""Minimal AIR -> LLVM AMDGPU (amdhsa) lowering prototype, text level.

Input: an AIR module already disassembled by upstream llvm-dis (opaque pointers), with
triple/datalayout replaced by amdgcn ones and values named by `opt -passes=instnamer`.
Handles only compute kernels (!air.kernel) and a handful of intrinsics; anything else is
reported as unsupported. This is a feasibility probe, not a translator.
"""
import re
import sys

src = open(sys.argv[1]).read().splitlines()
md = {}
for line in src:
    m = re.match(r'^!(\d+) = (?:distinct )?!\{(.*)\}$', line)
    if m:
        md[m.group(1)] = m.group(2)
named = {}
for line in src:
    m = re.match(r'^!([A-Za-z_.][\w.]*) = !\{(.*)\}$', line)
    if m:
        named[m.group(1)] = m.group(2)

def refs(body):
    return re.findall(r'!(\d+)', body)

kernels = {}  # name -> {argidx: (kind, addrspace)}
for kref in refs(named.get('air.kernel', '')):
    body = md[kref]
    fname = re.search(r'ptr @([\w.$]+)', body).group(1)
    parts = refs(body)
    args = {}
    if len(parts) >= 2:
        for aref in refs(md[parts[1]]):
            a = md[aref]
            idx = int(re.match(r'\s*i32 (\d+)', a).group(1))
            kind = re.search(r'!"(air\.[\w]+)"', a).group(1)
            asm = re.search(r'!"air\.address_space", i32 (\d+)', a)
            args[idx] = (kind, int(asm.group(1)) if asm else None)
    kernels[fname] = args

def split_args(s):
    out, depth, cur = [], 0, ''
    for ch in s:
        if ch in '([{<':
            depth += 1
        elif ch in ')]}>':
            depth -= 1
        if ch == ',' and depth == 0:
            out.append(cur.strip()); cur = ''
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out

BUILTIN = {
    'air.thread_position_in_grid': 'tpg',
    'air.thread_index_in_threadgroup': 'tid',
    'air.thread_position_in_threadgroup': 'tid',
    'air.threadgroup_position_in_grid': 'wgid',
    'air.threads_per_threadgroup': 'wgsz',
}
need_decl = set()
dyn_lds = []
out = []
unsupported = []
pending_entry = None
for line in src:
    if line.startswith('!air.') or line.startswith('declare') and '@air.' in line:
        continue
    m = re.match(r'^define (.*?)void @([\w.$]+)\((.*)\)(.*)\{$', line)
    if m and m.group(2) in kernels:
        pre, name, arglist, post = m.groups()
        meta = kernels[name]
        keep, entry = [], []
        for i, a in enumerate(split_args(arglist)):
            kind, asp = meta.get(i, (None, None))
            vname = a.split()[-1]
            if kind in BUILTIN:
                if not a.startswith('i32 '):
                    unsupported.append(f'{name}: vector builtin {kind}')
                b = BUILTIN[kind]
                need_decl.update(['wiid', 'wgid', 'dptr'])
                entry += [
                    f'  %__wi.{i} = call i32 @llvm.amdgcn.workitem.id.x()',
                    f'  %__wg.{i} = call i32 @llvm.amdgcn.workgroup.id.x()',
                    f'  %__dp.{i} = call ptr addrspace(4) @llvm.amdgcn.dispatch.ptr()',
                    f'  %__szp.{i} = getelementptr inbounds i8, ptr addrspace(4) %__dp.{i}, i64 4',
                    f'  %__sz16.{i} = load i16, ptr addrspace(4) %__szp.{i}, align 4',
                    f'  %__sz.{i} = zext i16 %__sz16.{i} to i32',
                    f'  %__base.{i} = mul i32 %__wg.{i}, %__sz.{i}',
                ]
                expr = {'tpg': f'add i32 %__base.{i}, %__wi.{i}', 'tid': f'add i32 %__wi.{i}, 0',
                        'wgid': f'add i32 %__wg.{i}, 0', 'wgsz': f'add i32 %__sz.{i}, 0'}[b]
                entry.append(f'  {vname} = {expr}')
            elif kind == 'air.buffer' and asp == 3:
                # dynamic threadgroup memory -> extern zero-sized LDS global
                g = f'@__dyn_lds.{name}.{i}'
                dyn_lds.append(f'{g} = external addrspace(3) global [0 x i8], align 16')
                entry.append(f'  {vname} = getelementptr i8, ptr addrspace(3) {g}, i32 0')
            elif kind == 'air.buffer':
                keep.append(a.replace(' "air-buffer-no-alias"', ' noalias'))
            else:
                unsupported.append(f'{name}: arg kind {kind}')
                keep.append(a)
        out.append(f'define {pre}amdgpu_kernel void @{name}({", ".join(keep)}){post}{{')
        pending_entry = entry
        continue
    if pending_entry is not None:
        if re.match(r'^[\w.$]+:', line):
            out.append(line); out.extend(pending_entry); pending_entry = None; continue
        out.extend(pending_entry); pending_entry = None
    # intrinsic lowering
    s = line
    m = re.match(r'^(\s*)(?:tail )?call void @air\.wg\.barrier\(i32 (\d+), i32 (\d+)\).*$', s)
    if m:
        ind = m.group(1); need_decl.add('sbar')
        out += [f'{ind}fence syncscope("workgroup") release', f'{ind}call void @llvm.amdgcn.s.barrier()',
                f'{ind}fence syncscope("workgroup") acquire']
        continue
    m = re.match(r'^(\s*)(?:tail )?call void @air\.simdgroup\.barrier\(i32 (\d+), i32 (\d+)\).*$', s)
    if m:
        ind = m.group(1); need_decl.add('wbar')
        out += [f'{ind}fence syncscope("wavefront") release', f'{ind}call void @llvm.amdgcn.wave.barrier()',
                f'{ind}fence syncscope("wavefront") acquire']
        continue
    m = re.match(r'^(\s*)(%[\w.]+) = (?:tail )?call i32 @air\.atomic\.global\.(add|sub|and|or|xor|xchg|max|min)\.?([su]?)\.?i32\(ptr addrspace\(1\)[^%]*(%[\w.]+), i32 ([^,]+), i32 (\d+), i32 (\d+), i1 (true|false)\).*$', s)
    if m:
        ind, dst, op, sign, p, v, order, scope, vol = m.groups()
        op = {'max': 'umax' if sign == 'u' else 'max', 'min': 'umin' if sign == 'u' else 'min'}.get(op, op)
        vo = 'volatile ' if vol == 'true' else ''
        out.append(f'{ind}{dst} = atomicrmw {vo}{op} ptr addrspace(1) {p}, i32 {v} syncscope("agent") monotonic, align 4')
        continue
    m = re.match(r'^(\s*)(?:tail )?call void @air\.atomic\.global\.store\.i32\(ptr addrspace\(1\)[^%]*(%[\w.]+), i32 ([^,]+), i32 (\d+), i32 (\d+), i1 (true|false)\).*$', s)
    if m:
        ind, p, v, order, scope, vol = m.groups()
        vo = 'volatile ' if vol == 'true' else ''
        out.append(f'{ind}store atomic {vo}i32 {v}, ptr addrspace(1) {p} syncscope("agent") monotonic, align 4')
        continue
    for a, l in (('@air.min.u.i32', '@llvm.umin.i32'), ('@air.max.u.i32', '@llvm.umax.i32'),
                 ('@air.min.s.i32', '@llvm.smin.i32'), ('@air.max.s.i32', '@llvm.smax.i32'),
                 ('@air.fma.f32', '@llvm.fma.f32')):
        s = s.replace(a, l)
    if '@air.' in s:
        unsupported.append('intrinsic: ' + re.search(r'@air\.[\w.]+', s).group(0))
    s = s.replace('addrspace(2)', 'addrspace(4)')  # AIR constant -> AMDGPU constant
    out.append(s)

decl = {
    'wiid': 'declare i32 @llvm.amdgcn.workitem.id.x()',
    'wgid': 'declare i32 @llvm.amdgcn.workgroup.id.x()',
    'dptr': 'declare ptr addrspace(4) @llvm.amdgcn.dispatch.ptr()',
    'sbar': 'declare void @llvm.amdgcn.s.barrier()',
    'wbar': 'declare void @llvm.amdgcn.wave.barrier()',
}
out += dyn_lds + [decl[k] for k in sorted(need_decl)]
open(sys.argv[2], 'w').write('\n'.join(out) + '\n')
for u in sorted(set(unsupported)):
    print('UNSUPPORTED', u, file=sys.stderr)
print('kernels:', {k: {i: v[0] for i, v in a.items()} for k, a in kernels.items()})
