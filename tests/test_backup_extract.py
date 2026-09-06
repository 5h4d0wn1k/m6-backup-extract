#!/usr/bin/env python3
"""Tests for m6-backup-extract Android Backup (.ab) extractor."""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import backup_extract as be

SCRIPT = os.path.join(ROOT, "backup_extract.py")


def make_sample(path):
    return be.create_sample_ab_file(path)


class TestABHeader(unittest.TestCase):
    def test_from_file(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "s.ab")
            make_sample(p)
            h = be.ABHeader.from_file(p)
            self.assertEqual(h.magic, b"Android Backup")
            self.assertEqual(h.version, 1)
            self.assertTrue(h.compressed)
            self.assertEqual(h.backup_schema_version, 1)

    def test_from_stream(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "s.ab")
            make_sample(p)
            with open(p, "rb") as f:
                h = be.ABHeader.from_stream(io.BytesIO(f.read()))
            self.assertEqual(h.magic, b"Android Backup")
            self.assertTrue(h.compressed)

    def test_bad_magic(self):
        with self.assertRaises(ValueError):
            be.ABHeader.from_stream(io.BytesIO(b"NOT A BACKUP\n1\n1\n1\nnone\n"))


class TestBackupExtractor(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.ab = os.path.join(self.td, "s.ab")
        make_sample(self.ab)

    def tearDown(self):
        shutil.rmtree(self.td, ignore_errors=True)

    def test_read_header(self):
        ex = be.BackupExtractor()
        h = ex.read_header(self.ab)
        self.assertEqual(h.version, 1)
        self.assertTrue(h.compressed)

    def test_decompress_gives_tar(self):
        ex = be.BackupExtractor()
        data = ex.decompress(self.ab)
        self.assertEqual(data[257:262].rstrip(b"\x00"), b"ustar")

    def test_list_contents(self):
        ex = be.BackupExtractor()
        contents = ex.list_contents(self.ab)
        names = [c["name"] for c in contents]
        self.assertIn("shared_prefs", names)
        self.assertIn("shared_prefs/user_prefs.xml", names)
        self.assertIn("databases/app.db", names)

    def test_extract_tar_roundtrip(self):
        ex = be.BackupExtractor()
        outdir = os.path.join(self.td, "extracted")
        files = ex.extract_tar(self.ab, outdir)
        self.assertTrue(
            os.path.exists(os.path.join(outdir, "shared_prefs", "user_prefs.xml")))
        self.assertIn("shared_prefs/user_prefs.xml", files)

    def test_extract_selective(self):
        ex = be.BackupExtractor()
        outdir = os.path.join(self.td, "sel")
        files = ex.extract_selective(self.ab, outdir, patterns=["databases"])
        self.assertEqual(files, ["databases/app.db"])
        self.assertTrue(os.path.exists(os.path.join(outdir, "databases", "app.db")))

    def test_get_info(self):
        info = be.BackupExtractor().get_info(self.ab)
        self.assertTrue(info["exists"])
        self.assertEqual(info["header"]["compressed"], True)


class TestSharedPrefsParser(unittest.TestCase):
    def test_parse_file_pref_types(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "prefs.xml")
            with open(p, "w") as f:
                f.write(be.create_sample_prefs_xml())
            prefs = be.SharedPrefsParser().parse_file(p)
        self.assertIs(prefs["dark_mode"], True)
        self.assertEqual(prefs["username"], "testuser")
        self.assertEqual(prefs["login_count"], 42)
        self.assertAlmostEqual(prefs["volume"], 0.75)
        self.assertEqual(prefs["seen_categories"], ["tech", "news", "sports"])

    def test_parse_from_string(self):
        xml = be.create_sample_prefs_xml()
        prefs = be.SharedPrefsParser().parse_from_string(xml)
        self.assertEqual(prefs["session_token"], "abc123def456")

    def test_get_sensitive_keys(self):
        xml = be.create_sample_prefs_xml()
        parser = be.SharedPrefsParser()
        parser.parse_from_string(xml)
        sensitive = parser.get_sensitive_keys()
        self.assertIn("session_token", sensitive)
        self.assertIn("api_key", sensitive)
        self.assertNotIn("username", sensitive)


class TestTarAnalyzer(unittest.TestCase):
    def test_analyze(self):
        with tempfile.TemporaryDirectory() as td:
            import io as _io
            import tarfile as _tf
            buf = _io.BytesIO()
            with _tf.open(fileobj=buf, mode="w") as tar:
                info = _tf.TarInfo(name="databases/app.db")
                info.size = 4
                tar.addfile(info, _io.BytesIO(b"data"))
                info = _tf.TarInfo(name="misc/notes.txt")
                info.size = 3
                tar.addfile(info, _io.BytesIO(b"abc"))
            tp = os.path.join(td, "t.tar")
            with open(tp, "wb") as f:
                f.write(buf.getvalue())
            result = be.TarAnalyzer().analyze(tp)
        self.assertEqual(result["stats"]["files"], 2)
        self.assertIn("databases/app.db",
                      [f["name"] for f in result["sensitive"]])


class TestWorkflow(unittest.TestCase):
    def test_full_report(self):
        with tempfile.TemporaryDirectory() as td:
            ab = os.path.join(td, "s.ab")
            make_sample(ab)
            out = os.path.join(td, "out")
            wf = be.BackupWorkflow(output_dir=out)
            report = wf.full_report(ab)
            self.assertIn("report_path", report)
            self.assertTrue(os.path.exists(report["report_path"]))
            with open(report["report_path"]) as f:
                data = json.load(f)
            self.assertEqual(data["extraction"]["extracted_count"], 4)
            self.assertIn("session_token",
                          data["extraction"]["sensitive_keys"])


class TestCli(unittest.TestCase):
    def test_demo_exits_zero(self):
        r = subprocess.run([sys.executable, SCRIPT, "-o",
                            tempfile.gettempdir(), "demo"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("exit=0", r.stdout)

    def test_create_sample_then_contents(self):
        with tempfile.TemporaryDirectory() as td:
            ab = os.path.join(td, "s.ab")
            r = subprocess.run([sys.executable, SCRIPT, "create-sample", ab],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            r = subprocess.run([sys.executable, SCRIPT, "contents", ab],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("databases/app.db", r.stdout)

    def test_report_cli_writes_files(self):
        with tempfile.TemporaryDirectory() as td:
            ab = os.path.join(td, "s.ab")
            make_sample(ab)
            out = os.path.join(td, "rep")
            r = subprocess.run([sys.executable, SCRIPT, "-o", out, "report", ab],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(os.path.exists(os.path.join(out, "m6", "report.json")))


if __name__ == "__main__":
    unittest.main()