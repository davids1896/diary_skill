# Daily diary library and paired PDFs

Every authored diary or diary supplement must have a matching, validated PDF before it is
handed to the owner. This includes tentative drafts. Preserve draft/confirmation state in
both formats. Raw source exports, source-review notes and software documentation are not
standalone diary deliverables. Give the PDF or the authenticated library's PDF link alongside
Markdown; a Markdown-only handoff is incomplete. Report rendering failures without hiding them.

`diary_library.py` supplies `Library(config)` for an existing authenticated Python web app.
The deployment must provide an `authorized()` method on its handler. Every library route
checks it, and no anonymous server or public publishing configuration is included.
Register the library under `/diary/`, route GET/HEAD/POST through `library.handle()`, and
call `library.start()` once. The library itself only permits GET/HEAD. Keep the backend
loopback-only behind the deployment's authenticated reverse proxy.

Configuration includes `cache`, `assets`, `generator`, `roots` (`archive` and optional `draft`),
`image_roots` (explicit local evidence directories), and optional `interval` (default 60 seconds).
Point `generator` at the existing verified diary PDF generator and `assets` at `web/diary-library`.
Keep scratch files, source snapshots and PDFs on an adequately sized private data volume.
The service needs write access only to its cache and adjacent archive PDFs; original
Markdown and the source-evidence trees are read-only inputs.

The worker watches dated diaries and complete diary drafts, including recording supplements.
It retains each original Markdown file, normalizes referenced pictures into a private
content-addressed snapshot, verifies that authored paragraphs/tables/pictures are preserved,
and generates a corresponding PDF with the established renderer. Source text and picture
changes invalidate the companion receipt. Snapshot Markdown, PDF, pictures and HTML stay
together. The archive also receives its conventional adjacent PDF. Files on a full system
partition can use the private snapshot's paired PDF through the library instead.

An optional `validated_archive_commit` must identify an explicitly verified prior publication
receipt, never an arbitrary HEAD. Existing archived Markdown, PDF and every referenced image
may be reused without repeating render checks only when all are tracked and byte-for-byte
unchanged relative to that verified commit. Other existing PDFs are verified against the
current Markdown, and changed revisions are rendered afresh. Store provenance in the private
cache; it does not grant publication approval or change the diary's confirmation state.

The page offers a date list, month filter, text search, separate version selection, HTML
reading, inline PDF preview, and PDF/Markdown downloads. Raw source exports, credentials,
filesystem listings and arbitrary paths are not routes. Images must be local and within
configured evidence roots. HTML strips active markup and external picture loads; responses
use no-store, a restrictive CSP, and explicit file types. PDF byte ranges are supported.

Keep generic code and synthetic tests in the portable skill repository. Diary bodies,
pictures, account configuration, cache receipts and production service adapters stay private.
