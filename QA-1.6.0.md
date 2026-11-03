# JobTracker 1.6.0 hardening and validation

Scheduled work began November 2, 2026 at 5:45 PM America/New_York. Real applications and mail were not used as test fixtures. All mutation and email-injection tests used temporary databases and synthetic messages; no test email was sent or placed in the user's Mail account.

## Review findings addressed

- Background status-option refresh preserves an open application's selected status and unsaved fields. Job-state reconciliation uses the form's original record rather than a potentially advanced polling snapshot. Unsaved status color/order drafts are retained too.
- HTTP review requires a token identifying the exact proposal, body/analysis revision, application links and affected job state. Changed proposals are refused and refreshed before another human decision.
- In-flight classification reloads the live message before missing-role detection, preserving manual links. Results or failures from an older body revision cannot overwrite a later download.
- Later nonempty, at least equally complete Mail bodies replace empty/partial text. Undecided messages requeue; approved, disapproved and ignored decisions remain resolved. Existing blank bodies receive explicit recovery windows even outside the normal incremental overlap. Shorter transient downloads do not erase stored text.
- Full exports include notification history, delivery and read state; restores merge without duplicating the same event. Legacy backups reconstruct pending alerts and quiet archival entries.
- Inbox search/type/date/review filters and sorting run before server pagination. Default pages contain 200 previews. Related rows are fetched in batches. Full content is loaded separately. Supersession makes one pass over candidate headers/links and does not load all bodies per company.
- Default classification and disapproval analysis use the running app's bundled Python/helper directly. Custom Apple Shortcuts remain optional. The installed JobTracker Email Review Shortcut was changed to use `/Applications/JobTracker.app/Contents/Resources/...` and its actual self-test passed.

## Additional failures found and corrected

- A pending warning explicitly queued for retry was discarded during restart initialization. Only legacy migration now normalizes those pending states; explicit retries survive.
- Old failed inference could mark a hydrated message failed. Failure writes now check body revision and resolved decisions.
- Pending application indicators and approvals could cross the selected account boundary. Backend scoping and immediate account-switch revision/UI refresh now cover those paths.
- Urgent status alerts could be trapped behind a historical normal-alert backlog. They now have priority, and their older normal alert is covered without deleting in-app history.
- Inboxes and notifications beyond their initial visible page are expandable. Full-view navigation can load the selected email even when its header is on another page; newer status context is queried independently of the current page/filter.
- A real local-model test labeled an explicit receipt with conditional interview language as other. The fixed type-only protocol and receipt fallback preserve confirmation while still proposing no status change.
- Initial launch checks used a fixed 3-second delay and could fail while startup was still progressing. Checks now wait up to 15 seconds for actual UI readiness and avoid modal shutdown alerts on test failure.

## Evidence

Automated suites: **150 backend tests and 55 desktop tests passed**. New coverage reproduces stale approvals (including HTTP requests without/current/stale tokens), live manual links during classification, hydrated-body races, body regression prevention, interrupted retries, selected-account changes, notification export/restore, 200+ notification expansion, urgent backlog priority, bounded inbox queries and rolling date windows. Date cases include future/invalid dates, leap day, year transitions and inclusive 7/30-day boundaries.

Interactive UI work used an isolated mock app with five initial mock jobs, a missing-role job added through the app, and a temporary future-dated job. Fixtures included confirmations, a conditional interview description, an actual invitation, technical test, offer, rejection, quoted older invitation, invalid evidence, an offline failure, general company correspondence and a second account's hidden proposal. A fake Mail sync injected a new interview representing Spam coverage without touching Apple Mail. The real JXA adapter's account and Spam/Junk behavior also has automated fixture coverage.

Verified in the UI: review stays on Applications; company-only proposals require a job choice; newer rejection warnings; rejection/offer/interview approval; ignore/restore; manual relinking without status edits; note/status preservation during a polling revision; invalid-quote warning; disapproval analysis and separately approved prompt correction; missing-job suggestion/add; search and type filters; company/type/flat grouping; oldest sorting; failed-analysis retry; collection catch-up; notification explanations/read-all without approval; future application exclusion from rolling counters; saved answer creation/search; Insights and grouped map locations.

Actual installed Shortcut self-test returned `jobtracker-email-review-v1`. The real local `qwen3.5:9b` model was also exercised with synthetic receipt, invitation and rejection text. The conditional-receipt classification was rechecked successfully after correction. No personal text was sent to the model as part of these tests.

A 10,000-message temporary database with 8 KB bodies returned a 200-preview inbox page using **16 SQL statements**, approximately **286 KB**, in **0.067 seconds** locally. Supersession of those 10,000 records completed in **0.209 seconds**. These are single-machine checks, not universal performance guarantees.

## Limits

This is broad regression testing, not proof that every possible failure has been eliminated. The in-app test browser blocked on a native JavaScript deletion confirmation, so that particular interactive deletion was not completed; backend deletion/recovery paths remain covered by existing tests. Provider outages, delayed Mail downloads, arbitrary classifier mistakes and OS notification policies remain external constraints. Long text is bounded before model inference; the complete collected source remains viewable up to the existing two-million-character storage limit. Initial Apple Mail history collection still depends on local Mail availability and can be slow.

Current email ingestion remains macOS/Apple Mail. Windows and Linux provider collection is planned, not implemented or device-tested. The classifier no longer needs Siri, and [EMAIL_PORTABILITY.md](EMAIL_PORTABILITY.md) sets out Gmail, Graph and IMAP adapters, cursor/deduplication rules, OAuth/secure storage and platform acceptance gates with primary sources.

The live database was snapshotted before installation. Application records are compared before/after launch to check preservation. No commit, push or publication was performed.

Installation verified: `/Applications/JobTracker.app` is version 1.6.0 and the packaged readiness check passed. All fields of the 35 saved application records matched the pre-update snapshot. The live UI shows Today **0**, Last 7 days **12**, Last 30 days **13**. The previous installed app and a consistent database snapshot were preserved in temporary backup folders.
