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
import tempfile
import argparse
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
            first_line = f.readline().rstrip(b"\n")
            if first_line != cls.MAGIC:
                raise ValueError(f"Not an Android Backup file: got magic {first_line!r}")

            header.magic = first_line
            version_line = f.readline().strip()
            header.version = int(version_line)
            compressed_line = f.readline().strip()
            header.compressed = compressed_line == b"1"
            schema_line = f.readline().strip()
            header.backup_schema_version = int(schema_line)

            checksum_line = f.readline().strip()
            header.device_checksum = checksum_line.decode("utf-8", errors="replace")

            header._raw_header = f.read(0)

        return header

    @classmethod
    def from_stream(cls, stream: io.BytesIO) -> "ABHeader":
        header = cls()

        def read_line() -> bytes:
            line = b""
            while True:
                byte = stream.read(1)
                if byte == b"\n" or byte == b"":
                    break
                line += byte
            return line

        first_line = read_line()
        if first_line != cls.MAGIC:
            raise ValueError(f"Not an Android Backup file: got magic {first_line!r}")
        header.magic = first_line

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
            first_line = f.readline().rstrip(b"\n")
            if first_line != b"Android Backup":
                raise ValueError("Not an Android Backup file")
            for _ in range(4):
                f.readline()
            f.readline()
            return f.read()

    def decompress(self, filepath: str, output_path: Optional[str] = None) -> bytes:
        if not self.header:
            self.read_header(filepath)
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

        with tarfile.open(fileobj=tar_stream, mode="r:tar") as tar:
            for member in tar.getmembers():
                tar.extract(member, output_dir, filter="data")
                extracted.append(member.name)

        return extracted

    def extract_selective(self, filepath: str, output_dir: str,
                          patterns: Optional[List[str]] = None) -> List[str]:
        os.makedirs(output_dir, exist_ok=True)
        data = self.decompress(filepath)
        tar_stream = io.BytesIO(data)
        extracted = []

        with tarfile.open(fileobj=tar_stream, mode="r:tar") as tar:
            for member in tar.getmembers():
                if patterns:
                    if any(p in member.name for p in patterns):
                        tar.extract(member, output_dir, filter="data")
                        extracted.append(member.name)
                else:
                    tar.extract(member, output_dir, filter="data")
                    extracted.append(member.name)

        return extracted

    def list_contents(self, filepath: str) -> List[Dict[str, Any]]:
        data = self.decompress(filepath)
        tar_stream = io.BytesIO(data)
        contents = []

        with tarfile.open(fileobj=tar_stream, mode="r:tar") as tar:
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
        "app_",
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
            with tarfile.open(filepath, mode="r:tar") as tar:
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


def add_report(payload: Dict, output_dir: str, title: str) -> Dict:
    """Write a JSON report under output_dir and return the path."""
    os.makedirs(output_dir, exist_ok=True)
    report_path = os.path.join(output_dir, "report.json")
    with open(report_path, "w") as f:
        json.dump(payload, f, indent=2, default=str)
    report = dict(payload)
    report["report_path"] = report_path
    return report


def cmd_demo(args):
    print("=" * 66)
    print("  M6 - Android Backup Extractor - offline demo")
    print("=" * 66)
    tmp = tempfile.mkdtemp(prefix="m6_demo_")
    ab_path = os.path.join(tmp, "sample.ab")
    create_sample_ab_file(ab_path)

    workflow = BackupWorkflow(output_dir=os.path.join(args.output_dir, "m6"))
    header = workflow.extractor.read_header(ab_path)
    print("  Header           :", header)

    contents = workflow.extractor.list_contents(ab_path)
    print("  Contents         : %d entries" % len(contents))
    for item in contents:
        prefix = "d" if item["type"] == "dir" else "f"
        print("    %s %s (%d bytes)" % (prefix, item["name"], item["size"]))

    extraction = workflow.extract_backup(ab_path)
    sensitive = extraction["sensitive_keys"]
    print("  Shared prefs     : %d file(s)" % len(extraction["prefs_files"]))
    print("  Sensitive keys   : %s" % json.dumps(sensitive))

    report = add_report({
        "demo": True,
        "header": {
            "version": header.version,
            "compressed": header.compressed,
            "schema_version": header.backup_schema_version,
            "device_checksum": header.device_checksum,
        },
        "contents_count": len(contents),
        "extracted_files": len(extraction["extracted_files"]),
        "prefs_files": extraction["prefs_files"],
        "sensitive_keys": sensitive,
        "input_sha256": hashlib.sha256(
            open(ab_path, "rb").read()).hexdigest(),
    }, args.output_dir, "M6 backup demo")
    shutil.rmtree(tmp, ignore_errors=True)
    print("  report           : %s" % report["report_path"])
    print("  exit=0")
    return 0


