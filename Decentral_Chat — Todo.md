# Decentral\_Chat — File Converter Upgrade: Master Plan

*Based on a hands-on review of both repositories (cloned and read) plus three small experiments run in a sandbox · 15 November 2026 · Revision 2 (complete, no day-wise schedule)*

## 1. Executive summary

Your converter today is a set of Python functions that mostly extract text and rebuild a plain document. That is why design is lost: a DOCX goes in, only `paragraph.text` comes out. ConvertX gets its quality by doing the opposite: it never re-creates a document itself, it hands each job to a specialist engine (LibreOffice, Pandoc, FFmpeg, ImageMagick/libvips, Poppler and others) behind a registry that knows which engine can do which conversion.

This plan brings that architecture into your Python backend, hardens it, and connects it to your end-to-end encryption.

Six decisions drive everything else:

1. **Re-implement the ConvertX pattern in Python; do not copy its TypeScript.** ConvertX is AGPL-3.0 (section 2.5).
2. **One engine per format family, with ordered fallback chains,** chosen by a benchmark on a golden test corpus rather than by guesswork.
3. **Convert-then-encrypt.** The server converts a plaintext file inside a short-lived sandbox, returns the result, and the browser encrypts it with your existing AES-GCM chat key before it is ever stored. Today converted files skip encryption entirely.
4. **Sandboxed worker with a real job queue and real progress.** Today conversion runs inside the API process that holds your Firebase credentials and signing key, with fake progress timers.
5. **Honest fidelity tiers.** Same-family conversions (DOCX to PDF, FLAC to WAV) can be verified as near-exact. Reconstructive ones (PDF to DOCX) cannot be guaranteed, because a PDF stores positioned glyphs, not paragraphs and tables. The UI tells the user which tier they are getting.
6. **Strangler rollout.** Build v2 beside v1, run both against the same corpus, switch with a feature flag, keep a kill switch.

**What "without loss" means in this project.** It is a measurable contract per tier (section 4), not a promise. For example: DOCX to PDF keeps the page count and fonts embedded; PNG to lossless WebP is pixel-identical; MP3 to FLAC keeps duration within 50 ms and keeps tags and cover art.

**How to read this plan.** Work is organised in phases (section 6) ordered by dependency, not by calendar. Each phase ends at a gate; you decide the schedule. Decisions that need your input are collected in section 11.

## 2. What I found

### 2.1 Defect register for the current converter

Everything below comes from reading the code. Items marked **\[ran\]** I also reproduced. The HTTP-path bugs (D-01) come from reading `service.py`; Phase 0 adds a regression test that confirms them against a running server.

| ID | Finding | Where | Impact |
| --- | --- | --- | --- |
| D-01 | The HTTP handler re-declares its own extension lists instead of calling `perform_file_conversion`, and those lists are shorter than the advertised map. By code reading, these fall through to "not supported": any audio target of flac, opus or wma; flac/wma/opus audio sources; tiff and ico image sources; flv/wmv video sources and targets; video to GIF; GIF to MP4. | `converters/service.py`, `convert_uploaded_file` | UI offers conversions that return HTTP 500 |
| D-02 | The advertised map includes zip, tar, gz, 7z and rar, but no code path implements them. | `service.py`, `get_supported_conversions` | Dead options in the UI |
| D-03 | `ALLOWED_EXTENSIONS` does not list html, tiff, ico, opus, wma, flv, wmv, yet the converter treats them as valid sources. | `core/config.py` | Uploads of these types are classified inconsistently |
| D-04 | Progress is fake. The browser increments 10 percent every 200 ms up to 90, and the server uses `asyncio.sleep` timers for audio and video. | `app.js` around line 2995, `service.py` | Progress bar says nothing about the real job |
| D-05 | No ownership check: the convert endpoint loads `file:{file_id}` and never compares `file_meta.user_id` with the caller. | `service.py` | Any logged-in user who learns a file ID can convert, and then download, someone else's file |
| D-06 | `serve_upload` only requires a valid login, not membership of the chat or ownership. It also accepts the JWT in a `?token=` query string. | `files/handlers.py`, `serve_upload` | Cross-user file access by URL; tokens leak into logs and history |
| D-07 | E2EE is bypassed. The conversion flow uploads the raw file (no encryption), and converted files are sent as `__converted` references that skip the encryption block entirely. | `app.js` \~3029 and \~3983 versus the encrypting path at \~3997 | Plaintext copies of documents sit on server disk |
| D-08 | **\[ran\]** Document conversions rebuild from `paragraph.text`: DOCX to HTML, TXT, MD and RTF drop bold, tables, lists, images and headers. TXT to DOCX discards blank lines and indentation. MD to DOCX writes raw markdown syntax as body text. HTML to DOCX or PDF strips all markup. | `converters/documents.py` | The main "design is lost" cause |
| D-09 | TXT, HTML, MD, CSV and XLSX to PDF depend only on `docx2pdf`, which drives Microsoft Word. It cannot work on a Linux server. | `documents.py` | These routes fail on any Linux deploy, including the cloud plan in your TODO |
| D-10 | Subprocesses run inside the API process via `asyncio.to_thread`. FFmpeg has no timeout, there is no concurrency cap, LibreOffice uses the shared default profile, and orphaned `soffice.bin` processes are not killed. | `audio.py`, `video.py`, `documents.py` | Hangs, resource exhaustion, and **\[ran\]** silent failures under concurrency |
| D-11 | Output is never verified, and raw exception text (including FFmpeg stderr) is returned to the client. | `service.py` | Corrupt output reported as success; internal detail leaks |
| D-12 | Converted files are stored permanently with absolute server paths in Redis and Firestore. There is no cleanup. | `service.py` | Privacy exposure and unbounded storage growth |
| D-13 | **\[ran\]** Image pipeline loses data: an animated GIF came out with 1 frame instead of 3; image to PDF re-encodes JPEG at quality 95 instead of embedding it; ICC profiles and EXIF are not carried over. | `converters/images.py` | Visible quality and metadata loss |
| D-14 | **\[ran\]** `test_converter.py` and `test_all_features.py` contain zero `assert` statements. | `backend/` | Nothing would catch a regression |
| D-15 | `_validate_file_magic` returns True on any exception (fail-open) and only checks signatures for images. | `core/security.py` | Weak upload validation |

