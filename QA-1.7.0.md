# JobTracker 1.7.0 validation

The release adds direct read-only Gmail, Microsoft Graph and IMAP/TLS ingestion on the shared Python backend and desktop credential bridge. Apple Mail remains available on macOS. All status suggestions remain subject to exact displayed-proposal approval.

## Automated coverage

The complete Python suite covers parsing, matching, quote/evidence checks, conditional hiring language, approvals, stale proposals, ambiguity, manual linking, ignore/supersession, restart and late-body recovery, notifications, backups, search/pagination, source identity, account isolation and cursor transactions. New provider fixtures exercise Gmail Spam and history pagination/expiration, attachment-backed text, binary attachment exclusion, Graph Junk/Archive/nested-folder enumeration, immutable IDs, folder/delta reset, removed items, IMAP read-only folder access, MIME text-only downloads, UIDVALIDITY reset, protected credential endpoints, refresh rotation/acknowledgment and Retry-After windows. Failing a provider page commits only previously completed pages.

Desktop tests exercise encryption/no plaintext persistence, insecure Linux storage refusal, preservation of locked/corrupt vaults, rollback on write failure, PKCE/state validation, cancellation/timeouts, missing offline grants, IPC origin/window guards, session-only connections and renderer-safe errors. Existing counts, forms, pending-status ranking, notification dispatch and shutdown tests remain in the suite.

## UI and package checks

Interactive tests use a disposable synthetic profile with mock jobs and confirmation, interview, technical test, offer, rejection, conditional wording, quoted thread, missing-role and invalid-evidence email fixtures. Checked provider-specific setup fields, Gmail/Microsoft instructions, filters, grouping/sorting, in-place approval, disapproval feedback, ignore/restore, manual relinking, notification history and unsaved status/notes through a background revision. A real packaged macOS app in a separate throwaway profile verified that the sandboxed preload/main-process connection bridge is available, encrypted-storage status is displayed and missing client IDs receive validation errors.

Native packaged smoke tests require both bundled Python startup and actual UI readiness. The desktop build workflow runs the complete suites and installer/smoke tests on native macOS ARM64, Windows x64 and Linux x64 runners. Release publication is gated on successful native build results. Artifacts are checksummed after download.

## Limits and privacy

No actual mail was sent, changed, marked read or seeded. No real application was approved or modified as a test. Provider exchanges and IMAP fixtures use synthetic responses; live Gmail/Outlook consent and a real IMAP server are not tested here. A user-provided registered OAuth client or app password is necessary. Generic IMAP OAuth, background agents/IDLE, Exchange's separate online archive and public preconfigured/verified Google OAuth registration are not included. Linux persistence needs an available secret store, otherwise session-only connection is offered. Oversized text is visible with a warning and receives no status proposal. See EMAIL_PORTABILITY.md for setup and remaining limits.

This testing provides regression evidence, not proof that every possible failure is eliminated. macOS is ad-hoc signed and not notarized; Windows installers are unsigned. Installer smoke tests do not substitute for testing provider consent and credential-store behavior on physical Windows/Linux desktops.
