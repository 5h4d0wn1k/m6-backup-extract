# MO6 — Android Backup Extractor

Parse and extract Android Backup (.ab) files with shared preferences analysis.

## Overview

This project implements Android Backup (.ab) file parsing, zlib decompression, tar extraction, and shared_preferences XML analysis. It can create sample backup files for testing and perform security-focused analysis of extracted data.

## Features

- **AB File Parsing**: Read Android Backup headers, detect compression, validate magic bytes
- **Zlib Decompression**: Handle compressed and uncompressed backup payloads
- **Tar Extraction**: Full and selective extraction from backup archives
- **Shared Preferences**: Parse XML files, search keys, identify sensitive values
- **Tar Analysis**: File statistics, interesting pattern matching, sensitive extension detection

## Installation

Standard library only — no dependencies required.

```bash
python3 backup_extract.py --help
```

## Usage

```bash
# Offline demo (creates a real .ab, parses, extracts, reports; exits 0)
python3 backup_extract.py -o reports demo

# Create a sample .ab file for testing
python3 backup_extract.py create-sample test.ab

# Show backup file info
python3 backup_extract.py info test.ab

# Parse and display header
python3 backup_extract.py header test.ab

# List backup contents
python3 backup_extract.py contents test.ab

# Extract backup to output directory
python3 backup_extract.py extract test.ab

# Extract and parse shared preferences
python3 backup_extract.py prefs test.ab

# Generate full analysis report (JSON under reports/)
python3 backup_extract.py -o reports report test.ab

# Parse a standalone shared_prefs XML file
python3 backup_extract.py parse-prefs user_prefs.xml
```

## Tests

```bash
python3 -m unittest discover -s tests -v
```

17 stdlib unittest cases covering header parsing, zlib+tar round-trips,
selective extraction, shared-prefs XML type mapping, sensitive-key scanning,
tar analysis, the full workflow report, and CLI exit codes.

## Live Lab Test Plan

1. In an offline lab, run `python3 backup_extract.py -o reports demo` against a
   **backup you made yourself** of your own device with `adb backup` (or use
   the built-in sample). Confirm it prints the header, contents, and sensitive
   keys, then exits 0.
2. `create-sample` then `contents`/`report` to verify the full pipeline.
3. Only ever extract or parse `.ab` files you created or that you have explicit
   written authorization to analyze. Never scan backups belonging to others.

## Metrics

- Format support: Android Backup `.ab` (v1, compressed and uncompressed),
  zlib payloads, tar archives, shared_preferences XML.
- Engine: `ABHeader`, `BackupExtractor`, `SharedPrefsParser`, `TarAnalyzer`,
  `BackupWorkflow`.
- Sensitive-key scan: token/password/secret/key/auth/credential/login/user
  patterns across parsed prefs.
- Report: JSON to `reports/` (gitignored), full workflow report with contents
  + extraction + sensitive keys.
- Test count: 17 stdlib unittest cases (see `tests/`).
- Dependencies: Python 3 stdlib only (`tarfile`, `zlib`, `xml.etree`,
  `struct`, `json`).
- Offline demo: creates a real compressed `.ab`, round-trips it, exits 0.

## Example Output

```
ABHeader(version=1, compressed=True, schema=1, checksum='none')

Contents:
  d shared_prefs/
  f shared_prefs/user_prefs.xml (482 bytes)
  f files/config.dat (15 bytes)
  f databases/app.db (24 bytes)

Sensitive keys found: {'session_token': 'abc123def456', 'api_key': 'sk-test-key-12345'}
```

## Architecture

- `ABHeader` — Android Backup header parser
- `BackupExtractor` — Core extraction and decompression
- `SharedPrefsParser` — XML preferences parser
- `TarAnalyzer` — Security-focused tar analysis
- `BackupWorkflow` — High-level analysis orchestrator

## Legal Disclaimer

**IMPORTANT: Read before use.**

This project is provided for **educational and authorized security testing purposes only**.

### Authorization Requirements
- You MUST have explicit written permission from the backup owner before using this tool
- Unauthorized extraction of backup data is illegal under federal and state laws
- This tool should ONLY be used on backups you own or have written authorization to analyze

### Legal Framework
- **Computer Fraud and Abuse Act (CFAA)**: Unauthorized access to computer systems is a federal crime
- **Wiretap Act (18 U.S.C. § 2511)**: Interception of electronic communications without consent is illegal
- **State Laws**: Many states have additional computer crime and wiretapping statutes
- **GDPR/CCPA**: Data collection may be subject to privacy regulations

### Acceptable Use
- Analyzing your own device backups
- Authorized forensic analysis with written scope
- Academic research in controlled lab environments
- Security education and training

### Prohibited Use
- Extracting data from backups you do not own
- Accessing sensitive data without authorization
- Any activity that violates applicable laws or regulations
- Commercial use without proper licensing

### No Warranty
This software is provided "AS IS" without warranty of any kind. The author is not responsible for any misuse or damage caused by this software.

### Responsible Disclosure
If you discover vulnerabilities using this tool, follow responsible disclosure practices:
1. Report to the vendor/owner privately
2. Allow reasonable time for remediation
3. Do not exploit beyond proof of concept

## License

MIT
