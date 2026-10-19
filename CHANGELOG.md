# Changelog

## [Unreleased]

## [2.0.0] - 2026-10-19

### Changed

- Migrate Molibrary Browser to PySide6 and MoleditPy 5, keeping plugin support
  for Python 3.9–3.14. The web server remains Python 3.10+.
- Adopt LGPL-3.0-or-later for the first-party plugin and distribute both GNU
  license texts and its scope notice with the single-file release. The web
  application's GPLv3 license and historical releases are unchanged.
- Keep the web app and plugin version at 2.0.0 under the existing shared release rule.

### Fixed

- Deliver worker results through GUI-thread slots, cancel the startup timer on
  dialog close, and finish active HTTP workers before destroying their Qt parent.
- Preserve the wait cursor's stack when search completion follows dialog close.
