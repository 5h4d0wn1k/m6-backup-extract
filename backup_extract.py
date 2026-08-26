"""
MO6 — Android Backup Extractor
AB file parsing, zlib decompression, tar extraction, shared_prefs reading.
"""

import struct
import zlib
import tarfile
import xml.etree.ElementTree as ET
import os
import sys
import json
import io
import time
import hashlib
import shutil
from typing import Dict, List, Optional, Tuple, Any
from pathlib import Path


class ABHeader:
    """Parse Android Backup (.ab) file headers."""

    MAGIC = b"Android Backup"
    HEADER_TERMINATOR = b"\n"

    def __init__(self):
        self.magic: bytes = b""
        self.version: int = 0
        self.compressed: bool = False
        self.backup_schema_version: int = 0
        self.device_checksum: str = ""
        self._raw_header: bytes = b""

    @classmethod
    def from_file(cls, filepath: str) -> "ABHeader":
        header = cls()
        with open(filepath, "rb") as f:
            magic = f.read(14)
            if magic != cls.MAGIC:
                raise ValueError(f"Not an Android Backup file: got magic {magic!r}")

            header.magic = magic
            version_line = f.readline().strip()
            header.version = int(version_line)
            header.compressed_line = f.readline().strip()
            header.compressed = header.compressed_line == "1"
            schema_line = f.readline().strip()
            header.backup_schema_version = int(schema_line)

            checksum_line = f.readline().strip()
            header.device_checksum = checksum_line

            header._raw_header = f.read(0)

        return header

    @classmethod
    def from_stream(cls, stream: io.BytesIO) -> "ABHeader":
        header = cls()
        magic = stream.read(14)
        if magic != cls.MAGIC:
            raise ValueError(f"Not an Android Backup file: got magic {magic!r}")
        header.magic = magic

        def read_line() -> bytes:
            line = b""
            while True:
                byte = stream.read(1)
                if byte == b"\n" or byte == b"":
                    break
                line += byte
            return line

        header.version = int(read_line().strip())
        header.compressed = read_line().strip() == b"1"
        header.backup_schema_version = int(read_line().strip())
        header.device_checksum = read_line().strip().decode("utf-8", errors="replace")

        return header

    def __repr__(self) -> str:
        return (
            f"ABHeader(version={self.version}, compressed={self.compressed}, "
            f"schema={self.backup_schema_version}, checksum={self.device_checksum!r})"
        )


class BackupExtractor:
    """Extract data from Android Backup (.ab) files."""

    def __init__(self):
        self.header: Optional[ABHeader] = None

    def read_header(self, filepath: str) -> ABHeader:
        self.header = ABHeader.from_file(filepath)
        return self.header

    def _read_payload(self, filepath: str) -> bytes:
        with open(filepath, "rb") as f:
            while True:
                line = f.readline()
                if line == b"\n" or line == b"":
                    break
            return f.read()

    def decompress(self, filepath: str, output_path: Optional[str] = None) -> bytes:
        payload = self._read_payload(filepath)
        if self.header and self.header.compressed:
            decompressed = zlib.decompress(payload)
        else:
            decompressed = payload

        if output_path:
            with open(output_path, "wb") as f:
                f.write(decompressed)

        return decompressed

    def extract_tar(self, filepath: str, output_dir: str) -> List[str]:
        os.makedirs(output_dir, exist_ok=True)
        data = self.decompress(filepath)
        tar_stream = io.BytesIO(data)
        extracted = []

        with tarfile.open(fileobj=tar_stream) as tar:
            for member in tar.getmembers():
                tar.extract(member, output_dir)
                extracted.append(member.name)

        return extracted

    def extract_selective(self, filepath: str, output_dir: str,
                          patterns: Optional[List[str]] = None) -> List[str]:
        os.makedirs(output_dir, exist_ok=True)
        data = self.decompress(filepath)
        tar_stream = io.BytesIO(data)
        extracted = []

        with tarfile.open(fileobj=tar_stream) as tar:
            for member in tar.getmembers():
                if patterns:
                    if any(p in member.name for p in patterns):
                        tar.extract(member, output_dir)
                        extracted.append(member.name)
                else:
                    tar.extract(member, output_dir)
                    extracted.append(member.name)

        return extracted

    def list_contents(self, filepath: str) -> List[Dict[str, Any]]:
        data = self.decompress(filepath)
        tar_stream = io.BytesIO(data)
        contents = []

        with tarfile.open(fileobj=tar_stream) as tar:
            for member in tar.getmembers():
                info = {
                    "name": member.name,
                    "size": member.size,
                    "mode": oct(member.mode),
                    "mtime": time.strftime(
                        "%Y-%m-%d %H:%M:%S", time.localtime(member.mtime)
                    ),
                    "type": "dir" if member.isdir() else "file",
                    "is_link": member.issym(),
                }
                if member.issym():
                    info["linkname"] = member.linkname
                contents.append(info)

        return contents

    def get_info(self, filepath: str) -> Dict:
        info = {
            "path": filepath,
            "exists": os.path.exists(filepath),
        }
        if not info["exists"]:
            return info

        info["file_size"] = os.path.getsize(filepath)
        try:
            self.header = ABHeader.from_file(filepath)
            info["header"] = {
                "version": self.header.version,
                "compressed": self.header.compressed,
                "schema_version": self.header.backup_schema_version,
                "device_checksum": self.header.device_checksum,
            }
        except ValueError as e:
            info["header_error"] = str(e)

        return info


