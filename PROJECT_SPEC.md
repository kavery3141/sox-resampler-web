# SoX Resampler Web — Product Specification

## Purpose
Run high-quality FLAC sample-rate conversion locally on TrueNAS SCALE, avoiding SMB transfer overhead. The app is intentionally manual: scanning/indexing may run automatically, but conversion never starts without explicit album selection and confirmation.

## Storage and deployment
- Music dataset: `/mnt/MainStorage/StorageDataset/Music`
- App dataset: `/mnt/MainStorage/StorageDataset/sox-resampler`
- Web port: `30058`
- Timezone: `America/Indiana/Indianapolis`
- LAN + Tailscale access
- No app-level authentication
- Container restart policy: `unless-stopped`
- Run as TrueNAS `apps` UID/GID 568 where practical
- Pinned container versions; show update availability but never auto-update

## Primary workflow
1. Daily incremental scan at 10:00 AM NAS-local time plus manual incremental/full rescan controls.
2. Local SQLite index stores FLAC path, album grouping, rate, bit depth, channels, duration, size, mtimes, metadata health, artwork thumbnail cache refs, and first-seen timestamps.
3. Library search defaults to 96 kHz + 192 kHz, with optional `> 48 kHz` discovery and exact oddball rates shown.
4. Albums are grouped strictly by `ALBUMARTIST + ALBUM`; multi-disc albums remain grouped together.
5. User selects one or many albums with checkboxes; Check All/Uncheck All apply only to the current matched set.
6. Only tracks whose source sample rate matches the active search filter are converted; nonmatching tracks in the same album remain untouched.
7. Review Batch page shows before/after technical summaries, warnings, free-space checks, estimated savings, concurrency 1/2, command preview, and destructive-action acknowledgment.
8. Conversion only begins after explicit confirmation.

## Default resampling profile
Built-in reference preset name: `Foobar Ultra 37 - 48 kHz`
- Target: 48,000 Hz
- Bit depth: preserve
- Passband: 95%
- Phase: 50% / linear
- Aliasing/imaging: disabled
- Quality target: closest technically accurate match to foobar2000 SoX Resampler 0.8.9 `Ultra 37 (222 dB)`; do not mislabel ordinary stock SoX `rate -v` as equivalent.
- FLAC compression: level 4

Advanced mode exposes editable DSP settings, dithering, headroom, quality/profile, passband, phase, aliasing, and compression. Presets store audio settings only; operational behavior is separate.

## Bit depth and dithering
- Preserve bit depth by default.
- When reducing bit depth, warn prominently.
- Automatically enable TPDF dither by default when bit depth is reduced.
- Dither mode and disable option live in Advanced settings.

## Metadata rules
Album-level fields shown prominently:
- `ALBUMARTIST`
- `ALBUM`
- `RELEASETYPE`
- `MUSICBRAINZ_ALBUMID`

Hard blockers:
- Missing/inconsistent `ALBUMARTIST`
- Missing/inconsistent `ALBUM`
- Missing/inconsistent `RELEASETYPE`
- Missing/inconsistent `MUSICBRAINZ_ALBUMID`

Do not fall back from missing `ALBUMARTIST` to track `ARTIST`.

Compilation/soundtrack status comes only from curated `RELEASETYPE`; do not infer it from artist strings. Per-track `ARTIST` variation is normal and must not trigger an album inconsistency warning.

ReplayGain is warning-only. Check:
- `REPLAYGAIN_TRACK_GAIN`
- `REPLAYGAIN_TRACK_PEAK`
- `REPLAYGAIN_ALBUM_GAIN`
- `REPLAYGAIN_ALBUM_PEAK`

Show exact track-level metadata inconsistencies and allow copying/exporting issue summaries.

## Audio/file safety
For each file:
1. Revalidate source identity/size/mtime/key metadata before work.
2. Create hidden same-directory temp file: `.<original>.sox-resampler.tmp.flac`-style naming.
3. Preserve/copy all applicable FLAC metadata and embedded artwork.
4. Preserve ReplayGain tags verbatim unless they were absent.
5. Verify target sample rate, bit depth, channel count/layout, duration/sample-count sanity.
6. Fully decode output FLAC end-to-end.
7. Compare required metadata blocks source vs output; metadata mismatch is a hard failure.
8. Check output peak/clipping. True clipping is a failure; results may offer `Retry with headroom`.
9. SHA-256 verified temp output and final replacement by default. Source hashing is optional Advanced behavior to avoid extra read I/O.
10. Immediately before replacement, verify the source has not changed during conversion.
11. Preserve owner/group, permissions/ACL behavior where practical, mtime, extended attributes, and birth time where technically possible. Failure to preserve birth time alone is nonfatal.
12. Atomically replace original only after verification passes.
13. Keep exact original filename. No persistent backup.

On failure: original remains untouched; log error; continue batch.

Busy files are deferred, retried once at batch end, and left untouched if still busy.

Startup and daily maintenance clean orphaned temp files safely. Interrupted temp files are never auto-promoted.

## Channel policy
- Mono: allowed, preserve mono.
- Stereo: normal.
- Multichannel: show/flag, nonselectable by default, investigate before any explicit Advanced override.

## Non-FLAC files
Ignore non-FLAC files for scan/report/conversion presentation. `.nfo`, `.lrc`, images, cue sheets, PDFs, text, etc. remain untouched and should not clutter reports.

