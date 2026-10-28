# GPU application path in the unified candidate

The actual boot-args have no navi48-apps or navi48-multisession gates. Live logs show declined APP probes from Warp's `stable` executable, Terminal, Finder, system UI services and others. This proves that desktop composition working in WindowServer does not establish application Metal acceleration. It does not quantify how much of the reported sluggishness this causes.

The prepared profile enables Cobalt's existing navi48-multisession=1, navi48-apps=1 and navi48-g5=1. G5 retains its default one-app-job credit, ring reserve and WindowServer priority; its waiting path runs outside the ring lock. No scheduler constants, VMID count, budgets, selector restrictions or recovery/strike policy are changed. Ordinary applications cannot access display ownership, register reads or nub publish/withdraw through this route.

The upstream allowlist is empty at every boot. The new seed-gpu-apps.py therefore runs from the guarded boot job after registry readiness and before adopting/arming the display. It requires root, no logged-in user and all three gates. The thirty distinct executable-name keys cover names actually seen in the declined-probe log, the four installed apps, Brave's helper and mtlprobe. Names are truncated to16bytes and hashed by the existing kernel policy: this is containment for honest programs, not a code-signing boundary. No network password or private document is involved. Unknown applications remain outside that list; admission is not proof of functional rendering.

The seeder uses only the existing appallow add/list/remove commands; it does not submit GPU work. It checks capacity before changing anything, verifies the whole resulting list and, on a failure, removes only entries attempted by this invocation and verifies the original list. A failed restoration is reported explicitly. Nine host fault/behavior tests pass, including every partial-add failure, missing writes, capacity/OFF refusal, idempotence and restoration failure. No seeding was performed in the running kernel.

Four upstream session/admission/scheduling/accelerator-route suites pass under ASan+UBSan: G2=250checks, G4=11011, G5=1871, G6=1006 (14138total). Source-pin checks ran with the correct cobalt64 root argument. The first invocation used the wrong source root and failed its file-reading assertions; those were invocation failures, corrected before interpreting results. Eight session/admission/policy/client source files in the compiled bringup-model staging are byte-identical to the audited source. These are host tests, not proof of real concurrent GPU/VMID behavior on Navi44.

Run the seeder tests without root:

```sh
python3 tools/baremetal/navi44-desktop/test-seed-gpu-apps.py
```

Local EFI: research/builds/macos-20261028/unified/efi-gpuapps-candidate/EFI. It preserves the combined GPU-name/USB/S5/Qualcomm/CPPC candidate and adds only the three gates. ocvalidate1.0.8 passes. To deploy this profile later, the updated guarded boot script, seed-gpu-apps.py and app-allowlist.json must all be installed together. Neither the EFI nor the new job has been installed/armed yet.

Limits still apply: four concurrent native session slots (one reserved for WindowServer), a shared app VRAM budget/visible-pool cap, three-strike refusal and a finite shader translator. An admitted app may still fail resource allocation or hit unsupported shaders/APIs; this is not a claim that every application is accelerated or all stutter is eliminated. The next hardware test must measure actual app admission, rendering/readback, session cleanup and desktop responsiveness concurrently. Remaining bands/magenta cannot be declared fixed by these gate changes.

Deployment audit also found that RDNA4FB's EFI entry is disabled: the live framebuffer comes from /Library/Extensions/RDNA4FB-0.0.8-n44.kext in the auxiliary collection, whose binary still matches the old f51ac257... baseline. Merely putting the model-corrected framebuffer binary into the disabled EFI entry does not deploy that correction. Resolve its actual activation path before claiming the name fix is ready.