class SharedPrefsParser:
    """Parse Android shared_preferences XML files."""

    SUPPORTED_TYPES = ("boolean", "string", "int", "long", "float", "set")

    def __init__(self):
        self.prefs: Dict[str, Any] = {}

    def parse_file(self, filepath: str) -> Dict[str, Any]:
        tree = ET.parse(filepath)
        root = tree.getroot()
        prefs: Dict[str, Any] = {}

        for tag in self.SUPPORTED_TYPES:
            for element in root.findall(tag):
                name = element.get("name")
                if name is None:
                    continue

                if tag == "boolean":
                    prefs[name] = element.get("value") == "true"
                elif tag == "string":
                    prefs[name] = element.text or ""
                elif tag == "int":
                    prefs[name] = int(element.get("value", "0"))
                elif tag == "long":
                    prefs[name] = int(element.get("value", "0"))
                elif tag == "float":
                    prefs[name] = float(element.get("value", "0.0"))
                elif tag == "set":
                    values = []
                    for child in element:
                        if child.text:
                            values.append(child.text)
                    prefs[name] = values

        self.prefs = prefs
        return prefs

    def parse_from_string(self, xml_string: str) -> Dict[str, Any]:
        root = ET.fromstring(xml_string)
        prefs: Dict[str, Any] = {}

        for tag in self.SUPPORTED_TYPES:
            for element in root.findall(tag):
                name = element.get("name")
                if name is None:
                    continue

                if tag == "boolean":
                    prefs[name] = element.get("value") == "true"
                elif tag == "string":
                    prefs[name] = element.text or ""
                elif tag == "int":
                    prefs[name] = int(element.get("value", "0"))
                elif tag == "long":
                    prefs[name] = int(element.get("value", "0"))
                elif tag == "float":
                    prefs[name] = float(element.get("value", "0.0"))
                elif tag == "set":
                    values = [child.text for child in element if child.text]
                    prefs[name] = values

        self.prefs = prefs
        return prefs

    def parse_all_prefs(self, directory: str) -> Dict[str, Dict[str, Any]]:
        all_prefs = {}
        for root_dir, dirs, files in os.walk(directory):
            for filename in files:
                if filename.endswith(".xml") and "shared_prefs" in root_dir:
                    filepath = os.path.join(root_dir, filename)
                    try:
                        prefs = self.parse_file(filepath)
                        all_prefs[filename] = prefs
                    except ET.ParseError:
                        all_prefs[filename] = {"_error": "Failed to parse XML"}
        return all_prefs

    def search_keys(self, keyword: str) -> Dict[str, Any]:
        results = {}
        for key, value in self.prefs.items():
            if keyword.lower() in key.lower():
                results[key] = value
            elif isinstance(value, str) and keyword.lower() in value.lower():
                results[key] = value
        return results

    def get_sensitive_keys(self) -> Dict[str, Any]:
        sensitive_patterns = [
            "token", "session", "password", "secret", "key", "auth",
            "api_key", "apikey", "access_token", "refresh_token",
            "credential", "login", "user_id", "email",
        ]
        results = {}
        for key, value in self.prefs.items():
            for pattern in sensitive_patterns:
                if pattern in key.lower():
                    results[key] = value
                    break
        return results

    def save_json(self, output_path: str) -> bool:
        try:
            with open(output_path, "w") as f:
                json.dump(self.prefs, f, indent=2)
            return True
        except IOError:
            return False


