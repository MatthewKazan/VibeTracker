# VibeTracker

## Download

Find latest release on the right, download and unpack release for your system. Only Mac has been tested

## Start from source
Double-click `Start.command` in Finder. It starts a local server and opens http://127.0.0.1:8765 in your browser. Keep its Terminal window running while using the app. Closing it does not erase saved applications. Python 3 is the only required runtime; no pip installation is needed.

Alternatively, run `python3 app.py` from this folder. If the port is occupied, set `PORT=8766 python3 app.py` and open that port instead.

## Interface
The app opens in dark mode directly to the application list. Add application lives in the sidebar (top navigation on narrow windows) and opens a dialog. Charts and summary cards are in Insights. The Set up local AI button provides the official Ollama download link, model-download instructions, a connection check, and a selector for installed local models.

## Workflow
- Add application → paste a public job-posting URL → Autofill → review → Save application.
- The date applied defaults to today. The app cannot determine when you actually applied from a job posting; adjust historical entries.
- Structured JobPosting data provides the best extraction. Page-title and labeled-text fallbacks work on simpler pages. For blocked or login-only job boards, paste the posting text. Configure an optional local Ollama model for improved extraction.
- Profile & data → paste your résumé text. The Fit / keywords column recalculates keyword coverage from the current saved résumé and description. It is a rough text comparison, not a calibrated fit prediction. Missing résumé or description means no score.
- Optional AI: install Ollama and download a model, then select it in Local AI. JobTracker discovers installed models and can start Ollama and load the selected model automatically. Inference stays local.
- Import spreadsheet accepts .numbers, .xlsx and UTF-8 CSV, previews the first rows, and lets you map columns. First worksheet only; first nonempty row is the header. Convert legacy .xls to .xlsx. Standard Excel 1900 dates are supported; use ISO dates for other date systems. US-style ambiguous dates are interpreted by the browser. Import is atomic: an invalid row rolls the entire import back. Limit: 10,000 rows and 25 MB.
- Import skips matching URLs or identical title/company/date records. Missing dates default to today, missing status to Waiting, and unknown stages normalize to Waiting. Review column mapping and exported results when migrating.
- Click any row to edit. Sort by any visible column, search titles/company/location/notes, filter status, and set a follow-up date.
- Job map → Locate unmapped jobs resolves location text with OpenStreetMap Nominatim, at most one request per second. City names are sent to that service. Ambiguous cities can resolve incorrectly; refine location text and locate again. Remote-only roles stay in the list. Map tiles need internet.

## Storage and recovery
The `data/jobs.sqlite3` database is the source of truth. Successful saves use SQLite transactions, WAL journaling, and FULL synchronous disk commits. Records survive browser closes, process crashes, and restarts. Unsaved form edits are not committed; click Save and wait for success.

Each mutation creates a SQLite online-backup snapshot before and after the change. Startup also creates a snapshot. The newest 50 snapshots are retained in `data/backups/`. Profile & data → Browse recovery snapshots downloads a selected snapshot as JSON; Restore JSON backup merges it into the current database. Merge restores missing records and skips matching existing ones; it does not overwrite edits.

For exact point-in-time recovery: stop the app, copy the current `data/` directory somewhere safe, replace `data/jobs.sqlite3` with your chosen `data/backups/*.sqlite3`, remove only the old `jobs.sqlite3-wal` and `jobs.sqlite3-shm` sidecar files if present, then restart. Never replace database files while the app is running.

Export full backup includes applications and résumé/settings. CSV includes application columns for Excel. Spreadsheet-formula-like text is escaped in CSV exports. Store backups on another disk or a backed-up folder: local snapshots cannot protect against drive failure, folder deletion, theft, or every hardware fault. Keep the whole project folder when moving the app, or set `JOB_MANAGER_DATA` to another persistent directory.