### 2.2 The three experiments

1. **Formatting loss.** I built a DOCX with a heading, a bold red run, a 2x2 table and a bullet. Applying the same logic as `documents.py` (paragraph text only) produced HTML with no table, no bold, and not even the table's text. Pandoc on the same file preserved the table, the bold and all cell text.
2. **LibreOffice concurrency.** Three simultaneous `soffice --convert-to pdf` jobs on the default profile: one silently produced no PDF. The same three jobs with a separate profile each (`-env:UserInstallation=file:///...`) all succeeded. This is why the plan mandates one throwaway profile per job.
3. **Animated GIF.** A 3-frame GIF run through the exact `images.py` GIF path (transpose, convert to palette, save) came out with 1 frame.

### 2.3 What ConvertX does well (adopt the technique)

- **Declarative per-engine modules.** Each converter file exports a `properties` object listing what it reads and writes; a central registry builds the "possible targets" table from them. One source of truth, no duplicated lists (the exact bug class in D-01).
- **Explicit engine choice and priority.** Converters are ordered (for example Inkscape ahead of ImageMagick for EMF), and the user can pick the engine when several qualify.
- **Explicit LibreOffice filter maps.** Import and export filters are named per format (`MS Word 2007 XML`, `writer_pdf_import`, `Calc MS Excel 2007 XML` and so on) instead of relying on guessing.
- **Engine-specific quality tricks.** FFmpeg: map and copy attached cover art for audio targets, `-vn` for WAV and AAC, scale-down for ICO, codec shortcuts like `h265.mp4`. ImageMagick: `-auto-orient`, `-density 300` for PDF input, multi-size ICO, special EMF handling.
- **Multi-file output** (a PDF turning into `name-1.png`, `name-2.png`) is detected and recorded as separate results.
- **Operational controls:** `MAX_CONVERT_PROCESS` concurrency chunking, `AUTO_DELETE_EVERY_N_HOURS` cleanup, environment-driven FFmpeg arguments for hardware acceleration.
- **Mockable command execution.** Every wrapper accepts an injected `execFile`, so unit tests check the exact command line without installing the tools. A shared "common tests" suite runs against every converter.

### 2.4 What ConvertX does not give you (you must add it)

- Per-process timeouts and process-group kills (its `execFile` calls set none).
- Isolated LibreOffice profile per job (its wrapper uses the default profile, so it inherits the concurrency problem from experiment 2).
- Output verification. Its wrappers resolve "Done" when the process exits, without checking that a valid output file exists.
- Fidelity measurement. It has no check that the result resembles the input.
- A sandbox. Its README says to allow only trusted users, because it runs parsers on untrusted files without isolation.
- Anything about E2EE. It is a standalone web app with its own accounts and database.

### 2.5 Licensing

ConvertX is AGPL-3.0. Copying or adapting its code into your project would oblige you to offer your whole project under AGPL, including to users who only reach it over the network. The tools it wraps (LibreOffice, Pandoc, FFmpeg, ImageMagick, Poppler) are separate programs under their own licenses, and calling them as command-line subprocesses is the normal approach. Check each license when you publish a Docker image that bundles them. I am not a lawyer; confirm this before release.

Options considered:

- **(a) Re-implement the pattern in Python (recommended).** Ideas, architecture and the public tools' command-line options are not copyrightable the way source code is. Write your own registry, wrappers and tests, and consult ConvertX only as a reference for which options matter.
- **(b) Run unmodified ConvertX as a separate service.** Rejected. It is a web application with cookie-JWT accounts and its own SQLite database and no stable programmatic API. It cannot take part in your encrypt-after-convert flow, and any customization would trigger AGPL obligations.
- **(c) Relicense your repo as AGPL.** Only if you want that for other reasons.

### 2.6 ConvertX technique adoption map