class TarAnalyzer:
    """Analyze tar archives for security-relevant content."""

    INTERESTING_PATTERNS = [
        "shared_prefs",
        "databases",
        "files",
        "cache",
        "lib",
        "app_,
        "webview",
    ]

    SENSITIVE_EXTENSIONS = [
        ".db", ".sqlite", ".sqlite3",
        ".key", ".pem", ".crt", ".p12",
        ".json", ".xml", ".properties",
        ".conf", ".config",
    ]

    def analyze(self, filepath: str) -> Dict:
        result = {"path": filepath, "files": [], "stats": {}}

        try:
            with tarfile.open(filepath) as tar:
                all_files = []
                dirs = 0
                total_size = 0

                for member in tar.getmembers():
                    entry = {
                        "name": member.name,
                        "size": member.size,
                        "type": "dir" if member.isdir() else "file",
                        "is_symlink": member.issym(),
                    }
                    if member.issym():
                        entry["linkname"] = member.linkname

                    all_files.append(entry)
                    if member.isdir():
                        dirs += 1
                    else:
                        total_size += member.size

                result["files"] = all_files
                result["stats"] = {
                    "total_entries": len(all_files),
                    "directories": dirs,
                    "files": len(all_files) - dirs,
                    "total_size": total_size,
                }

                result["interesting"] = [
                    f for f in all_files
                    if any(p in f["name"] for p in self.INTERESTING_PATTERNS)
                ]

                result["sensitive"] = [
                    f for f in all_files
                    if any(f["name"].endswith(ext) for ext in self.SENSITIVE_EXTENSIONS)
                ]

        except tarfile.TarError as e:
            result["error"] = str(e)

        return result


class BackupWorkflow:
    """High-level backup analysis workflow."""

    def __init__(self, output_dir: str = "backup_output"):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
        self.extractor = BackupExtractor()
        self.prefs_parser = SharedPrefsParser()
        self.tar_analyzer = TarAnalyzer()

    def analyze_backup(self, ab_path: str) -> Dict:
        result = {
            "backup_path": ab_path,
            "info": self.extractor.get_info(ab_path),
        }

        if not result["info"]["exists"]:
            result["error"] = "File does not exist"
            return result

        try:
            result["header"] = str(self.extractor.read_header(ab_path))
        except ValueError as e:
            result["header_error"] = str(e)
            return result

        try:
            contents = self.extractor.list_contents(ab_path)
            result["contents_count"] = len(contents)
            result["directories"] = [c["name"] for c in contents if c["type"] == "dir"]
            result["interesting_files"] = [
                c["name"] for c in contents
                if any(p in c["name"] for p in ["shared_prefs", "databases", "files"])
            ]
        except Exception as e:
            result["contents_error"] = str(e)

        return result

    def extract_backup(self, ab_path: str) -> Dict:
        extract_dir = os.path.join(self.output_dir, "extracted")
        extracted_files = self.extractor.extract_tar(ab_path, extract_dir)

        prefs_dir = os.path.join(self.output_dir, "prefs")
        os.makedirs(prefs_dir, exist_ok=True)
        prefs_data = self.prefs_parser.parse_all_prefs(extract_dir)

        sensitive = self.prefs_parser.get_sensitive_keys()

        return {
            "extracted_files": extracted_files,
            "prefs_files": list(prefs_data.keys()),
            "prefs_data": prefs_data,
            "sensitive_keys": sensitive,
            "extract_dir": extract_dir,
        }

    def full_report(self, ab_path: str) -> Dict:
        analysis = self.analyze_backup(ab_path)
        extraction = self.extract_backup(ab_path)

        report = {
            "analysis": analysis,
            "extraction": {
                "extracted_count": len(extraction["extracted_files"]),
                "prefs_files": extraction["prefs_files"],
                "sensitive_keys": extraction["sensitive_keys"],
                "extract_dir": extraction["extract_dir"],
            },
        }

        report_path = os.path.join(self.output_dir, "report.json")
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2, default=str)

        report["report_path"] = report_path
        return report


def create_sample_prefs_xml() -> str:
    return '''<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
    <boolean name="dark_mode" value="true" />
    <string name="username">testuser</string>
    <string name="session_token">abc123def456</string>
    <int name="login_count" value="42" />
    <long name="last_sync" value="1693000000000" />
    <float name="volume" value="0.75" />
    <set name="seen_categories">
        <string>tech</string>
        <string>news</string>
        <string>sports</string>
    </set>
    <string name="api_key">sk-test-key-12345</string>
    <boolean name="notifications_enabled" value="false" />
</map>'''