## Resource behavior
- Default workers: 1
- Optional workers: 2 per batch
- Selecting 2 shows a nonblocking NAS-load warning
- User may change 1↔2 while running; takes effect only between files and is logged
- Low CPU priority and low I/O priority for scans and conversion
- No hard CPU cap by default; configurable optional limit
- Best-effort NAS/media-activity advisory only; never auto-change concurrency
- One heavy storage task at a time: conversion vs scan/rebuild are mutually exclusive
- Daily scan defers while conversion is running

## Batch controls
- Pause after current file / Resume
- Stop after current album
- Cancel after current file
- Emergency Force Stop Current File, preserving original and deleting temp output
- Paused/interrupted jobs survive app/NAS restart but never auto-resume
- Queue order survives restart/browser refresh
- Batch supports manual reorder via drag and accessible move controls
- Retry Failed Files
- Retry clipping failures with suggested headroom

## Storage safety
- Show current free space, estimated temp requirement, estimated final savings
- Configurable free-space reserve, default 10 GB
- Re-check free space before each new file; pause if unsafe
- Refuse new conversion work if ZFS pool is unhealthy or music dataset becomes read-only
- Pool-health safeguard is not overridable

## Scanner/index
- SQLite-based local index in app dataset
- Incremental daily scan at 10:00 AM, manual incremental rescan, full rescan, rebuild index
- Full/long scans can pause/resume and survive restart as interrupted/paused
- Do not follow symlinks
- Skip hidden/system folders by default
- Configurable exact-path and glob exclusions; test/preview before saving; excluded content is fully out of scope
- Daily scan is discovery/indexing only and can never convert anything
- Scan progress view for full scans/rebuilds
- Maintenance view shows indexed tracks/albums, scan times, issues, DB size, versions

## UI
Navigation:
- Home
- Library
- Convert
- History
- Settings
- Maintenance

Home:
- High-Rate Candidates shortcut
- candidate/blocked/warning/interrupted-job status summary
- interrupted job card when relevant

Library:
- Continuous/virtualized scrolling; no pagination unless proven necessary for performance
- Instant Album Artist/Album text filtering with ~250 ms debounce
- Source-rate filters and `>48 kHz`
- Exact detected oddball rates
- Clean/Warnings/Blocked filtering
- `Show only albums with warnings`
- Recently Added convenience filter (simple; avoid overengineering combinations)
- Sort by Album Artist, Album, source rate, source size, estimated savings, first-seen date
- Cover thumbnails in Comfortable mode; Compact mode hides by default
- Artwork priority: embedded FLAC picture, then folder-local `folder/cover/front` JPG/PNG variants, then placeholder
- Thumbnail-only artwork cache; do not duplicate full-resolution art
- Expandable album rows; detail expansion state lasts current browser session
- Proper icon assets/components only; never Unicode/text glyph pseudo-icons
- Keyboard navigation/shortcuts; no shortcut may start conversion
- Expand/Collapse All Visible
- Persistent Selected Albums tray with album/track counts, source size, estimated savings, warning count, Review Batch, Clear Selection
- Selection survives sorting/filtering/scrolling; current-filter Check/Uncheck semantics do not wipe selections outside the filter

Convert:
- Dedicated Review Batch page
- Remove/reorder albums without returning to Library
- Per-album before/after summaries
- Album-level estimates by default; optional per-track estimates in expanded details
- Downsample ratio shown as secondary technical detail
- Nonblocking warnings for 44.1-family→48-family conversion and for upsampling
- Clear warnings/dither recommendation for bit-depth reduction
- DSP command preview, read-only
- Advanced settings editable
- Final destructive replacement acknowledgment resets each batch
- Remember last-used audio preset; concurrency always resets to 1

History/reports:
- Pre-conversion and post-conversion TXT + CSV export
- Metadata Issues TXT + CSV export using current filtered set
- Persistent history 180 days
- Failures/errors retained until manually cleared
- Log rotation: 10 MB active max, 5 rotations
- Track active processing time separately from paused time; ETA excludes paused time
- Show relative and exact timestamps
- All timestamps use `America/Indiana/Indianapolis`; exports explicitly include timezone
- No user attribution
- No email/push/external notifications

Live conversion status:
- current file, album, batch progress
- conversion speed
- read/write throughput
- CPU/memory
- active workers/queue depth
- elapsed/active/paused time
- ETA and estimated finish clock time; finish time unavailable while paused
- Safe to Restart indicator

Settings:
- System/Light/Dark theme; System default; remembered per browser
- Comfortable/Compact density; remembered per browser
- Cover-thumbnail preference per browser
- Read-only Scan Mode with prominent persistent banner; survives restart; disabling requires confirmation
- Reset to Defaults affects app/UI/default audio preferences only, not index/history/exclusions/custom presets
- Built-in `Factory Defaults` preset is read-only/nondeletable
- Built-in `Foobar Ultra 37 - 48 kHz` is read-only/nondeletable and duplicable
- Custom presets editable/deletable/exportable/importable as validated JSON with preview and optional notes

Maintenance:
- Incremental Rescan / Full Rescan / Rebuild Index / Vacuum Database
- Version info: app, SoX, libsoxr (if used), FLAC, backend, DB schema
- Update available indicator only; no automatic install
- Lightweight maintenance event log
- `/health` endpoint used by container health check

## Branding
Approved icon: dark navy rounded square with interlocked fast-moving opposing arrows, orange and white. Repository asset path: `assets/icon.png`.