| ConvertX technique | Adopted as | Plan location |
| --- | --- | --- |
| Per-engine `properties` (reads/writes) | `EngineSpec` and `Route` dataclasses; capability list generated from the registry | Section 3.3, Phase 1 |
| Priority-ordered converters, user-selectable engine | Ordered engine chains, optional `engine` job parameter | Sections 3.4, 3.5 |
| Named LibreOffice filters | Filter maps in `engines/libreoffice.py` | Phase 2 |
| FFmpeg cover-art mapping, `-vn`, codec shortcuts | Audio codec table and video recipes | Phase 3 |
| ImageMagick `-auto-orient`, multi-size ICO | Pillow EXIF transpose, ICO size set; ImageMagick only for the long tail | Phase 3 |
| Multi-file output detection | PDF to images returned as one ZIP; batch ZIP in Phase 7 | Phases 2, 7 |
| `MAX_CONVERT_PROCESS`, auto-delete | Global semaphore, per-engine caps, janitor with 15-minute TTL | Phases 1, 4 |
| Env-driven FFmpeg arguments | `CONVERTER_FFMPEG_EXTRA_ARGS` and hardware-acceleration setting | Section 3.6 |
| Injected `execFile` and common tests | Fake runner, command snapshot tests, shared engine contract tests | Phase 1, section 8 |
| *Not in ConvertX:* timeouts, profile isolation, verification, fidelity metrics, sandbox, E2EE | Added by this plan | Sections 4, 5, Phases 1 to 4 |

## 3. Target architecture

### 3.1 Principles

1. **Delegate to specialist engines.** Never rebuild a document from extracted text when an engine can convert it natively.
2. **Single source of truth.** Supported routes come from the registry only. The API, the UI and the tests all read it.
3. **Untrusted input.** Every file is treated as hostile; every engine runs with limits, no network, no secrets.
4. **Ephemeral by default.** Plaintext exists only in a per-job temp directory that is destroyed when the job ends.
5. **Verify before you claim success.** Each result is opened and checked before the job is marked done.
6. **Say what you did.** Every job reports engine, fidelity tier and warnings.

### 3.2 Request flow (convert-then-encrypt)

```
Browser                     API (aiohttp)                 Queue (Redis)      Worker (sandbox)
 | 1. pick file + target        |                              |                   |
 | 2. POST /api/convert/jobs -> | auth, ownership, limits,     |                   |
 |    (multipart, TLS)          | sniff type, write to         |                   |
 |                              | /work/<job>/in, enqueue ---> |                   |
 | <- 202 {job_id}              |                              | 3. dequeue -----> |
 | 4. poll or WS: stage, % <----|<---- progress/state ---------|<- run engine chain|
 |                              |                              |   verify output   |
 | 5. GET .../result?t=<token>  |<-------- /work/<job>/out ---------------------- |
 | <- converted bytes (stream, then delete job dir)            |                   |
 | 6. CryptoEngine.encryptBuffer (AES-GCM chat key)            |                   |
 | 7. POST /api/upload/file (encrypted blob) -> normal send path                   |
```

Steps 6 and 7 reuse code you already have (`CryptoEngine.encryptBuffer` and the upload path). The server never stores the plaintext result and never writes it to Firestore.

### 3.3 Backend layout

```
backend/app/files/converters/
  registry.py        EngineSpec, Route, capability probe, route lookup
  runner.py          async subprocess runner: timeout, process-group kill, rlimits
  workspace.py       per-job temp dir, secure cleanup
  jobs.py            job model, state machine, queue, concurrency semaphore
  verify.py          output validators (magic, re-open, page count, duration)
  fidelity.py        tier definitions, comparison metrics, warnings
  engines/
    base.py          BaseEngine: build_command(), parse_progress(), verify()
    libreoffice.py   filter maps, isolated profile, macro lockdown
    pandoc.py        --sandbox, media extraction, reference docx
    ffmpeg.py        codec table, progress parsing, cover art, protocol whitelist
    raster.py        Pillow + pillow-heif; ImageMagick/libvips for the long tail
    poppler.py       pdftotext, pdftoppm, pdftohtml
    pdf2docx_engine.py
    img2pdf_engine.py
    sheets.py        csv/xlsx with encoding detection
  routes.py          thin aiohttp handlers (v2) + v1 compatibility shims
  worker.py          queue consumer entry point (Phase 4b)
```

`service.py` keeps `perform_file_conversion` and `get_supported_conversions` as thin shims that call the registry, so old callers and the old UI keep working during migration.

### 3.4 Engine routing matrix

Tiers are defined in section 4: **A** exact or lossless, **B** high fidelity, **C** reconstructive. The order of engines in each chain is a starting hypothesis; the Phase 1 benchmark confirms or reorders it.