def create_sample_ab_file(filepath: str) -> str:
    prefs_xml = create_sample_prefs_xml()
    prefs_bytes = prefs_xml.encode("utf-8")

    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w") as tar:
        info = tarfile.TarInfo(name="shared_prefs/")
        info.type = tarfile.DIRTYPE
        tar.addfile(info)

        info = tarfile.TarInfo(name="shared_prefs/user_prefs.xml")
        info.size = len(prefs_bytes)
        tar.addfile(info, io.BytesIO(prefs_bytes))

        files_data = b"sample app data"
        info = tarfile.TarInfo(name="files/config.dat")
        info.size = len(files_data)
        tar.addfile(info, io.BytesIO(files_data))

        db_data = b"sample database content"
        info = tarfile.TarInfo(name="databases/app.db")
        info.size = len(db_data)
        tar.addfile(info, io.BytesIO(db_data))

    tar_content = tar_buffer.getvalue()
    compressed = zlib.compress(tar_content)

    with open(filepath, "wb") as f:
        f.write(b"Android Backup\n")
        f.write(b"1\n")
        f.write(b"1\n")
        f.write(b"1\n")
        f.write(b"none\n")
        f.write(b"\n")
        f.write(compressed)

    return filepath


def main():
    if len(sys.argv) < 2:
        print("Usage: backup_extract.py <command> [args]")
        print("Commands:")
        print("  info <ab_file>          - Show backup file info")
        print("  header <ab_file>        - Parse and display header")
        print("  contents <ab_file>      - List backup contents")
        print("  extract <ab_file>       - Extract backup to output dir")
        print("  prefs <ab_file>         - Extract and parse shared_prefs")
        print("  report <ab_file>        - Generate full analysis report")
        print("  parse-prefs <xml_file>  - Parse a shared_prefs XML file")
        print("  create-sample <ab_file> - Create a sample .ab file for testing")
        return

    cmd = sys.argv[1]
    workflow = BackupWorkflow()

    if cmd == "info":
        if len(sys.argv) < 3:
            print("Usage: backup_extract.py info <ab_file>")
            return
        info = workflow.extractor.get_info(sys.argv[2])
        print(json.dumps(info, indent=2))

    elif cmd == "header":
        if len(sys.argv) < 3:
            print("Usage: backup_extract.py header <ab_file>")
            return
        try:
            header = workflow.extractor.read_header(sys.argv[2])
            print(header)
        except ValueError as e:
            print(f"Error: {e}")

    elif cmd == "contents":
        if len(sys.argv) < 3:
            print("Usage: backup_extract.py contents <ab_file>")
            return
        try:
            contents = workflow.extractor.list_contents(sys.argv[2])
            for item in contents:
                prefix = "d" if item["type"] == "dir" else "f"
                print(f"  {prefix} {item['name']} ({item['size']} bytes)")
        except Exception as e:
            print(f"Error: {e}")

    elif cmd == "extract":
        if len(sys.argv) < 3:
            print("Usage: backup_extract.py extract <ab_file>")
            return
        try:
            extracted = workflow.extractor.extract_tar(sys.argv[2], workflow.output_dir)
            print(f"Extracted {len(extracted)} files to {workflow.output_dir}")
        except Exception as e:
            print(f"Error: {e}")

    elif cmd == "prefs":
        if len(sys.argv) < 3:
            print("Usage: backup_extract.py prefs <ab_file>")
            return
        try:
            extraction = workflow.extract_backup(sys.argv[2])
            print(f"Parsed {len(extraction['prefs_files'])} preference files")
            print(f"Sensitive keys found: {extraction['sensitive_keys']}")
            print(json.dumps(extraction["prefs_data"], indent=2))
        except Exception as e:
            print(f"Error: {e}")

    elif cmd == "report":
        if len(sys.argv) < 3:
            print("Usage: backup_extract.py report <ab_file>")
            return
        try:
            report = workflow.full_report(sys.argv[2])
            print(f"Report saved to: {report['report_path']}")
        except Exception as e:
            print(f"Error: {e}")

    elif cmd == "parse-prefs":
        if len(sys.argv) < 3:
            print("Usage: backup_extract.py parse-prefs <xml_file>")
            return
        parser = SharedPrefsParser()
        prefs = parser.parse_file(sys.argv[2])
        print(json.dumps(prefs, indent=2))

    elif cmd == "create-sample":
        if len(sys.argv) < 3:
            print("Usage: backup_extract.py create-sample <output_file>")
            return
        path = create_sample_ab_file(sys.argv[2])
        print(f"Created sample AB file: {path}")

    else:
        print(f"Unknown command: {cmd}")


if __name__ == "__main__":
    main()