## Privacy and dependencies
The server listens on loopback only and requires a session token for writes. Résumé and job records stay on disk. Public job URLs are fetched directly; optional model inference is local. Map scripts/styles and Sankey dependencies are bundled; tiles/geocoding use OpenStreetMap, and optional display fonts use Google Fonts. The tracker works without these services using system fonts; map rendering and URL lookup need connectivity. Do not expose this development server to the internet.

## Verification
`python3 -m unittest discover -s tests -v`

Tests cover SQLite reopen and backup recovery, a forced process kill/restart, HTTP save behavior, atomic failed imports, CSV/XLSX parsing, structured posting extraction, partial updates, snapshot exports, and private URL blocking.


## Automatic local AI and fit details
At app opening, JobTracker checks Ollama's installed local models. Automatic startup is enabled by default and can be disabled in Local AI. When enabled, it launches the installed Ollama CLI (`ollama serve`) on loopback if necessary and loads the selected model. If no model is selected, it tries the smallest installed compatible text model first. Embedding and cloud models are excluded or rejected before inference. The selected model stays loaded for ten minutes after use, then Ollama may unload it; the next request loads it again. Starting a model does not download it. Optional suggestions link to model pages and copy Terminal download commands.

The desktop app can ask whether to unload the selected model when quitting; the answer can be remembered and changed in settings. Startup errors are reported in the Local AI dialog; CLI startup output is in `data/ollama.log`.

Click a Fit / keywords cell to see exact matched terms, missing terms, and quoted job-description context. This deterministic percentage is keyword coverage, not an employer ATS score or a calibrated estimate of suitability. Common recruiting boilerplate is filtered and known skill phrases are included, but the extraction remains heuristic. Missing résumé wording is not proof of a missing skill. No résumé is edited automatically.

Analyze with local AI compares requirements with résumé evidence, distinguishes unclear evidence from potential gaps, and suggests wording. It verifies job and résumé quotes against the supplied texts; model-generated recommendations still require review. Unsupported claims are flagged for conditional use only. Add skills or accomplishments only if they reflect your actual experience. All inference uses localhost. Analyses are stored in SQLite and reused while the résumé, posting, selected model and analysis version are unchanged. They are included in database snapshots; JSON exports currently export the underlying jobs/profile, so deep analyses can be regenerated after JSON restore.

Local model sizes and usage references: https://ollama.com/library/qwen3:4b and https://ollama.com/library/llama3.2. Runtime API: https://docs.ollama.com/api/tags and https://docs.ollama.com/api/generate.

## Version 1.0.2 reliability fixes
Restores the desktop authentication header after the JobTracker rename; checks the backend session before displaying the window. Adds recovery guidance for offline services, model failures, invalid backups, unreadable files and storage errors. Import validation identifies the failing row and rolls back the batch. CSV delimiter detection is limited to actual delimiters so single-column files are not split on letters. A failed post-save snapshot is reported as a warning after a successful database commit. Error messages remain visible until dismissed.

## Numbers import (1.0.3)
Import spreadsheet accepts modern .numbers files, parsed locally in a bundled worker. Choose the table, map columns and review before importing. Limits: 25 MB, 10,000 data rows, 200 columns; a 45-second timeout prevents a stuck reader. Password-protected or unsupported legacy files should be saved as an unencrypted current Numbers file or exported as .xlsx/CSV. Dates are normalized to ISO date text. No Numbers installation is required on Windows or Linux. The bundled SheetJS CE 0.20.3 license is in static/vendor/SHEETJS-LICENSE.

## Version 1.1.0

Neutral dark theme, full-row status colors and grouped map pins. Sort levels are visible above the application list and saved in SQLite. Default order: status ascending, date applied newest first, company A–Z. Blank values sort last.

Fit opens an automatic local model review when a résumé and description are available. The displayed estimate weights required requirements twice as heavily as preferred ones; supported evidence earns full credit, partial evidence half, unclear/gap zero. It is not an ATS score. Quotes are checked against the supplied text; the model can still make semantic mistakes. Reviews use the current date, saved profile corrections and job-specific discussion. Profile facts remain distinct from résumé evidence. Corrections and discussions persist in SQLite and full JSON backups.