| Family | Routes | Primary engine | Fallbacks | Tier | Key technique |
| --- | --- | --- | --- | --- | --- |
| Office to PDF | DOCX, DOC, ODT, RTF, PPTX, PPT, ODP, XLSX, XLS, ODS to PDF | LibreOffice headless | none; fail with a clear error | B | Metric-compatible fonts installed; Writer, Impress and Calc PDF export filters; isolated profile |
| Office to office | DOCX, ODT, RTF, DOC; XLSX, ODS, XLS; PPTX, ODP, PPT | LibreOffice | none | B | Explicit infilter and outfilter map per format |
| Document to light markup | DOCX, ODT, RTF to HTML, MD, TXT | Pandoc | LibreOffice HTML export | B (structure kept, page layout not) | `--extract-media`; self-contained HTML; keep tables, lists, links |
| Markup to document | MD, HTML to DOCX or ODT | Pandoc | none | B | `--reference-doc` template so styles look intentional |
| Markup or text to PDF | MD, HTML, TXT to PDF | LibreOffice writer or web export | WeasyPrint, decided in the Phase 2 spike | B | Pandoc turns MD into styled HTML first; UTF-8 text import filter keeps whitespace |
| PDF to editable | PDF to DOCX | pdf2docx (already in your requirements) | LibreOffice `writer_pdf_import`, then text-only flagged degraded | C | Engine order set by benchmark; degraded output is labelled in the UI |
| PDF to text, HTML | PDF to TXT, HTML | Poppler `pdftotext -layout`, `pdftohtml` | none | C | Layout mode keeps columns |
| PDF to images | PDF to PNG or JPG | Poppler `pdftoppm -r 200` | `pdftocairo` | A (raster) | One file per page, returned as a ZIP; page-range option |
| Images to PDF | JPG, PNG, TIFF, WebP to PDF | img2pdf | Pillow with alpha flatten | A | Lossless embedding: JPEG bytes are not re-encoded |
| Raster to raster | PNG, JPG, WebP, BMP, TIFF, GIF, AVIF, HEIC, ICO | Pillow (+ pillow-heif) | ImageMagick or libvips for rare formats and very large images | A or B | Keep ICC profile, apply EXIF orientation, explicit alpha policy, keep animation frames |
| Vector to raster | SVG to PNG, JPG | rsvg-convert or resvg | Inkscape | B | Explicit DPI; ImageMagick's SVG reader is not used on untrusted input |
| Audio | MP3, WAV, OGG, AAC, M4A, FLAC, WMA, OPUS | FFmpeg | none | A (lossless to lossless) or B | Codec and bitrate table, `-map_metadata 0`, cover-art mapping |
| Video | MP4, WebM, MKV, MOV, AVI, FLV, WMV; video to audio; video to GIF | FFmpeg | none | B | CRF defaults, `+faststart`, yuv420p for compatibility, two-pass palette for GIF |
| Spreadsheet data | CSV to XLSX; XLSX to CSV | LibreOffice Calc (to CSV, all sheets) and openpyxl (to XLSX) | openpyxl with cached values | B | Charset detection; keep leading zeros as text; CSV filter tokens for delimiter and UTF-8 |
| Archives | ZIP, TAR, GZ, 7Z | removed in Phase 0 | optional safe implementation in Phase 7 | n/a | Advertised today but not implemented (D-02) |

### 3.5 Job API v2

Old routes (`/api/files/convert`, `/api/files/conversion-formats`, `/api/files/conversion-progress/{id}`) stay as shims for at least two releases.

| Method and path | Purpose | Notes |
| --- | --- | --- |
| `GET /api/convert/capabilities` | Full route table: source, target, engine chain, tier, options, size limits | Built from the registry; the UI renders from it; ETag supported |
| `POST /api/convert/jobs` | Multipart: file, target, optional engine and options | Returns 202 `{job_id}`; enforces auth, limits, type sniffing |
| `GET /api/convert/jobs/{id}` | State, stage, real percent, warnings, tier, engine | Owner only. Optional push over your existing WebSocket |
| `GET /api/convert/jobs/{id}/result` | Streams the output once, then deletes it | One-time token, 10-minute expiry, owner only |
| `DELETE /api/convert/jobs/{id}` | Cancel | Kills the process group, wipes the job directory |

**Job states:** `queued`, `running` (with a stage: `probing`, `converting`, `verifying`), `done`, `failed`, `cancelled`, `expired`. Job records live in Redis with a TTL of 15 minutes and contain no file paths and no plaintext content.

**Example: capabilities (one entry)**

```json
{
  "version": "2026-11-15",
  "routes": [{
    "src": "docx", "dst": "pdf", "tier": "B",
    "engines": ["libreoffice"],
    "options": {"page_range": "string", "engine": "enum"},
    "limits": {"max_bytes": 52428800, "max_pages": 300},
    "warnings_possible": ["font_substitution"]
  }]
}
```

**Example: create job**

```
POST /api/convert/jobs   (multipart/form-data)
  file=<binary>   target=pdf   options={"page_range":"1-5"}
-> 202 {"job_id":"b3f1...","state":"queued","queue_position":1}
```

**Example: job status**

```json
{
  "job_id": "b3f1...", "state": "running", "stage": "converting",
  "percent": null, "engine": "libreoffice", "tier": "B",
  "warnings": [], "queue_position": 0
}
```

`percent` is `null` when the engine cannot measure progress (the UI then shows an indeterminate bar). On `done`, the status also carries `result_token` (single use) and `result_name` (sanitised display name).

**Error codes and HTTP status**

| Code | HTTP | Friendly message (UI) |
| --- | --- | --- |
| `E_UNSUPPORTED` | 400 | That conversion isn't available. Try one of: (list from registry) |
| `E_TYPE_MISMATCH` | 400 | The file content doesn't match its extension |
| `E_TOO_LARGE` | 413 | The file is larger than the limit for this type |
| `E_CORRUPT` | 422 | The file looks damaged and can't be read |
| `E_PASSWORD_REQUIRED` | 422 | The file is password-protected; remove the password and retry |
| `E_TIMEOUT` | 504 | The conversion took too long and was stopped |
| `E_ENGINE_UNAVAILABLE` | 503 | This conversion is temporarily unavailable |
| `E_VERIFY_FAILED` | 500 | The result failed a safety check and was discarded |
| `E_LIMIT` | 429 | Too many conversions in progress; try again shortly |

### 3.6 Configuration reference

All values are environment-driven; defaults are the starting values from section 9.3.

