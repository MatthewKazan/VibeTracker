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
