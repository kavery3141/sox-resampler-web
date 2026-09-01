# SoX Resampler Web

A TrueNAS SCALE-local FLAC resampling appliance with a browser UI. Audio conversion runs directly against the NAS-mounted music dataset, avoiding SMB transfer overhead.

## Project status

Active pre-release development. The core scanner, metadata validation, batch review, persistent conversion jobs, crash-safe replacement journal, Ultra 37 resampling backend, local artwork cache, maintenance controls, history/reports, health checks, and browser UI are implemented and exercised by the container CI build. The project has not been declared a stable 1.0 release yet.

## Default workflow

- Scan/index FLACs locally in SQLite.
- Find high-rate candidates; 96 kHz + 192 kHz are the default filters, with 88.2/176.4 kHz and `>48 kHz` discovery available.
- Group releases by `ALBUMARTIST + ALBUM`, including multi-disc releases spread across multiple directories.
- Block albums with missing or inconsistent `ALBUMARTIST`, `ALBUM`, `RELEASETYPE`, or `MUSICBRAINZ_ALBUMID` metadata.
- Select albums manually, review the exact matching tracks and DSP command, acknowledge in-place replacement, then start conversion.
- Scheduled scanning is discovery-only and never launches conversion.

## Default audio profile

`Foobar Ultra 37 - 48 kHz` targets the closest technically accurate Linux implementation of foobar2000 SoX Resampler 0.8.9 Ultra 37 behavior currently supported by the project:

- 48,000 Hz target
- preserve source bit depth
- 95% passband
- 50% / linear phase
- aliasing disabled
- FLAC compression level 4
- custom pinned SoX rate backend using 37-bit filter accuracy (`rate -d 37`)

This is intentionally **not** described as ordinary stock SoX `rate -v`, and the project does not claim bit-for-bit identity with the foobar component wrapper.

## File-safety model

Each source FLAC is converted to a hidden same-directory temporary file. Before replacement the app verifies technical output properties, user metadata and embedded pictures, performs a full FLAC decode test, checks clipping, preserves filesystem metadata, revalidates source identity, and hashes the verified output. Replacement uses a persistent crash-recovery journal and an atomic same-filesystem exchange. The old source remains available until the new file has passed final verification; failures leave the original untouched.

Interrupted replacement journals and orphan temp files are reconciled conservatively at startup and during maintenance. Ambiguous states require manual attention rather than silently promoting or deleting files.

## TrueNAS development deployment

The supplied `compose.truenas.yaml` currently follows the development image while the application is being built:

- music dataset: `/mnt/MainStorage/StorageDataset/Music` -> `/music`
- app dataset: `/mnt/MainStorage/StorageDataset/sox-resampler` -> `/data`
- Web UI: port `30058`
- timezone: `America/Indiana/Indianapolis`
- runtime UID/GID: `568:568`
- restart policy: `unless-stopped`

Stable deployments will use pinned release tags rather than automatic updates. The Maintenance page can check published GitHub releases and report update availability, but the application never installs an update itself.

## Storage health

New destructive conversion work fails closed if the configured ZFS pool is not confirmed healthy, the music dataset is not writable, free space drops below the configured reserve, Read-only Scan Mode is enabled, or recovery state requires manual attention. On Linux/OpenZFS the app prefers the read-only `/proc/spl/kstat/zfs/<pool>/state` pool heartbeat and retains `zpool status -x` as a fallback.

## Branding

Approved application icon: `assets/icon.png`.

For the complete behavior and safety requirements, see `PROJECT_SPEC.md`.
