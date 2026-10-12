target triple = "amdgcn-amd-amdpal"
; Same as a "fragment-like" AMDGPU_PS entry to show graphics calling convention
define amdgpu_ps <4 x float> @ps_main(<2 x float> inreg %unused, float %x, float %y) {
  %r = insertelement <4 x float> poison, float %x, i32 0
  %g = insertelement <4 x float> %r, float %y, i32 1
  %b = insertelement <4 x float> %g, float 0.0, i32 2
  %a = insertelement <4 x float> %b, float 1.0, i32 3
  ret <4 x float> %a
}

