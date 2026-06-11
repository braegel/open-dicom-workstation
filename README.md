# Open DICOM Workstation

A free, open-source DICOM workstation — by radiologists, for radiologists.

Open DICOM Workstation (ODW) retrieves studies from a PACS (C-FIND / C-MOVE / C-GET),
stores them locally and lets you view them with the tools radiologists actually use:
slice scrolling, window/level, zoom and pan. It is built for minimal latency and easy
extensibility, and runs on macOS, Linux and Windows.

> **Status:** early MVP under active development.

## Quickstart

Requires [uv](https://docs.astral.sh/uv/) and Python 3.11–3.14.

```sh
uv sync
uv run odw
```

## Connecting to a PACS

Configure your PACS node (AE title, host, port) in *Settings*.

- **C-GET** works out of the box — data flows back over the same association.
- **C-MOVE** requires that your workstation's AE title, host and listen port
  (default `ODW`, port 11112) are registered as a known destination on the PACS.

## Development

This project is strictly test-driven: every change starts with a failing test.

```sh
uv run pytest                 # unit + UI tests (headless)
uv run ruff check .           # lint
uv run mypy                   # type check
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

## License

[GPL-3.0-or-later](LICENSE). Commercial use is permitted under the terms of the GPL;
derivative works must remain open source under the same license, with attribution.
