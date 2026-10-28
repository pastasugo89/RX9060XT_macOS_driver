# Persistent guarded activation

The staged org.navi44.accelerated-trial LaunchDaemon retains its label for compatibility, but is now persistent across reboots: it is no longer moved to a consumed filename. RunAtLoad=true and KeepAlive=false launch it once on each boot; root/wheel are explicit. This is prepared source only, not a job installed or started in the running session.

boot-state.py records one attempt per kernel boot UUID in the root-owned application-support directory. Its state is independent of shader caches and /tmp, so rebooting cannot erase a failed attempt:

| Previous phase | Same boot | New boot |
|---|---|---|
| absent | Begin pending | Begin pending |
| stable | Refuse another attempt | Begin pending |
| stopped (SIGTERM) | Refuse another attempt | Begin pending |
| pending | Refuse | Refuse; reviewed reset required |
| failed | Refuse | Refuse; reviewed reset required |

The latch is written and fsynced before any guard removal or GPU/display change. A nonblocking file lock serializes state transactions; metadata checks reject symlinks, hard links, unsafe modes/ownership, malformed/oversized state and unsafe parent directories. Replacement is atomic and preserves pending state if writing fails. A profile-name change alone cannot clear failure. No automatic reset command is exposed by the helper. A reviewed deployment can archive/reset state only after investigating the previous failure.

The desktop script records failed on an error/interrupt and stopped on an orderly SIGTERM. stopped is not a successful rendering result. After a stable login transition it records desktop-stable-120s. If no user logs in during the five-minute observation, it retains acceleration and records only login-window-stable-300s: it does not claim that the user transition was tested. A crash/change of WindowServer PID during that interval still fails the attempt.

Recovery disarms the pipe, restores the software-selection metadata and sets the kill flag. It restarts WindowServer only while no user session is present. With an active user it records deferred recovery and never forces a logout; a session restart may still be needed to finish returning an existing process to software. No reboot, logout or WindowServer signal was issued while preparing/testing this revision.

An existing APP/disabled marker prevents activation. Existing L1/no-flip kill files remain respected; only the recognized root-owned empty L1 marker can be cleared after the latch grants a new attempt. Root flag creation uses exclusive noclobber creation and never chmods/touches a foreign/symlink target. Log directory/file metadata is checked before root redirection.

Validation:17host state-machine/ownership/concurrency/write-fault tests;4extracted recovery-function tests under Bash strict mode using fake GPU tools, fake login state and intercepted signals;4root-only flag tests confined to a temporary directory (creation/idempotence, symlink target preservation, foreign ownership and nonempty/hard-linked files). No test invokes the actual GPU tools or live WindowServer. bash syntax and launchd plist lint pass. These tests cover control flow and filesystem behavior, not real launchd timing, graphics correctness or hardware recovery.

Remaining startup constraint: activation deliberately refuses an already logged-in user and a login racing startup checks. It will not interrupt that session to obtain acceleration. The first unified hardware test must leave the login window until the GPU restart/readiness sequence has finished. Fast-login behavior and persistent activation over multiple real boots still require validation; this candidate must not be described as a definitive, verified startup solution yet.