| Setting | Default | Purpose |
| --- | --- | --- |
| `CONVERTER_V2` | off | Feature flag and kill switch for the v2 path |
| `CONVERTER_WORK_DIR` | `/work` | Per-job directories (tmpfs-backed) |
| `CONVERTER_JOB_TTL_SECONDS` | 900 | Job record and job directory lifetime |
| `CONVERTER_RESULT_TOKEN_TTL_SECONDS` | 600 | One-time result token lifetime |
| `CONVERTER_MAX_CONCURRENT` | min(CPU cores, 4) | Global running-job semaphore |
| `CONVERTER_ENGINE_CAPS` | `libreoffice=2` | Per-engine concurrency caps |
| `CONVERTER_USER_MAX_RUNNING` | 2 | Running jobs per user |
| `CONVERTER_USER_HOURLY_CAP` | 30 | Jobs per user per hour |
| `CONVERTER_LIMITS_*` | per family | Max bytes, pages, duration, megapixels, timeouts |
| `CONVERTER_FFMPEG_EXTRA_ARGS` | empty | Extra FFmpeg arguments, for example hardware acceleration |
| `CONVERTER_JANITOR_INTERVAL_SECONDS` | 300 | Sweep for leftover job directories |
| `CONVERTER_QUEUE_BACKEND` | `redis` | `memory` for development and tests |

## 4. Fidelity policy and how it is measured

### 4.1 Tiers

- **Tier A, exact or lossless.** The output decodes to identical content (pixels, samples, cell values) or embeds the source data unchanged. Acceptance is automated equality or a strict metric.
- **Tier B, high fidelity.** A native engine produces the same visual or semantic result. Small differences are possible (font substitution, anti-aliasing). Acceptance is structure and layout metrics within thresholds.
- **Tier C, reconstructive.** The target stores structure the source does not (paragraphs and tables from a PDF). The engine infers it. Acceptance is text completeness and basic structure, and the user is warned.

### 4.2 Measurable acceptance thresholds

The numbers for Tier C are starting values; Phase 1's benchmark calibrates them against your real corpus.

| Route | What is measured | Threshold |
| --- | --- | --- |
| DOCX, PPTX, XLSX to PDF | Page count equals the approved baseline; every font in the PDF is embedded (`pdffonts`); no substitution warning for fonts in the source; per-page SSIM against the approved baseline render at 100 dpi | Page count exact; fonts 100 percent embedded; SSIM at least 0.98 inside the pinned Docker image |
| DOCX or ODT to HTML or MD | Counts of tables, images, headings, list items and hyperlinks versus the source XML | 100 percent equal |
| MD or HTML to DOCX | Heading levels become Heading styles; tables become real tables; code blocks get a code style | 100 percent of structures mapped |
| PDF to DOCX (Tier C) | Word recall against `pdftotext` of the source; embedded image count; page count | Recall at least 0.97; images at least 90 percent; pages within plus or minus 1 |
| Image to lossless target (PNG, lossless WebP, TIFF) | Pixel comparison after the same color mode and orientation | Identical |
| Image to lossy target | PSNR or SSIM at default quality; dimensions after orientation; alpha handled per policy | PSNR at least 35 dB or SSIM at least 0.95; ICC kept when the target supports it |
| Animated GIF or WebP | Frame count and per-frame delay | Equal count; delay within 10 ms |
| JPEG to PDF | `pdfimages -all` extracts a JPEG whose hash equals the source | Identical bytes |
| Audio | Duration, sample rate, channels, tags, cover art | Duration within 50 ms; rate and channels equal unless the target forces otherwise; title, artist, album and cover kept when the target supports them |
| Video | Duration, resolution, audio stream presence, rotation, moov atom position for MP4 | Duration within 0.1 s; resolution equal; faststart present |
| CSV and XLSX | Cell values, row and column counts, Unicode, leading zeros | Cell-by-cell equal |

### 4.3 Warnings shown to the user

Each job returns a `warnings` list that the UI shows next to the result. Examples:

- "This conversion rebuilds the layout from a PDF and may differ from the original." (PDF to Word)
- "This format is lossy; the file will be re-compressed." (to JPEG, MP3, WebP lossy)
- "Transparency was replaced with white." (PNG to JPEG)
- "Only the first frame was kept." (animated source to a non-animated format)
- "Location data was removed from this photo." (default privacy behavior)
- "Fonts were substituted: Name A became Name B." Detection technique: read the fonts declared in the source (`word/fontTable.xml` for DOCX) and compare with `pdffonts` output of the result.

### 4.4 Visual regression technique

1. Render each Tier B output to PNG with `pdftoppm -r 100`.
2. Compare with an approved baseline using SSIM (scikit-image) or ImageMagick `compare -metric SSIM`.
3. A human approves each baseline once; later changes must be re-approved on purpose.
4. Baselines are only valid inside the pinned converter image (fixed fonts and engine versions). Run the visual suite in that image only, otherwise cross-machine drift causes false failures.

---

## Implementation status

Updated after building the v2 converter. Verified by running the code, not by inspection.

### Defect register

