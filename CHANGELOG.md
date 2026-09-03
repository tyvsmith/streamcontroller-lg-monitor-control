# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] - 2026-09-02

### Added

- LG 45GX950A Dual Mode switching between 5K2K 165 Hz and WFHD 330 Hz.
- Monitor-profile fields for model-specific Dual Mode values and labels.
- Automated coverage for Dual Mode actions, per-display state, and incomplete profiles.

### Changed

- Dual Mode state is tracked per display.
- ddcutil 2.1+ is required for unknown VCP writes.

### Fixed

- Incomplete Dual Mode profiles are treated as unsupported.

[0.3.0]: https://github.com/tyvsmith/streamcontroller-lg-monitor-control/releases/tag/v0.3.0