def main():
    p = argparse.ArgumentParser(
        prog="backup_extract.py",
        description="M6 - Android Backup (.ab) parser, extractor and "
                    "shared-preferences analyzer")
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("demo", help="offline demo (exits 0)").set_defaults(
        func=cmd_demo)

    p_info = sub.add_parser("info", help="show backup file info")
    p_info.add_argument("ab_file")
    p_info.set_defaults(func=cmd_info)

    p_header = sub.add_parser("header", help="parse and display header")
    p_header.add_argument("ab_file")
    p_header.set_defaults(func=cmd_header)

    p_contents = sub.add_parser("contents", help="list backup contents")
    p_contents.add_argument("ab_file")
    p_contents.set_defaults(func=cmd_contents)

    p_extract = sub.add_parser("extract", help="extract backup to output dir")
    p_extract.add_argument("ab_file")
    p_extract.set_defaults(func=cmd_extract)

    p_prefs = sub.add_parser("prefs", help="extract and parse shared_prefs")
    p_prefs.add_argument("ab_file")
    p_prefs.set_defaults(func=cmd_prefs)

    p_report = sub.add_parser("report", help="generate full analysis report")
    p_report.add_argument("ab_file")
    p_report.set_defaults(func=cmd_report)

    p_parse = sub.add_parser("parse-prefs", help="parse a shared_prefs XML file")
    p_parse.add_argument("xml_file")
    p_parse.set_defaults(func=cmd_parse_prefs)

    p_create = sub.add_parser("create-sample", help="create a sample .ab file")
    p_create.add_argument("output_file")
    p_create.set_defaults(func=cmd_create_sample)

    p.add_argument("-o", "--output-dir", default="reports",
                   help="directory for reports (default: reports)")

    args = p.parse_args()
    if not getattr(args, "cmd", None):
        p.print_help()
        return 0
    return args.func(args)


def cmd_info(args):
    workflow = BackupWorkflow()
    print(json.dumps(workflow.extractor.get_info(args.ab_file), indent=2))
    return 0


def cmd_header(args):
    try:
        header = BackupExtractor().read_header(args.ab_file)
        print(header)
        return 0
    except ValueError as e:
        print(f"Error: {e}")
        return 1


def cmd_contents(args):
    try:
        contents = BackupExtractor().list_contents(args.ab_file)
        for item in contents:
            prefix = "d" if item["type"] == "dir" else "f"
            print(f"  {prefix} {item['name']} ({item['size']} bytes)")
        return 0
    except Exception as e:
        print(f"Error: {e}")
        return 1


def cmd_extract(args):
    try:
        workflow = BackupWorkflow()
        extracted = workflow.extractor.extract_tar(args.ab_file, workflow.output_dir)
        print(f"Extracted {len(extracted)} files to {workflow.output_dir}")
        return 0
    except Exception as e:
        print(f"Error: {e}")
        return 1


def cmd_prefs(args):
    try:
        workflow = BackupWorkflow()
        extraction = workflow.extract_backup(args.ab_file)
        print(f"Parsed {len(extraction['prefs_files'])} preference files")
        print(f"Sensitive keys found: {json.dumps(extraction['sensitive_keys'])}")
        print(json.dumps(extraction["prefs_data"], indent=2))
        return 0
    except Exception as e:
        print(f"Error: {e}")
        return 1


def cmd_report(args):
    try:
        report = BackupWorkflow(output_dir=os.path.join(args.output_dir, "m6")) \
            .full_report(args.ab_file)
        print(f"Report saved to: {report['report_path']}")
        return 0
    except Exception as e:
        print(f"Error: {e}")
        return 1


def cmd_parse_prefs(args):
    parser = SharedPrefsParser()
    prefs = parser.parse_file(args.xml_file)
    print(json.dumps(prefs, indent=2))
    return 0


def cmd_create_sample(args):
    path = create_sample_ab_file(args.output_file)
    print(f"Created sample AB file: {path}")
    return 0


if __name__ == "__main__":
    main()