| ID | Status | Evidence |
| --- | --- | --- |
| D-01 | **Fixed** | `service.py::get_supported_conversions` now returns `routes_table.supported_targets(...)`. The HTTP handler and the UI read the same registry. |
| D-02 | **Fixed** | Phase 0 removed the advertised-but-unimplemented archives. Phase 6 brought back **only** zip and tar, behind a real engine with traversal and zip-bomb guards; gz/7z/rar stay unimplemented and return `400 E_UNSUPPORTED`. |
| D-03 | **Fixed** | `ALLOWED_EXTENSIONS` now lists every converter source extension: images gained tiff/tif/ico/avif/heic/heif, video flv/wmv, audio opus/wma, documents html/htm. No converter source is silently classified as `document`. |
| D-04 | **Fixed** | Jobs carry real `state` and `stage` (`probing`/`converting`/`verifying`). The browser's fake 10%-per-200ms timer was deleted; the UI now polls the status endpoint, shows the stage label, and only moves the bar when the engine reports a real `percent`. |
| D-05 | **Fixed** | `convert_uploaded_file` compares `file_meta['user_id']` with the caller before reading bytes. v2 job status/result/cancel go through `JobStore.get_owned`, covered by a test that reads another user's job and gets 404. |
| D-06 | **Fixed** | Media elements use short-lived signed URLs (`?mt=`, one file / one user / one hour) minted by `POST /api/files/media-urls` after the entitlement check. `serve_upload` no longer reads `?token=`; it takes the Authorization header only. It resolves the file record via `_file_meta_for_path` and allows exactly two cases: the uploader, or a member of the chat the file was sent to (`is_chat_member`). Unindexed files are refused with 403. Recipients keep access because `create_message` calls `bind_file_to_chat` for every attachment at send time, so the file-to-chat link is durable in Redis and Firestore. Verified by `testing/test_security_regressions.py`. |
| D-07 | **Fixed** | The v2 flow downloads the result as a plain `File` and hands it to the normal send path, so `CryptoEngine.encryptBuffer` runs before upload. The old `__converted`/`serverId` shortcut that skipped encryption was deleted, along with its preview branches. |
| D-08 | **Fixed for installed engines** | Conversion is delegated to LibreOffice/Pandoc/Pillow/FFmpeg instead of rebuilding from `paragraph.text`. Routes whose engine is missing are no longer advertised (see note below). |
| D-09 | **Fixed for installed engines** | `docx2pdf`/Microsoft Word is no longer on any route. PDF export goes through LibreOffice or Pandoc. |
| D-10 | **Partial** | `runner.py` adds timeouts and process-group kills; `engines/libreoffice.py` uses a throwaway profile per job; `jobs.py` enforces global and per-engine semaphores. Still runs in the API process rather than a separate worker. |
| D-11 | **Fixed** | Every result passes `verify.verify_output` (magic bytes, archive integrity, UTF-8, PDF page count) before the job is marked done. Raw exception text never reaches the client. |
| D-12 | **Fixed** | Plaintext lives only in `work/<job_id>/`; the directory is wiped on result collection, cancel, and by `workspace.sweep_expired`. Job records hold no paths. |
| D-13 | **Fixed** | `engines/raster.py` preserves animation frames, carries the ICC profile, applies EXIF orientation, and warns when alpha or frames are lost. `img2pdf` embeds JPEG bytes without re-encoding. |
| D-14 | **Fixed** | New tests under `testing/`: `smoke_registry.py`, `test_v2_api.py` (real HTTP), `check_server_imports.py`. They assert and they run. |
| D-15 | **Fixed** | `_validate_file_magic` fails closed on unreadable input and validates PDF, audio, video, OOXML/ZIP, OLE2 and text, not just images. |
| D-16 | **Fixed** | `get_queue` treated any non-`None` client as real Redis, so the development `MockRedis` fallback was selected as the queue backend. It has no `BRPOP`, so all four workers failed on every poll and **every conversion stalled in `queued`**. The fallback is now detected by capability and the in-process queue is used instead. |

### Phases

- **Phase 0 (defect triage)** - done for D-01, D-02, D-05, D-11, D-13, D-15.
- **Phase 1 (registry, engines, verify, workspace, jobs)** - done. `registry.py`, `routes_table.py`, `fidelity.py`, `verify.py`, `workspace.py`, `settings.py`, `runner.py`, `jobs.py`, `dispatch.py`, `routes.py`, plus eight engine adapters.
- **Phase 2 (routing matrices)** - done. 303 routes generated from engine capability declarations.
- **Phase 3 (per-family fidelity)** - done. Every adapter is live. LibreOffice 26.8.3.1, Pandoc 3.14, Poppler 25.07 and FFmpeg are installed and detected. `settings.which()` was extended to search Windows install directories after finding that winget installs these tools without adding them to PATH: a binary that worked in the terminal was invisible to the server, which silently disabled every route depending on it.
- **Phase 4 (worker + queue)** - done. `queue.py` provides `MemoryQueue` and `RedisQueue` behind one interface. `jobs.py` holds staging, the runner, the consumer loop and the inline pool. `create_job_handler` stages the bytes and enqueues only the job id. `_start_converter_runtime` starts the pool at boot and also starts `janitor_loop`, which had been written but never wired up, so expired plaintext had quietly accumulated in `backend/work`. Verified by `testing/test_queue_e2e.py` (md to docx through the queue).
- **Phase 5 (multi-file output + batch ZIP)** - done. A result with more than one
  file (PDF to one PNG per page) used to return `files[0]` and silently drop the
  rest; `workspace.package_outputs` now zips them. `batch.py` adds
  `POST /api/files/batch` plus status and result endpoints: N files in, one ZIP
  out, with a `manifest.json` recording per-file outcomes so 19 good files are
  still delivered when 1 fails. Verified by `testing/test_phase5_batch_zip.py`
  and `testing/test_phase5b_batch_api.py`.