Spreadsheet import includes an optional local AI column-mapping button and job-description mapping; users review mappings before the atomic import. A search-brief export includes profile text and tracked roles for a web-enabled assistant to find verified recent postings. This is a manual handoff, not a direct ChatGPT connection.

On desktop quit, users can unload the selected Ollama model, keep it loaded, or cancel. Remembered choices are editable in Profile & data. This does not terminate the Ollama service or unload other models.

## Application flow and compact layout
Insights includes a Sankey diagram with separate interview rounds, one node per outcome, and counts on every ribbon. Ribbon width represents application volume; earlier stages may be inferred from recorded interview counts. The chart explains its counting rules below the diagram. Status colors come from your settings. Controls and table rows use compact spacing while preserving readable text.

## Development
Use Node.js 24 and Python 3.12 or newer. Run `npm ci`, then `npm test` and `python3 -B -m unittest discover -s tests`. Run `python3 app.py` for browser development or see DISTRIBUTION.md for desktop builds. Personal databases, backups, local test data, generated installers, and credentials are excluded from Git.

## Version 1.2.0
Questions & answers stores reusable responses in named groups. Drag groups to reorder them and drag cards between groups. Copy questions, answers, pairs, or the whole library; bulk paste accepts Q:/A: pairs. Text search is immediate; Search by meaning uses your selected local model to rank saved records in small batches, with no generated answers. Question groups and their order are included in full backups.

New applications record a timezone-aware save time. Hover over the applied date to see it; date sorting breaks same-day ties using that instant. Older records without a recorded application time show “Time not recorded.” Existing sort priorities remain configurable.

Autofill now reads page metadata, matching role objects in same-origin JavaScript bundles, and Gem's public posting API. HTML paragraph and list boundaries are preserved. Fit extraction accepts S-prefixed sentence references and falls back to source requirement sentences when model references fail, while retaining evidence checks during scoring.

## Version 1.2.1
Q&A cards now have a single Copy answer action. Complete autofill fields skip unnecessary model calls, complete structured postings skip extra source fetching, and full posting text takes priority over short marketing metadata. Failed optional script fetches preserve available extraction results. The desktop backend client fully reads responses and handles interrupted connections without using Undici, addressing the reported parser assertion.

## Email connections and email review

Choose Emails → Collection & classification settings → Connect Gmail, Outlook or IMAP. For native Apple Mail on macOS, use Refresh accounts, select the job-search account and press Use this account. Collection reads only that account, including Spam, Junk, Sent and archived folders; folders named Trash, Deleted Messages and Drafts are excluded. Localized/custom folders may need corresponding exclusions. No email is moved, deleted or marked read. macOS may request Mail automation permission.

Collection and classification are independent. The collector reads each candidate message body once, matches tracked-company names, legal-name variants, common spacing/camel-case variants, split brand names and known employer domains, and saves all matches immediately. Company correspondence remains viewable even if it is a newsletter or AI cannot classify it. Exact tracked role mentions narrow the application links; company-only messages link to all tracked roles at that company. Manual links are preserved.

For the Apple Mail adapter, the initial history search starts with recent messages and works backward in resumable windows. Mail date metadata bounds the search; if unavailable, the fallback searches back to 1970. Timeouts split unfinished windows. Incremental checks rescan a two-day overlap and deduplicate on Message-ID. Each committed window saves its collection checkpoint independently of AI results. Adding/changing tracked companies triggers a history refresh. Check emails since last sync resumes collection; Rescan all company emails restarts matching. Collection and AI queues resume after app restart.

AI only classifies saved email types: rejection, actual interview/test request, job offer, application confirmation, or other. It does not decide which emails to retain, select application links or add jobs. Types are committed individually. Normalized whitespace, HTML entities and typographic punctuation are allowed when validating model evidence. An unverifiable quote is removed and replaced with a visible warning; the original email and manual status suggestion remain available. Other model/shortcut failures stay on the individual email with Retry this email / Retry failed analyses, and never roll back collection or stop other queued messages.

