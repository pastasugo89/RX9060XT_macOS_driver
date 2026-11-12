# Security policy

## Reporting a vulnerability

Please do not report security vulnerabilities in a public issue. Report them privately with GitHub's private
vulnerability reporting: open
<https://github.com/pastasugo89/RX9060XT_macOS_driver/security/advisories/new>, or use the "Report a vulnerability"
button in the Security tab of the repository.

Please include:

- the component (kext, auxiliary kext, Metal bundle, translator, RADV patches, or a tool);
- the versions involved (kext version, Metal bundle version, macOS build);
- what you found, how to reproduce it, and what an attacker could do with it;
- whether you have a fix or a patch in mind.

Remove private data from your report, such as serial numbers, paths and personal names.

If you believe the repository contains proprietary material, such as Apple or AMD binaries, AMD firmware, or personal
data, report it through the same private channel.

## What counts as a security issue

- **The kernel extensions** run in kernel context and accept requests from user space through their user clients
  (`N48N`). Memory-safety bugs, privilege escalation, and any way for an unprivileged process to crash the kernel,
  or to reach GPU memory or registers it should not reach, are security issues.
- **The Metal bundle and the translator (`n48xlate`)** process shader input from applications. Malformed input that
  corrupts memory is a security issue.
- **Reliability problems** (freezes, hangs, GPU resets, display glitches) are not security issues, unless an
  unprivileged user or a remote party can trigger them. Report them as ordinary bugs with the bug report template.

## Supported versions

Only the latest commit on the default branch is supported. The project is experimental, and fixes are not backported to
earlier kernel or bundle versions.

## Response

This is a one-person project run in spare time. The maintainer aims to acknowledge every report, but cannot promise a
response time.

## Disclosure

Please give the maintainer a reasonable time to prepare a fix before you disclose the problem publicly. If you want
credit in the fix, say so in your report.
