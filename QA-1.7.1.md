# Email precision repair — 1.7.1

The reported boarding pass entered job correspondence because its Apple Wallet text matched a tracked Apple job. A separate title-extraction error treated a company-prefixed title (`Company | Role`) as a missing role even when that role was already tracked. A generic acknowledgment in a rejection could also create a premature missing-role suggestion.

Collection now distinguishes employer identity/job context from incidental brand mentions and excludes clear personal travel/purchase/financial receipts. Genuine employer correspondence, job receipts from ATS senders, and interview-related travel remain eligible. Quoted earlier messages do not supply new company matches. HTML blockquote boundaries are retained so the same rule applies to HTML-derived bodies.

Status proposals require a verified quotation from the current message that supports the proposed hiring outcome. Greetings, conditional hiring language, marketing offers, rescheduling regrets and quoted older decisions cannot supply that evidence. Unsupported classifications remain viewable with a warning and no status proposal. Approval rechecks this contract, including proposals imported from older versions. Genuine conversation invitations, phone screens, technical tests, employment offers and explicit declines have regression coverage.

Role comparison recognizes the known employer prefix and suffix without collapsing distinct roles or levels. Existing matching hints are reconciled even after a manual rejection approval. A versioned repair recoverably ignores clearly unrelated, automatically linked consumer messages and withdraws unsupported pending proposals. It retains original email content, human review decisions, restored emails, manual links, job statuses and approval history. Show ignored and Restore ignored email allow recovery of excluded correspondence.

Validation: 203 Python tests and 72 desktop tests; realistic negative and positive fixtures were added and unrealistic type/evidence combinations in older review tests were corrected. The actual local Qwen 3.5 9B model passed eight synthetic examples covering rejection, confirmation, conditional confirmation, quoted history, technical assessment, interview, offer and newsletter. No real email content was used in model evaluation.

A migration rehearsal on a consistent copy of the live database verified unchanged application records, saved status decisions and manual links, while excluding the boarding-pass false positive and dismissing the duplicate role hint. Live records were not modified by the rehearsal. Native Windows, Linux and macOS builds run the complete suites and packaged UI/mail-bridge startup checks before release publication.

These checks target reproduced failures and representative language. They do not prove perfect classification. Unsupported or unusual wording may need manual review; human approval remains mandatory for every application status change.

The live-profile installation check exposed a separate chart path-rendering error that interrupted initial data loading. Sankey ribbons now use their coordinates directly to generate SVG paths, avoiding the failing global path dependency. Packaged smoke mode now seeds a synthetic application with interview history and fails on a visible data-loading error, so empty profiles cannot hide this failure.
