# Codex Handoff — Preserve and Verify Outreach Engine Patch

Use this source tree as the new baseline. Do **not** recreate the outreach engine from a prompt and do not revert to an older v0.1.8 tree.

First inspect `OUTREACH_ENGINE_PATCH_NOTES.md` and the actual diff.

Your immediate task is verification/build hardening, not redesign:

1. Run Ruff and fix only legitimate issues without changing intended behavior.
2. Install/use the project's normal PySide6 Windows environment.
3. Run the complete automated test suite.
4. Launch at 1366x768 and 1920x1080.
5. Verify a fresh database creates `contact_points` safely.
6. Verify an existing v0.1.8 database opens without data loss.
7. In Lead Detail, test `Contact Intelligence` with:
   - no website + Google phone
   - website with public generic email
   - website with multiple emails
   - email + phone and switching preferred route
   - contact-page-only case
   - no usable public contact data
   - suppressed lead
8. Verify `Discover / Refresh Public Contacts` does not freeze the UI.
9. Verify Outreach -> `Discover Public Contacts` works for a user-chosen batch size.
10. Verify `outreach-ready.csv` contains only verified/approved/contactable leads.
11. Verify `outreach-needs-review.csv` gives a correct human-readable reason for every skipped lead.
12. Verify suppression by a discovered email suppresses the lead and invalidates approved outreach.
13. Verify Guided Call opens and all first-level branches work.
14. Verify nested branches for price and “need to think” work.
15. Verify lead-specific price language uses Seller Pricing Intelligence and no sample amount is hardcoded into the actual response.
16. Verify `Record Call Outcome` opens the structured outcome dialog with Phone selected and persists the interaction.
17. Re-run existing website-builder prompt tests and confirm Lovable/Canva/generic prompts remain intact.
18. Run PyInstaller and Windows startup smoke tests.

Do not add automatic sending, robocalling, SMS blasting, hidden-email harvesting, or unsupported contact enrichment during this verification pass.

If these changes are being folded into v0.1.9 Prospect Intelligence, preserve them and update schema/release migration strategy accordingly rather than creating a conflicting parallel migration.
