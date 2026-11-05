# Codex handoff — Local Presence Miner v0.1.9

Use this source tree as the baseline. Do not revert to the older v0.1.8 source and do not recreate the qualification logic from a prompt.

The qualification implementation is already present. Your job is to verify and harden it in the Windows environment, fix only genuine defects found by tests/smoke testing, then package the Windows release.

Required checks:

1. Run Ruff and fix violations without changing qualification semantics.
2. Run the full pytest suite, including PySide6/UI tests.
3. Open an existing v0.1.8 database and verify automatic `.backup-before-v0109` creation and preservation of existing data.
4. Confirm existing leads with empty qualification snapshots recalculate on startup.
5. Run Demo Mode and confirm Sales Priority/class/confidence populate.
6. Smoke-test Lead list, Dashboard, Review Queue, Lead Detail, Contact Intelligence, Outreach, and batch outreach export.
7. Verify contact discovery recalculates qualification.
8. Verify manual competitor review recalculates qualification.
9. Confirm review count is not reintroduced as a hard minimum anywhere in qualification.
10. Build with PyInstaller and verify the EXE reports version 0.1.9.

Do not add Apollo/Hunter or automated sending as part of this verification build unless separately requested.