All email-driven status changes require approval. Applications show Review buttons beside their current saved status. Pending interview/test and offer suggestions sort ahead of approved Interview pending applications and ordinary sort levels. Clicking a review button opens its source email. An approval changes only the selected linked applications and records the email/date; disapproval leaves statuses unchanged and asks the shortcut to propose a prompt correction for separate approval. Ignore email removes an obsolete message from review without triggering error analysis; Show ignored and Restore ignored email retain access to its history.

When every tracked role at a company has an approved current status (from email review or an explicitly saved terminal status: Rejected, Accepted, Withdrawn or Offer declined), earlier messages linked to that company are automatically marked Ignored · superseded. The conservative cutoff is the oldest effective email date across those approvals (or the recorded manual status-transition time), so messages that might postdate one role’s decision remain visible. Waiting and automatically inferred Ghosted statuses do not count as terminal approvals. Editing notes without changing a terminal status does not move its cutoff. Approved/dismissed emails and explicitly restored historical messages are preserved. A missing-role suggestion is not assumed to belong to unrelated existing jobs.

The inbox displays total, matching, shown, awaiting-classification and pending-review counts. Group by Company & role, Email type, or No grouping; sort by received date (either direction), type, review status or company. Combine search, inclusive local date range, type, Needs review, Exclude confirmations and Show ignored filters. Lists load lightweight previews, full bodies load on selection, and Show 200 more exposes further matching records. Full-body search covers text beyond the preview.

Specific role names in confirmation text are checked against tracked applications without AI. A possible missing role gets a persistent “<job> may be missing from list” hint. A background lookup tries public posting URLs and public web search using only company/title; a found posting must match the title and employer. Private applicant, assessment and interview links are excluded, and applicant tokens/tracking parameters are not forwarded. When a posting cannot be verified, the hint remains. Review & add application opens a prefilled editable draft; nothing is added until you save it. Duplicate receipts share the suggestion and source links.

Native desktop notifications report newly collected emails, and potential status changes request urgent banners/sound and dock attention. Notifications are grouped and durably acknowledged after display; clicking opens the email review. Dock badge counts reflect unresolved reviews. macOS notification permissions and Focus settings govern OS delivery. In-app counts and review buttons remain available.

Email contents and model inference stay local. Public posting lookup sends company/title search terms and requests public job pages. Email records, application links, missing-role suggestions, approved status provenance and feedback are included in SQLite snapshots and JSON exports; JSON restores remap job IDs and retain the review state. Notifications are not replayed from exports.

### JobTracker Email Review shortcut

The shortcut already created on this Mac takes Shortcut Input, passes it to stdin of one Run Shell Script action, and returns JSON:

```sh
'/Applications/JobTracker.app/Contents/Resources/python/bin/python3' -B '/Applications/JobTracker.app/Contents/Resources/backend/mail_shortcut.py'
```

It uses the installed local Ollama model selected in JobTracker. The default classifier is invoked directly using the running app’s bundled Python and helper; Apple Shortcuts is optional. The installed Siri Shortcut also points to the Applications bundle. Custom Shortcuts remain supported on macOS. The app invokes it with shortcuts run and JSON input/output files.

Current classification input includes mode=classify, type_only=true, model, classifier_prompt, and the saved email. Output is a kind (rejection/interview/offer/confirmation/other) and evidence quote. Legacy callers with jobs or batch input remain supported. Feedback input uses mode=feedback, email, classifier_prompt, tracked job context and disapproval_reason; output includes explanation and proposed_prompt. A prompt correction is applied only after approval and only if its base prompt has not changed. mode=selftest checks shortcut wiring without inference.

### 1.6 review hardening

Application counters use inclusive local calendar windows: today, the last 7 days and the last 30 days, excluding future dates. They refresh at local midnight and on focus after sleep. Background email work preserves open application status selections, notes and unsaved status color/order drafts.

