# Cross-platform email integration

Design decision, November 2, 2026: keep collection independent from classification and approval. The desktop app should connect directly to the selected mail account; Apple Mail should remain an optional adapter. Siri should be a launcher, not a required processing engine. Version 1.7 implements direct Gmail, Microsoft Graph and IMAP/TLS connections. Provider sign-in requires OAuth client registration or an IMAP app password. The automated provider tests use fixtures; no live mail account was connected during testing.

## Shared workflow

`Selected account → provider adapter → durable message store → company/role matching → classification queue → proposal → manual approval`

The implemented adapter contract has `profile`, `page(cursor)` and `message(remote_id)` methods; each adapter owns folder enumeration, initial/incremental pagination and source links. Return normalized IDs, UTC receipt timestamps, headers, plain text, body completeness, folder membership and an opaque resume cursor. Return explicit retryable/permanent failures. Commit messages and a page cursor in the same database transaction, before classification. A failed body fetch must leave a durable retry item rather than advance past an unrecorded message. Never let classifier failure roll back ingestion.

Use `(adapter, account_id, provider_message_id)` as the source identity. Track folder memberships separately; use Message-ID and content checks only for cross-adapter reconciliation, not as globally unique primary keys. This avoids collisions between accounts and duplicates caused by folder moves. Migration should map existing Apple Mail records without replacing approvals, manual links, ignore decisions or notification read state. Add an explicit completeness field rather than inferring download state from body length.

Run matching, type classification, supersession, proposal tokens, paging, search and review in the shared Python service. Default classification now runs the app's bundled helper on all OSes. Provider adapters must not own application status logic. Always validate proposal version, source content, affected links and current job state at approval time.

## Adapter choices

| Adapter | Platforms | Collection/resume design | Scope |
| --- | --- | --- | --- |
| Gmail API | macOS, Windows, Linux | Initial paged list/get; subsequent history cursor; include Spam explicitly and discard Trash/Drafts locally. Full deduplicated resync if history expires. | First direct provider, given the currently selected account's provider. |
| Microsoft Graph | macOS, Windows, Linux | Enumerate folders recursively; retain separate next/delta links per folder, including Junk, Sent and Archive. Refresh folder inventory and reconcile moves. | Second provider; delegated read permission sufficient for message bodies. |
| IMAP over TLS | macOS, Windows, Linux | Read-only EXAMINE and BODY.PEEK; identify messages using mailbox + UIDVALIDITY + UID; use IDLE as a hint and reconnect/catch-up polling as recovery. | Generic fallback; provider-specific OAuth/app-password onboarding still needed. |
| Apple Mail/JXA | macOS | Preserve the current account-scoped, Spam-inclusive adapter and catch-up controls. | Optional compatibility route; not the shared foundation. |

Gmail's history cursor can expire and return HTTP 404; the documented recovery is a full sync. Gmail's `includeSpamTrash` includes both Spam and Trash, so Trash exclusion must remain explicit. Request read-only message access, not send/modify rights. Public distribution requires reviewing Google's verification requirements for restricted read scopes. Sources: [Gmail sync](https://developers.google.com/workspace/gmail/api/guides/sync), [message listing](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/list), [Gmail scopes](https://developers.google.com/workspace/gmail/api/auth/scopes).

Graph message deltas operate per folder. Persist opaque next/delta URLs without rebuilding them. Folder names such as `junkemail`, `archive` and `sentitems` avoid relying on localized UI names; Exchange's separate archive mailbox is not the same as the ordinary Archive folder. Sources: [message delta sync](https://learn.microsoft.com/en-us/graph/delta-query-messages), [well-known folders](https://learn.microsoft.com/en-us/graph/api/resources/mailfolder?view=graph-rest-1.0).

