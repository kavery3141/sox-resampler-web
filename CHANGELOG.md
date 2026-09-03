# Changelog

## 1.0.0 — 2026-09-03

First stable release.

### Highlights

- TrueNAS SCALE-local browser application for manually selected FLAC resampling.
- Custom pinned SoX Ultra 37 backend targeting 48 kHz with preserved source bit depth by default.
- Manual destructive workflow with explicit review, acknowledgment, source identity revalidation, verified temp output, crash-recovery journal, and atomic same-filesystem replacement.
- Up to three concurrent conversions with optional per-worker CPU limiting.
- SQLite library index, scheduled discovery-only scans, metadata issue reporting, source-rate filtering, artwork cache, history, reports, and maintenance tools.
- Release-aware album identity using `MUSICBRAINZ_ALBUMID` when available, including correct multidisc handling and separation of same-named releases with different MBIDs.
- ReplayGain 2.0 recalculation using bundled rsgain 3.7 with album analysis, true peak, -18 LUFS target, clipping protection, and standard ReplayGain tags.
- ReplayGain values are recalculated from the complete logical release and written only to tracks converted by the manually started job.
- FLAC metadata and artwork preservation with supported APPLICATION metadata blocks copied and verified byte-for-byte.
- Retry Failed Files and Retry Clipping with Headroom flows, both requiring a fresh review and explicit start.
- ZFS/readiness checks, free-space reserve, read-only scan mode, ownership/mode/xattr preservation checks, and conservative recovery behavior.
- Browser-persistent theme, density, library filters, Basic/Advanced DSP mode, artwork preferences, and configurable button tooltips enabled by default.
- Stable TrueNAS Custom App YAML on port 30058 using the pinned `ghcr.io/kavery3141/sox-resampler-web:1.0.0` image.

### Release policy

Stable deployments should use immutable release tags. The mutable `:dev` image remains available for ongoing development and testing. The app can check GitHub for newer published releases but never installs updates automatically.