- **Phase 6 (archives)** - done, safely. D-02 removed zip/tar because nothing
  implemented them; `engines/archive.py` brings back **zip and tar only**, and
  treats extraction as hostile input: path traversal and absolute paths are
  refused, member count, expanded size and compression ratio are capped before
  a byte is written. `zip -> tar` is a real repack now. Verified by
  `testing/test_phase6_archives.py`, which feeds it a `../../escaped.txt` member
  and an 8 MB-of-zeros bomb and requires both to be rejected.
- **Phase 7 (hardening)** - done. Three defects fixed: `CONVERTER_USER_HOURLY_CAP`
  was declared but never enforced (one account could occupy the pool
  indefinitely); `CONVERTER_RESULT_TOKEN_TTL_SECONDS` was declared but never
  applied, so a download token stayed live for the full 15-minute job TTL; and
  `JobStore.purge` cleaned `_jobs` but not `_user_jobs`, so that list grew
  forever with ids that no longer resolved. Verified by
  `testing/test_phase7_hardening.py`.

- **Phase 8 (converter UI)** - done. Three gaps closed in `frontend/`. The
  local fallback list still advertised `gz`, `7z` and `rar` as conversion
  targets even though Phase 6 only implements zip and tar, which recreated the
  D-02 dead-option bug in the client after it was fixed on the server; the
  archive block is now `zip -> tar` and `tar -> zip` only. A batch control
  (`#convertAllBtn`) sends every staged file in one request, polls the aggregate
  batch endpoint for `done`/`failed` counts, and hands the returned ZIP to the
  normal send path as a real `File` so it is still encrypted with the chat key.
  The button only appears when 2 to 20 files are staged and a target is chosen.

### Verification performed

- `testing/smoke_registry.py` - 373 routes, tiers, engine availability (all eight engines), workspace lifecycle, corrupt-PDF rejection.
- `testing/check_frontend_syntax.py` - parses `app.js` and asserts the E2EE
  helpers are still referenced, so a syntax slip cannot ship silently.
- `testing/check_frontend_batch_ui.py` - 21 checks guarding the UI contract:
  every element id the batch flow reads exists in `index.html`, the fallback
  conversion map no longer offers gz/7z/rar, the handler is defined once and
  wired to the button, the batch result stays a real `File` (so E2EE is not
  bypassed), and the client cap matches `MAX_BATCH_FILES` in `batch.py`.
- `testing/test_v2_api.py` - 22 checks over real HTTP: PNG to WEBP gives `202` then `done` and a real `RIFF`/`WEBP`; bad token `403`; single-use token; `png -> gz` still `400 E_UNSUPPORTED`; `zip -> tar` now succeeds through the archive engine and yields a real USTAR; second user gets `404`.
- `testing/check_server_imports.py` - the live `DecentralChatServer` registers all nine v2 routes (jobs plus batch); `zip` now advertises `tar`, and every advertised target resolves to a route with an installed engine.
- `testing/test_phase5_batch_zip.py` - a two-page PDF produces two PNGs, and the
  download is a ZIP containing both rather than page 1 only.
- `testing/test_phase5b_batch_api.py` - 17 checks over real HTTP: two files in,
  one ZIP out, bad token 403, single-use, a mixed batch rejected whole with
  `E_UNSUPPORTED` and nothing half-queued, another user gets 404.
- `testing/test_phase6_archives.py` - pack, repack, `../` traversal refused, and
  an 8 MB-of-zeros archive refused as a decompression bomb.
- `testing/test_phase7_hardening.py` - hourly cap enforced and rolling, cap=0
  means unlimited, token TTL shorter than the job TTL, and `purge`/`sweep` no
  longer leak ids in `_user_jobs`.
- `testing/test_v2_api.py` - 22 checks including `zip -> tar` now producing a
  real USTAR archive.
- `testing/test_security_regressions.py` - 28 checks driving the real handlers: refresh replay inside the grace window succeeds and outside it returns 401; anonymous file request 401, logged-in stranger 403, chat member 200, uploader 200, unindexed file 403; membership rebuilt from Firestore after an eviction; attachments record their chat at send time.

### Known gaps

1. **Fixed.** LibreOffice, Pandoc and Poppler are installed. All eight engines report available.
2. **Fixed.** Jobs are queued and executed by a worker pool (`jobs.worker_loop`).
3. `percent` is coarse. Only `done` reports 100; running jobs report `null`.
4. The conversion UI was verified statically (`node --check`, endpoint wiring, no leftover v1 calls) and the API over real HTTP. The browser flow was not driven end to end, because this sandbox has no Firebase credentials to log in with.
5. **Fixed.** Files uploaded before `bind_file_to_chat` existed carried no `chat_id` and were refused with 403. `membership.backfill_attachment_chat_ids()` rebuilds the link from the `messages` collection at startup (called from `migrate_existing_files`). Idempotent, covered by `testing/test_attachment_backfill.py`.

### Session lifetime and cache-loss resilience

Two failure modes were fixed alongside D-06 because they are why a session or a conversation could vanish after a few idle days.

**Refresh rotation.** The old refresh token used to be revoked the instant it was redeemed. A dropped response, a closed tab, or two tabs refreshing at once left the client holding a token the server had already killed, so a network hiccup ended in a forced re-login. `refresh_token` now records `rotated_at` next to `revoked` and accepts reuse for `REFRESH_ROTATION_GRACE_SECONDS` (120 s). A missing or malformed timestamp is treated as epoch 0 and refused, so an old revoked token cannot slide through.