Status approvals include a token tied to the displayed classification, body revision, application links and current affected job state. A stale request is refused and refreshed for review. In-flight analysis uses live link/decision state and cannot overwrite a newly downloaded email body. Later Mail downloads hydrate empty or incomplete records and requeue undecided emails; resolved decisions stay resolved. Old empty bodies receive a separate recovery scan.

The inbox API pages 200 headers by default, performs search/filter/sort before paging, and batches related-record queries. Full content is fetched on selection. Supersession uses one header/link pass rather than loading all bodies per company. Full backups include notification delivery/read history and legacy restores reconstruct alerts. More than 200 notifications can be expanded in the UI. Account checks cover previews, approvals and pending application indicators.

See [EMAIL_PORTABILITY.md](EMAIL_PORTABILITY.md) for the implemented cross-platform adapters, provider registration instructions, migration design and remaining limitations. Gmail, Outlook/Microsoft 365 and IMAP/TLS connect directly on macOS, Windows and Linux. The default local classifier no longer depends on Siri or the development checkout.


### 1.7 direct email connections

Connect Gmail, Outlook/Microsoft 365 or IMAP/TLS from Emails → Collection & classification settings. OAuth uses system-browser sign-in with PKCE; supply your registered Google Desktop or Microsoft Mobile/Desktop client ID. Other providers can use an IMAP app password. Remember encrypts credentials with system-backed desktop storage; exports contain no tokens or passwords. Linux requires an available secret store for persistent credentials, or an explicit session-only connection.

All adapters feed the same durable collection, local classification, company/role linking, notification and manual approval workflow. Spam/Junk and ordinary Archive folders are included, while Trash/Drafts are excluded. API cursors and retained messages commit together; company changes trigger a deduplicated full pass, and empty bodies are retried during subsequent checks. Large/incomplete text is held without a status proposal. Apple Mail stays available on macOS through Refresh accounts. Direct provider setup and limitations are in [EMAIL_PORTABILITY.md](EMAIL_PORTABILITY.md).

### 1.7.1 email precision repair

Personal boarding passes, purchase confirmations and similar consumer transactions no longer become job correspondence through incidental employer-brand mentions such as wallet badges. Employer identity, current-message context and job-related evidence determine relevance. Quoted earlier threads cannot create new status proposals. Unsupported or invented status evidence produces a visible warning and no proposal, and approval revalidates the current email. Company-prefixed role names match their existing application instead of creating duplicate missing-role hints. The update repairs existing automatic false positives recoverably while preserving applications, approved decisions, original emails and manual links. See [QA-1.7.1.md](QA-1.7.1.md).

Job ads are saved separately and hidden by default in Emails. Use **Show job ads** or the **Job ads & recruiter pitches** type filter to view them. **Profile & data → Notification preferences** controls status-review-only alerts, email categories, ad keyword rules (for example Boston Dynamics or humanoid), sender/company mutes, quiet hours, sound and privacy. Rules affect notifications, never status approvals. Muted alerts do not replay after changing preferences. The current version appears in the sidebar and Profile & data.

Apple Mail scanning uses small resumable batches, caches completed reads, and waits while Mail is in the foreground. Automatic checks run at most once every five minutes; **Scan next small batch** advances manually with a short rest between invocations. **Pause scan** cancels collection and disables automatic checks. Existing correspondence and unfinished checkpoints are retained. Large historical backlogs are collected gradually.

## Low-resource mode (1.9.0)

The pause button beside Local AI stops JobTracker's background AI, email scans and classification, desktop notifications, credential polling and renderer polling. Active owned classifier processes and response sockets are cancelled. Only JobTracker's selected or used resident Ollama models are unloaded; other models and the shared Ollama server remain available to other apps. An unload failure is shown with a retry button. Saved applications, Q&A, insights, emails and cached fit reports remain available; network map tiles and new AI requests require resuming. Explicit posting lookups and field autofill remain available while paused and skip model-based extraction. Pausing does not change your automatic-start, analysis or mail preferences, and the pause survives app restarts.

