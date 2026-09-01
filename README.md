# SoX Resampler Web

A TrueNAS SCALE-local FLAC resampling appliance with a Web UI.

The application is designed to resample FLAC files directly on the NAS so audio never has to traverse SMB for conversion. The primary workflow is manual album selection for 96 kHz / 192 kHz sources, downsampling to 48 kHz while preserving bit depth, metadata, embedded artwork, ReplayGain tags, timestamps, ownership, permissions, ACL behavior, and extended attributes where supported.

## Project status

Initial implementation in progress.

## Planned deployment defaults

- Music root: `/mnt/MainStorage/StorageDataset/Music`
- App data: `/mnt/MainStorage/StorageDataset/sox-resampler`
- Web UI port: `30058`
- Time zone: `America/Indiana/Indianapolis`
- Restart policy: `unless-stopped`
- Default source search: 96 kHz + 192 kHz
- Default target: 48 kHz
- Bit depth: preserve
- FLAC compression: level 4
- Default workers: 1, optional 2 per batch

## Safety model

Conversions are written to hidden same-directory temporary FLAC files, verified before replacement, and atomically renamed over the source only after all required checks pass. Interrupted jobs never auto-resume.
