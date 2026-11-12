# Contributing

Thank you for looking at this project. It is an experimental GPU driver for one card (RX 9060 XT, Navi 44) on one
operating system (macOS Tahoe 26.6.2). Most of the work needs real hardware, so the review and merge speed depends on
what can be tested. Please read the [Safety section of the README](README.md#safety) before you run anything from this
repository.

## Ground rules

- **Do not submit Apple or AMD material.** That means Apple binaries, frameworks, installers and shader compiler output;
  files extracted from macOS; AMD firmware (`*.bin` firmware blobs, VBIOS images); and any file derived from Apple's
  software, such as shader captures and SPIR-V or AIR translations made from them. The project's `.gitignore` lists the
  paths that must stay out of git.
- **Do not submit private data.** Remove serial numbers, `MLB`, `ROM` and `SystemUUID` values, Wi-Fi network names, MAC and
  IP addresses, home-directory paths, and personal names or e-mail addresses from logs, configuration files and
  screenshots. Replace them with placeholders.
- **Copy code only when the licence allows it.** Keep the original header and licence text. Name the source and its
  licence in the pull request. Do not submit code derived from projects whose licences forbid derivative works or
  restrict use with AI tools. Examples are NullMoth's plugin code (PolyForm Noncommercial) and the ChefKiss projects
  NootRX and NootedRed.
- **Tell us about safety.** A change that writes GPU registers, changes clock or power states, or touches the boot path
  or EFI must say so in the pull request, with the rollback plan. See [Safety-relevant changes](#safety-relevant-changes).

## Development setup

The build needs a macOS machine with the Xcode Command Line Tools. The Linux side needs `clang`, `python3`, and `zstd`
for some optional firmware checks. Fetch every external project yourself. Nothing from the list in the
[README](README.md#building) is vendored.

- Keep build output out of the tree, or in the ignored `build/` directories. Do not commit build output.
- Use a scratch directory for test output, for example `$TMPDIR/some-name`, not a directory inside the repository.
- Do not run `kmutil install --update-all`. The auxiliary kext guide explains why.
- Do not load a kext for the first time on a machine you cannot restart.

## Code style

- Match the file you change. Do not reformat existing lines in a change that does not need it. The kernel extension
  sources mix tabs and spaces, and `navi48metal/Navi48Device.m` uses four spaces, so follow the file in front of you.
- Python and shell scripts should match the existing script in the same directory, for example `set -e` or `set -eu` in
  shell.
- Keep a commit to one topic. Start the subject with the component when that helps. The history already uses prefixes
  such as `STATO:` and `Report:`.
- Write comments that say why, not what. Existing code refers to build numbers and test names. Keep that convention in the
  files you change.
- New documents, issues and pull request text are written in English. Existing Italian documents stay in Italian. Add an
  English summary to a new document if it is useful to readers.

## Tests

Run the tests that match the files you changed, and say in the pull request which ones you ran and what they showed.
Some tests need firmware or captures that are not in the repository. Those tests fail or skip, and the output says so.

### Linux host tests

Run from the repository root.

- `tools/hosttests/run.sh` builds and runs the host tests of the kext code. It reads the dumps in `research/hw_dump/`
  and the firmware in `/usr/lib/firmware` when present. Firmware checks skip when the files are absent.
- `python3 tools/hosttests/run-cobalt64-tests.py [--asic navi44|navi48] [filter ...]` runs the Cobalt64 test files in
  `cobalt64/src/navi48-bringup/tests/` and `cobalt64/src/dcn41/tests/`. Each result is PASS, FAIL, BUILD or NOCMD.
  It compares the results with `tools/hosttests/cobalt64-baseline.txt`. A test that passed in the baseline and now
  fails is a regression, and the script exits with status 1. Some BUILD and FAIL entries are expected, because some files
  are not published.
- `tools/linux-check-kext.sh [file.cpp ...]` checks that the kext sources compile with `-fsyntax-only`. Set `MKSDK` to
  the `MacKernelSDK` headers, which come with the RDNA4FB clone.
- `tools/mesa-shim-check.sh` checks RADV's gfx1200 record. It needs a Mesa tree with the patches applied (see the header
  of the script).

### macOS host tests and builds

Run from `cobalt64/`, unless a path says otherwise.

- `make -C src/navi48-bringup MKSDK=/path/to/MacKernelSDK all` builds the kext. Check the result as described in
  `BUILDING.md`.
- `make -C src/xlat12 kextcheck` checks the translator for the kext. `make -C src/xlat12 test` runs its self-tests. Those
  self-tests need captured Apple command streams, which are not in the repository, so they report a failure without them.
- `python3 tools/dcn41/build.py kextcheck` builds the display helper check.
- `tools/conductor/suites.sh <tree-root> <out-dir>` runs every host suite in `src/navi48-bringup/tests/`, using the compile
  line in each file's header. Use a scratch `<out-dir>`.
- `make -C tools/native/navi48accel/tests all` (and `plants`) runs the tests of the auxiliary kext.
- `tools/pc/autoarm/test/run-tests.sh` runs the fake-environment tests of the autoarm scripts. It runs on a macOS host only.

### Hardware tests

A hardware test is a test run on the GPU. Only report one you ran. Say which build and which macOS build you used,
and what you saw. Do not claim a result you did not observe.

## Hardware reports

Hardware results are the most useful contribution at this stage.

- If you have a **RX 9060 XT (Navi 44)** and you tried a build, open a
  [bug report](.github/ISSUE_TEMPLATE/bug_report.yml) for a failure, or a
  [hardware report](.github/ISSUE_TEMPLATE/hardware_report.yml) for a result.
- If you have **another Navi 44 or Navi 48 card**, use the
  [hardware report](.github/ISSUE_TEMPLATE/hardware_report.yml) template. Say which card, board and monitor you used.
- Include the build versions: the kext version, the Metal bundle version, the auxiliary kext version, the RDNA4FB
  version, the OpenCore version, the macOS build and the boot-arguments.
- Redact the logs as described in [Ground rules](#ground-rules). Attach a short excerpt rather than a whole system log.
- A negative result is useful. A freeze, a black screen or a failed boot is a result.

## AI-assisted contributions

AI-assisted contributions are allowed. You must:

- disclose in the pull request which parts were produced or changed with an AI tool;
- read, understand and test the change yourself, and be able to answer questions about it;
- check that the output does not reproduce third-party code under a licence that does not fit this project;
- give an AI tool only redacted excerpts. Do not paste Apple binaries, AMD firmware or private logs into it.

## Licence and sign-off

Your contribution is licensed under the licence of the directory it changes. The table in the
[README](README.md#licences) shows which licence applies to each part.

Please sign off each commit with `git commit -s`. The sign-off certifies the
[Developer Certificate of Origin](https://developercertificate.org). It is requested, not enforced by a bot.

## Safety-relevant changes

A change needs a **Safety impact** section in its pull request if it:

- writes GPU registers, or changes firmware or ring buffers;
- changes clock, voltage, power-limit or fan state, or the thermal watchdog;
- changes the boot path, the OpenCore configuration, the EFI layout or the kext loading order;
- changes the user-client interface between the kext, RADV and the Metal bundle.

In that section, say what could go wrong, how the change fails safe, and how to roll it back. The maintainer may test
such a change on hardware before merging. There is no continuous integration for hardware.

## Pull requests and issues

- Search the existing issues before you open a new one.
- Use the issue templates. They ask for the information needed to reproduce a problem.
- Keep pull requests small, and describe the change and its test results in the template.
- Update the documentation when behaviour changes. This includes the status table in [README.md](README.md) and
  [docs/STATUS.md](docs/STATUS.md).

## Conduct and security

- Please follow the [Code of Conduct](CODE_OF_CONDUCT.md) in issues, pull requests and discussions.
- Report security problems privately, as described in [SECURITY.md](SECURITY.md). Do not open a public issue for them.