Every launch has a 30-second grace period before automatic workers, provider reconnection, desktop polling or Ollama startup. Saved views load immediately. Press pause during that period to prevent automatic startup without changing your normal preferences. Explicitly requested local saves and reads still work while paused. The Electron window and local data engine remain resident so browsing can respond immediately.

## Memory use (1.9.1)

Chart and map libraries load on demand. Hidden insights, map instances, Q&A cards and closed email previews release their derived DOM; returning restores view controls, chart sizing, map position and scroll position. Email lists request metadata without body previews, while body searches still use the entire saved email. Only the selected full inbox message stays cached; a hidden email view releases it unless it contains unsaved human review inputs. Hidden notification lists are not rendered. Saved records and cached AI analyses on disk remain intact. Spreadsheet parsing already uses a worker that terminates after import; AI caches already have size limits.

`scripts/memory-profile.cjs` runs a reproducible disposable-profile workload with synthetic jobs, Q&A and large emails. It collects renderer JavaScript heap and DOM counts after garbage collection, then checks unsaved email controls, chart settings, filters and profile text. These measurements do not represent total Electron or system RAM.

## Interview prep

**Interview prep** opens compact About me / Technical notes side by side, or either section on its own. General cheat sheet is the reusable base; Crabi is a prepared independent copy. **Fork for interview** copies the selected sheet, optionally loads a saved application's description or reads a pasted job URL, and attaches the reviewed description. Without AI, description keywords add pointers to relevant existing experience. Optional **Draft notes with local AI** produces an editable preview before the fork is created. Blocked job pages can be pasted manually. AI drafts require review for factual accuracy.

**Edit notes** exposes plain Markdown; **Save** or Cmd/Ctrl+S commits both sections. In-session drafts survive switching versions or navigating away. Closing/reloading with drafts triggers a warning. **Interview view** hides the sidebar and page header (Escape exits); section tabs, search, and a text-size slider remain available. **Copy for AI**, **Paste / import edit**, and **Export .md** exchange editable text with explicit `<!-- about -->` and `<!-- technical -->` markers. Imports become drafts before saving. Source notes and forks have independent revisions; stale saves are rejected without discarding the draft. Full exports and recovery snapshots include all sheets. Restoring notes merges by ID, keeps unrelated forks, and increments revisions.

For AI agents: `GET /api/interview-prep` returns `sheets`. `POST /api/interview-prep` uses the app's usual session authentication and supports `{action:"save", id, expected_revision, title, about, technical}`, `{action:"fork", id, expected_revision, title, job_id?, role_description?, role_url?}`, or `{action:"delete", id, expected_revision}`. Read the current revision before editing; HTTP 409 means re-read and merge. `POST /api/interview-prep/draft` takes source `id`, `expected_revision`, and `role_description`; it returns unsaved local-AI `about` and `technical` Markdown. It honors low-resource pause. Do not write SQLite files directly while the app is running.

Interview cards can be reordered by their small drag handles in reading mode. Right-click a card (or use Shift+F10 with the card focused) for **Edit**, **Move up**, and **Move down**; the menu is the only place movement buttons appear. Card edits and ordering save immediately, independently for each sheet, and the exported Markdown uses the same order. **Read notes** saves the current sheet before returning to reading mode; a save failure keeps the editor and draft available. LaTeX is rendered offline using bundled KaTeX 0.19.1 and its fonts. Use `\( ... \)` for inline expressions and `\[ ... \]` or `$$ ... $$` for display equations. Editor/import/export retain LaTeX source. Recognized formulas in existing sheets are migrated without replacing surrounding notes.

### Extra interview sections (1.11)

Use **+ Add section** for additional named areas such as Questions, Company research, or Math details. Each section has its own tab and Markdown editor; **All sections** shows the sections in a two-column grid. The small **•••** section control renames or deletes an extra section; deletion keeps a recovery snapshot. **+ Add card** creates a card directly in reading mode. Card context menus, reordering, search, LaTeX, save/revision protection, forks, exports and restores work with extra sections too. Up to 20 additional sections are supported per sheet. About me and Technical remain available for compatibility with older editors.