**Cache loss.** `chats/membership.py` treats Redis as a cache and Firestore as the source of truth. `get_chat_members` repopulates `chat_members:{chat_id}` and `user_chats:{user_id}` after an eviction, so a conversation neither disappears from a recipient's sidebar nor loses download rights when the cache is cold.

Both are covered by `testing/test_security_regressions.py`: 28 checks covering refresh replay inside and outside the window, anonymous / stranger / member / uploader / unindexed file access, membership repair, and attachment-to-chat binding.


---

## Work log

Ticked only where the behaviour was run and observed, not merely written.

### Converter architecture

- [x] Defect triage for D-01, D-02, D-03, D-04, D-05, D-07, D-11, D-13, D-14, D-15
- [x] `registry.py` / `routes_table.py` as the single source of supported routes (D-01, D-02)
- [x] `runner.py` with timeouts and process-group kills (D-10, partial)
- [x] `workspace.py` per-job temp dir plus `sweep_expired` janitor (D-12)
- [x] `verify.py` output validation before a job is marked done (D-11)
- [x] `fidelity.py` tiers A/B/C and the warning vocabulary
- [x] Engine adapters: raster, img2pdf, pdf2docx, libreoffice, pandoc, poppler, ffmpeg
- [x] Job API v2: capabilities, create, status, result, cancel
- [x] `service.py` reduced to a shim over the registry so v1 callers keep working
- [x] Convert-then-encrypt: converted bytes go through `CryptoEngine.encryptBuffer` (D-07)
- [x] Phase 4: worker pool + queue consumer (`queue.py`, `stage_upload`, `run_one`, `worker_loop`, `start_inline_workers`); verified by `testing/test_queue_e2e.py`
- [x] Phase 5: multi-file results returned as one ZIP; batch endpoint (`batch.py`)
- [x] Phase 5b: N files in, one ZIP out, with a manifest of per-file outcomes
- [x] Phase 6: safe zip/tar engine; traversal and decompression bombs refused
- [x] Phase 7: hourly cap, result-token TTL and `_user_jobs` leak all enforced
- [x] Phase 8: converter UI offers no dead archive targets; batch control with one-ZIP output

### File access and sessions

- [x] `serve_upload` entitlement: uploader, or member of the file's chat (D-06)
- [x] Session JWT no longer accepted in the query string (D-06)
- [x] Every attachment bound to its chat at send time (`create_message`)
- [x] Membership and sidebar repaired from Firestore after a cache eviction
- [x] Refresh-token rotation grace window, so a dropped reply is not a logout
- [x] Signed media URLs: `<img>`, `<video>` and `<audio>` cannot send an
      Authorization header, so the server mints `/api/uploads/...?mt=...`
      URLs scoped to one file and one user with a one-hour expiry, from
      `POST /api/files/media-urls`, only after the entitlement check passes
- [x] The frontend hydrates those URLs in one batched call and re-renders once
- [x] Legacy attachments get their chat binding rebuilt at startup

### Messaging

- [x] Group member blocking (per-chat, viewer-private). `chats/chat_blocks.py`
      stores `chat_blocks:{chat_id}:{blocker}` and reuses `is_chat_member` for
      authorisation, so a block can only be written by a member about another
      member. Deliberately distinct from `/api/users/block`, which is
      account-wide and symmetric; direct chats are refused and pointed at it.
- [x] Three routes: `GET/POST /api/chats/{chat_id}/blocked` and
      `DELETE /api/chats/{chat_id}/blocked/{user_id}` (unblock is idempotent).
- [x] `get_messages` drops blocked senders from the caller's view only. The
      message stays in storage for everyone else, so unblocking restores the
      history instead of losing it.
- [x] The group members modal renders a Block/Unblock action per member (never
      on yourself) with the live state, and reloads the thread after a toggle.
- [x] `testing/test_chat_member_blocking.py` - 14 checks: directionality (the
      blocked member cannot see the block), per-chat scoping (a block in one
      group does not leak into another), authorisation (non-member, outsider and
      self-block all refused), idempotent unblock, and separate lists per viewer.
- [x] Avatars in the chat list were already correct: `get_chats` returns
      `avatar_url` for direct chats (the other user's) and for groups, and the
      sidebar renders an `<img>` with an initial fallback. Verified, no change needed.

### Known gaps

- [x] LibreOffice, Pandoc and Poppler installed and detected. All eight engines
      report available (the archive engine was added in Phase 6); `docx->pdf`
      resolves to libreoffice. Verified 2026-11-16 via
      `python testing/smoke_registry.py`: `libreoffice=True, pandoc=True,
      poppler=True, ffmpeg=True, raster=True, img2pdf=True, archive=True,
      pdf2docx=True`, 373 routes registered. No route is inert.
      (An earlier run on 2026-11-15 saw `libreoffice=False, pandoc=False,
      poppler=False` because winget had installed the tools without adding them
      to PATH; `settings.which()` now also searches the Windows install dirs.)
- [x] Jobs no longer run as loose tasks in the API process. Phase 4 added a worker pool draining a real queue.
- [ ] `percent` is coarse: only `done` reports 100.
      Engine-level progress callbacks (`parse_progress()` per engine) are the fix.
- [ ] The browser flow was verified statically and over HTTP, not by logging in,
      because this sandbox has no Firebase credentials.
