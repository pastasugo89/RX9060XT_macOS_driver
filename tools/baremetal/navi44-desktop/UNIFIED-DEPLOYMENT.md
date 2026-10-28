# Unified candidate deployment

This machine-specific candidate targets 26.6.2/25G83 and the inspected OCBOOT volume UUID. It retains the integrated Qualcomm WCN785x. It is not a claim of a finished hardware repair: black-band removal, all future shader paths, physical wireless operation, CPPC behavior and subsequent boot/login behavior remain unproven.

`prepare-unified-payload.py NEW_LOCAL_DIRECTORY` assembles the reviewed EFI, bundle24, runtime helpers, translator and review documents. `check-unified-payload.py PAYLOAD` verifies content, modes, EFI semantics and the unchanged live baseline. `install-unified-payload.py PAYLOAD` performs the same read-only preflight. None of these default commands mounts a disk, loads a driver, starts activation or reboots.

`install-unified-payload.py PAYLOAD --apply` requires root and the already writable UUID-verified EFI. It makes private verified staging and original-file backups under `/Library/Application Support/Navi44/accelerated-trial/deployment-*`. It refuses changed baselines, unsafe ancestors, insufficient staging space and conflicting EFI additions. The sequence is:

1. Copy and verify new EFI paths, retaining every old boot path.
2. Atomically exchange the Metal bundle using Darwin RENAME_SWAP; retain bundle23 in the backup directory.
3. Atomically install runtime files and verify them.
4. Atomically replace OC/config.plist.
5. Install the persistent boot job last, then verify all final hashes and modes.

No service is bootstrapped and no WindowServer signal is issued. A normal reboot is a separate user action. Copy/verification exceptions attempt restoration of the config, changed runtime files and Metal bundle. New EFI additions remain unreferenced after restoration. Externally changed targets are preserved and reported for manual review. A failed rollback is never reported as success.

After a successful installation, before activation/reboot, `install-unified-payload.py --restore-backup BACKUP_DIRECTORY` checks restoration prerequisites without writing. Adding `--apply` restores the recorded baseline, provided the original boot UUID and EFI UUID still match and activation state has not appeared. This is deliberately limited to a completed, unactivated deployment. Interrupted transactions, power loss, changed targets or restoration after reboot require inspection of journal.json, original-manifest.json, original-config.plist, original-system and metal-exchange.bundle. The journal is diagnostic metadata, not a guarantee against power loss between a write and the following journal update. Never delete a deployment directory until the candidate is validated or restoration is verified.

Tests: `test-unified-payload.py` exercises the actual staged payload and resealed semantic regressions. `test-unified-installer.py` exercises real temporary APFS directory swaps, restoration at seven injected failure phases, preservation of external changes, mode restoration, source races, conflicting EFI additions, symlinked parents and restore boot-UUID refusal. These tests make no live GPU or service calls. They do not prove FAT power-loss durability, kernel boot success, device bring-up or display correctness.