For IMAP, mailbox name + UIDVALIDITY + UID provides stable identity within the protocol; sequence numbers are unsafe checkpoints. Reset/reconcile a folder when UIDVALIDITY changes. Use OAuth SASL where supported, verify TLS, and never mark messages read as a side effect. Sources: [IMAP4rev2](https://www.rfc-editor.org/rfc/rfc9051.html), [OAuth SASL](https://www.rfc-editor.org/rfc/rfc7628.html).

## Credentials and privacy

Use a desktop OAuth authorization-code flow with PKCE and an approved loopback redirect, then store refresh tokens in the OS credential store. Keep tokens out of SQLite exports, logs, model prompts and renderer JavaScript. Backups should restore source IDs and cursors, then require account reauthorization on a new computer.

Use Electron's OS-backed encrypted storage from the main process: Keychain on macOS, OS protection on Windows and an available secret store on Linux. Refuse persistent credential storage when Linux reports `basic_text`; offer session-only connection until a secure store exists. [Electron safeStorage](https://www.electronjs.org/docs/latest/api/safe-storage) documents that fallback's lack of protection.

The current app keeps AI processing local; retain that default. Connecting a provider necessarily makes requests to that provider, but it does not require sending email content to a separate AI/cloud service. Keep one explicitly selected job-search account active and show its scope, folders and last successful collection in the UI.

## Scheduling and notifications

Initially poll changes while the app is open and catch up after sleep/reconnect. Treat push/IDLE as wake hints, not the source of truth. Always reconcile from durable provider cursors. Add an optional native background agent only after the foreground adapters are reliable; make its scope and shutdown behavior visible. No always-on server is needed for the first version.

Keep in-app notification history authoritative. Use the existing Electron notification layer for native alerts on each platform; do not promise to override Focus/Do Not Disturb. Ordinary company messages create normal alerts; only actual status proposals create urgent review alerts. Reading or dismissing an OS alert never approves a proposal.

## Delivery sequence and acceptance criteria

1. Extract and test the adapter contract against the existing Apple Mail reader and a fake adapter. Add source identity/completeness migrations and reversible reconciliation.
2. Implement Gmail read-only OAuth, paginated initial sync, history recovery, Spam coverage and disconnect/reauthorization. Validate against a dedicated test mailbox; never seed a real job-search inbox.
3. Add Graph and then IMAP adapters behind the same contract. Include localized folders, nested folders, moves, duplicate IDs, expired/revoked credentials, rate limits, 429 retry delays, changed cursors and missing bodies.
4. Exercise the same UI/review conformance suite on macOS, Windows and Linux. Package and verify each native build before advertising support.
5. Offer optional background operation and Siri/other OS launchers after the above is stable.

Release gates: no status edits without exact-proposal approval; no source/account leakage; cursor advancement only after durable storage; stable manual links; identical backup/restore semantics; late body recovery; bounded inbox responses; secure token storage; offline recovery; and no lost/duplicated notifications after crashes. Benchmark 10,000+ messages and realistic multi-company data. Keep testing evidence and known limits with each release.


## 1.7 implementation and setup

Open Emails → Collection & classification settings → Connect Gmail, Outlook or IMAP. Select exactly one account for job-search correspondence. Connecting switches that selection; it never approves a proposal. Enable automatic checking to poll while JobTracker is open, or use Check emails since last sync. The first pass fetches provider history, filters company mentions deterministically, and queues AI only for retained company emails. Provider cursors and retained messages commit together per page. A failed request leaves the current page uncommitted. Rescan all company emails restarts ingestion with deduplication and preserves human decisions.

Gmail setup: enable Gmail API in a Google Cloud project, configure the OAuth consent screen, add your own address as a test user if the app is in testing, and create a Desktop app OAuth client. Enter its public client ID and, if supplied, the desktop client secret. Sign in in the system browser using PKCE and a random loopback redirect port. JobTracker requests only `gmail.readonly`. Google testing-mode authorizations with these scopes can expire after seven days; reconnect if necessary. A broadly distributed, preconfigured OAuth client requires Google's restricted-scope verification; this release does not bundle one. [Installed-app OAuth](https://developers.google.com/identity/protocols/oauth2/native-app), [OAuth testing and token expiration](https://developers.google.com/identity/protocols/oauth2#expiration).

Outlook setup: register a Microsoft Entra application with the appropriate supported account types. Add a Mobile and desktop application platform redirect `http://localhost/oauth/callback` (the desktop listener uses a random port), and delegated Graph `User.Read` and `Mail.Read` permissions. Enter the application client ID; no client secret is used. JobTracker requests `offline_access` for refresh tokens. Tenant policies may require administrator consent. [App registration](https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-register-app), [authorization-code/PKCE flow](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow).

Other IMAP accounts: enter email, TLS hostname/port (normally 993), optional separate username and a provider app password. This adapter uses EXAMINE and BODY.PEEK, downloads text MIME sections without binary attachments, and never changes read flags. Generic IMAP OAuth/IDLE are future extensions; use direct OAuth adapters for Gmail/Outlook providers that disable password login.

Credentials are held in Python process memory and passed only through a main-process authenticated endpoint. The renderer never receives saved credentials. Remember encrypts the credential file in the desktop profile through Electron safeStorage. A locked/unavailable secret store preserves existing ciphertext; Linux `basic_text` storage is rejected. Uncheck Remember for a session-only connection. Disconnect forgets the active credential while retaining correspondence and decisions; restoring a JSON backup requires reconnecting accounts. Never export credentials for migration.

Provider identity is account-scoped, and Outlook requests immutable IDs on every request. Ordinary Junk/Spam, Sent and Archive folders are included; Trash/Deleted/Drafts are excluded. Graph's separate online archive mailbox is not supported by the mail API. IMAP respects special-use flags and common trash/drafts names; servers that omit flags and use other localized names may expose additional folders. Gmail history expiration triggers a fresh pass; Graph invalid deltas reset the affected folder and deleted folders cannot cause an endless retry. IMAP UIDVALIDITY changes start that folder again, reconciling matching messages when possible. Matching Message-ID, account address, subject, sender, date and content prefix help reconcile folder moves or Apple Mail migration without dropping manual links or approvals.

Empty bodies are retried in bounded groups during later checks. Text over the 2 MB safety limit remains visible with a warning and receives no automatic status proposal. Complete original content can be reviewed in the source mail client; IMAP has no universal open-in-client link on Windows/Linux. Gmail and Outlook open validated provider webmail links. Retry analysis does not classify known-incomplete text. Provider Retry-After windows are respected during the session. HTTP errors, throttling and timeout errors surface in the email status; subsequent manual or minute polls resume at the saved page. Durable background scheduling, background agents/IDLE/push, generic IMAP OAuth and hosted preconfigured OAuth registration remain future work.