Markdown exchange appends `<!-- section:stable-id -->`, followed by `# Section name` and the section's Markdown. Preserve all section markers during AI edits. Importing an older file with only About me / Technical preserves existing extra sections. API saves may include `sections:[{id,title,content}]`; omitting this field preserves existing sections.

The General and Crabi sheets now include **Math details**, checked against `learned_visual_pose/geometry_conventions.md`, `notes/math_reference.md` and current C++/Python implementations. It covers general ICP and its correspondences, the actual CNN mutual-nearest-neighbor frontend, the Kabsch trace/SVD proof, target-minus-prediction Jacobians, graph residual/adjoint/Log differentiation, and the current Huber/LM/anchor/factorization implementation. A short code-checked solver-conventions card is added to Technical. These additions preserve existing cards and custom sections.

### Compact Technical math and independent columns (1.11.1)

ICP correspondences/objectives, the Kabsch trace/SVD explanation, and the GN/Jacobian derivations now live in concise Technical cards. Their intact detailed copies are removed from Math details; custom-edited cards are retained. The change applies once to sheets that still contain the supplied cards and is included in normal snapshots. In All sections, About me and Technical form independent vertical stacks: Math details follows About me immediately instead of waiting for the Technical column to end. Narrow layouts retain the section order.

### Vocabulary and drag-edge scrolling (1.12)

General and Crabi include a concise **Vocabulary** section with geometry/estimation, ML, and robotics terms. It is an ordinary editable section and copies with the rest of the sheet.

Holding a dragged card near the top or bottom of the visible notes starts automatic vertical scrolling, including when the pointer stays still. Speed increases with proximity and ramps over 400 ms, capped at 900 px/s. These values follow Atlassian's standard auto-scroll configuration: https://github.com/atlassian/pragmatic-drag-and-drop/blob/main/packages/auto-scroll/src/shared/configuration.ts. The edge zone is 25% of the usable viewport, capped at 180 px; the upper edge accounts for the sticky toolbar. Scrolling stops on drop, drag end, Escape, leaving the window, hiding the page, or switching away. Insertion markers follow the content during scrolling.

### Section placement and full-width cards (1.13)

Every section heading has a compact **•••** menu (also available by right-clicking the heading) with Move section up/down, Left column, Right column, and Span both columns. Ordinary sections stack independently in each column; a full-width section forms a band across both columns and can contain two independent card stacks. Existing large headings, search, and section tabs remain available for scanning.

Dragging a card horizontally keeps it in its original section and expands that section to both columns. The card menu also has Left column / Right column commands. Move up/down respects the card's current column. Layouts save independently for each interview sheet, copy on forks, and are included in backups and Markdown exchange. `section_layout:[{field,column}]` and `card_columns:{field:["left","right",...]}` are optional API fields; `field` is about, technical, or extra:<section-id>, and section column can also be both. Markdown exports append an `interview-layout` JSON comment; preserve it when editing with AI. Omitting layout fields in older API clients preserves existing layout.

### Application capture

**Add job application** sits at the top right; its dropdown includes **Import spreadsheet**. Autofill fills the fields and immediately becomes available again. A compact status shows the independent background review; optional, collapsed suggestions contain keyword matches and missing terms with posting excerpts before the full local résumé review finishes. Saving never waits for suggestions, and arriving results do not expand the form. Draft reviews use the saved résumé, remembered facts and custom prompts. Completed requirement checks are reused by the existing analysis caches when the application is saved. A review validates its local model once instead of repeating model discovery for every requirement; inference settings and evidence checks are unchanged.

Draft reviews show the current phase and, once requirements are known, actual completed/total requirement counts with the item under review. The progress bar is indeterminate during posting retrieval and requirement discovery; percentages reflect reviewed requirements, not estimated elapsed time.
