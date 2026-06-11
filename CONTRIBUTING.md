# Contributing to Open DICOM Workstation

Thank you for contributing! A few ground rules keep this project healthy.

## Test-driven development is mandatory

Every feature and bug fix starts with a **failing test**, followed by the minimal
implementation that makes it pass. Pull requests without tests are not merged.

1. Write the failing test (`tests/unit/`, `tests/ui/` or `tests/integration/`).
2. Run `uv run pytest` and confirm it fails for the right reason.
3. Implement the minimal change to make it pass.
4. Refactor while green.

## Architecture rule: the core is Qt-free

`odw.core` must never import PySide6 — it is enforced by
`tests/unit/test_core_is_qt_free.py`. UI code lives in `odw.ui` only.
This keeps the core reusable for other front ends and scripts.

## Workflow

```sh
uv sync                       # set up the environment
uv run pytest                 # run the test suite
uv run ruff check . && uv run ruff format .
uv run mypy
```

UI tests run headless via `QT_QPA_PLATFORM=offscreen` (set automatically in
`tests/ui/conftest.py`).

Integration tests against a real Orthanc PACS are optional and skipped unless
`ODW_ORTHANC_HOST` is set. See `tests/integration/`.

## Translations

UI strings use Qt's `self.tr("...")`. Regenerate the translation sources with:

```sh
uv run pyside6-lupdate src/odw/ui/*.py -ts src/odw/ui/i18n/odw_de.ts
```

## License

By contributing you agree that your contributions are licensed under
GPL-3.0-or-later.
