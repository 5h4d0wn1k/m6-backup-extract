> **⚠️ EDUCATIONAL USE ONLY — AUTHORIZED TESTING ONLY.**
> This project exists for education, research, and **defense of systems you own
> or hold explicit written authorization to assess**. Unauthorized use is
> prohibited and may be illegal. Read [ETHICS.md](ETHICS.md) and
> [SCOPE.md](SCOPE.md) before use. Use at your own risk; **AS IS**, no warranty.

# M6 — Android Backup Extractor & Sensitive-Data Analyzer

Android Backup (`.ab`) parser and analyzer: header parsing, zlib decompression, tar extraction, shared-preferences XML analysis, and security-focused scanning for credentials and sensitive keys — stdlib only.

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/5h4d0wn1k/m6-backup-extract.svg)](https://github.com/5h4d0wn1k/m6-backup-extract)
[![Last commit](https://img.shields.io/github/last-commit/5h4d0wn1k/m6-backup-extract.svg)](https://github.com/5h4d0wn1k/m6-backup-extract)
[![Issues](https://img.shields.io/github/issues/5h4d0wn1k/m6-backup-extract.svg)](https://github.com/5h4d0wn1k/m6-backup-extract)

## Why

Mobile backups are dense with secrets — stored credentials, API keys, session tokens — and auditing them is a bread-and-butter mobile forensics skill. M6 parses Android Backup `.ab` files end-to-end (header, zlib payloads, tar archives, `shared_prefs` XML), then scans extracted preferences for sensitive keys and interesting files for sensitive extensions. It also writes its own sample `.ab` files, so the whole pipeline is testable offline on backups you create from your own devices.

## Features

- **`.ab` file parsing** — magic/header validation, version + compression detection, zlib and uncompressed payloads
- **Tar extraction** — full and selective extraction from backup archives
- **Shared preferences analysis** — XML parsing, key search, sensitive-value identification
- **Sensitive-key scanning** — token/password/secret/key/auth/credential/login/user patterns
- **Tar analysis** — file statistics, interesting patterns, sensitive extension detection
- **Sample `.ab` generator** — `create-sample` builds a real backup for testing

## Quickstart

```bash
# Offline demo (creates a real .ab, parses, extracts, reports; exit 0)
python3 backup_extract.py -o reports demo

# Create a sample backup for testing
python3 backup_extract.py create-sample test.ab

# Inspect and analyze any .ab file you own
python3 backup_extract.py info test.ab
python3 backup_extract.py contents test.ab
python3 backup_extract.py extract test.ab
python3 backup_extract.py prefs test.ab
python3 backup_extract.py -o reports report test.ab

# Unit tests (17)
python3 -m unittest discover -s tests
```

## Project structure

- `backup_extract.py` — `ABHeader`, `BackupExtractor`, `SharedPrefsParser`, `TarAnalyzer`, `BackupWorkflow` and CLI
- `tests/` — 17 stdlib unittest cases over the full pipeline

## Documentation

- [ETHICS.md](ETHICS.md) — educational purpose and authorized use only
- [SCOPE.md](SCOPE.md) — authorized-testing scope checklist
- [SECURITY.md](SECURITY.md) — vulnerability reporting
- [CONTRIBUTING.md](CONTRIBUTING.md) — safe contribution guidelines

## Contributing

New sensitive-key patterns, extraction modes and fixture coverage are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md); analyze only backups you own or hold authorization for.

## License

MIT — see [LICENSE](LICENSE). Provided **AS IS**, without warranty, for education and authorized mobile forensics use only.