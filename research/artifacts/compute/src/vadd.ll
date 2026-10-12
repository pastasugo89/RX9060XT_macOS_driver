; Minimal hand-written LLVM IR compute kernel for amdgcn-amd-amdhsa
target triple = "amdgcn-amd-amdhsa"

declare i32 @llvm.amdgcn.workitem.id.x()
declare i32 @llvm.amdgcn.workgroup.id.x()
declare ptr addrspace(4) @llvm.amdgcn.dispatch.ptr()

define amdgpu_kernel void @vadd_ir(ptr addrspace(1) noalias readonly %a,
                                   ptr addrspace(1) noalias readonly %b,
                                   ptr addrspace(1) noalias %c, i32 %n)
    "amdgpu-flat-work-group-size"="1,256" {
entry:
  %tid = call i32 @llvm.amdgcn.workitem.id.x()
  %gid = call i32 @llvm.amdgcn.workgroup.id.x()
  %dp = call ptr addrspace(4) @llvm.amdgcn.dispatch.ptr()
  ; hsa_kernel_dispatch_packet_t.workgroup_size_x is a u16 at byte offset 4
  %wgsz.p = getelementptr inbounds i8, ptr addrspace(4) %dp, i64 4
  %wgsz16 = load i16, ptr addrspace(4) %wgsz.p, align 4
  %wgsz = zext i16 %wgsz16 to i32
  %base = mul i32 %gid, %wgsz
  %i = add i32 %base, %tid
  %inb = icmp ult i32 %i, %n
  br i1 %inb, label %body, label %exit
body:
  %idx = zext i32 %i to i64
  %pa = getelementptr inbounds float, ptr addrspace(1) %a, i64 %idx
  %pb = getelementptr inbounds float, ptr addrspace(1) %b, i64 %idx
  %pc = getelementptr inbounds float, ptr addrspace(1) %c, i64 %idx
  %va = load float, ptr addrspace(1) %pa, align 4
  %vb = load float, ptr addrspace(1) %pb, align 4
  %s = fadd float %va, %vb
  store float %s, ptr addrspace(1) %pc, align 4
  br label %exit
exit:
  ret void
}

; Same as a "fragment-like" AMDGPU_PS entry to show graphics calling convention
define amdgpu_ps <4 x float> @ps_main(<2 x float> inreg %unused, float %x, float %y) {
  %r = insertelement <4 x float> poison, float %x, i32 0
  %g = insertelement <4 x float> %r, float %y, i32 1
  %b = insertelement <4 x float> %g, float 0.0, i32 2
  %a = insertelement <4 x float> %b, float 1.0, i32 3
  ret <4 x float> %a
}

!llvm.module.flags = !{!0}
!0 = !{i32 1, !"amdhsa_code_object_version", i32 600}
