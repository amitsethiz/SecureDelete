"""
Automated tests for securedelete core logic.
Run with:  python -m pytest test_securedelete.py -v
       or: python test_securedelete.py
"""

import os
import struct
import tempfile
import threading
import unittest

import securedelete as sd


# ===========================================================================
# format_bytes
# ===========================================================================
class TestFormatBytes(unittest.TestCase):
    def test_bytes(self):
        self.assertEqual(sd.format_bytes(512), "512.00 B")

    def test_kilobytes(self):
        self.assertEqual(sd.format_bytes(1024), "1.00 KB")

    def test_megabytes(self):
        self.assertEqual(sd.format_bytes(1024 ** 2), "1.00 MB")

    def test_gigabytes(self):
        self.assertEqual(sd.format_bytes(1024 ** 3), "1.00 GB")

    def test_zero(self):
        self.assertEqual(sd.format_bytes(0), "0.00 B")

    def test_fractional(self):
        self.assertIn("1.50", sd.format_bytes(1536))


# ===========================================================================
# format_time
# ===========================================================================
class TestFormatTime(unittest.TestCase):
    def test_seconds(self):
        self.assertEqual(sd.format_time(45.0), "45s")

    def test_minutes(self):
        self.assertEqual(sd.format_time(90.0), "1m 30s")

    def test_hours(self):
        self.assertEqual(sd.format_time(3661.0), "1h 1m 1s")

    def test_zero(self):
        self.assertEqual(sd.format_time(0), "0s")


# ===========================================================================
# make_fill_data
# ===========================================================================
class TestMakeFillData(unittest.TestCase):
    def test_pass1_zeros(self):
        data = sd.make_fill_data(1, 8)
        self.assertEqual(data, b"\x00" * 8)

    def test_pass2_ones(self):
        data = sd.make_fill_data(2, 8)
        self.assertEqual(data, b"\xFF" * 8)

    def test_pass3_random(self):
        d1 = sd.make_fill_data(3, 32)
        d2 = sd.make_fill_data(3, 32)
        self.assertEqual(len(d1), 32)
        # Probability of two 32-byte random values colliding is astronomically low
        self.assertNotEqual(d1, d2)

    def test_correct_length(self):
        for p in (1, 2, 3, 4):
            self.assertEqual(len(sd.make_fill_data(p, 100)), 100)


# ===========================================================================
# random_name
# ===========================================================================
class TestRandomName(unittest.TestCase):
    def test_default_length(self):
        name = sd.random_name()
        self.assertEqual(len(name), 16)

    def test_custom_length(self):
        name = sd.random_name(8)
        self.assertEqual(len(name), 8)

    def test_only_alphanumeric(self):
        for _ in range(20):
            name = sd.random_name(32)
            self.assertTrue(name.isalnum(), f"Non-alphanumeric chars in: {name!r}")

    def test_uniqueness(self):
        names = {sd.random_name() for _ in range(100)}
        self.assertEqual(len(names), 100)


# ===========================================================================
# shred_file
# ===========================================================================
class TestShredFile(unittest.TestCase):
    def _make_temp(self, content=b"SENSITIVE DATA 1234567890"):
        fd, path = tempfile.mkstemp()
        with os.fdopen(fd, "wb") as f:
            f.write(content)
        return path

    def test_file_deleted_after_shred(self):
        path = self._make_temp()
        result = sd.shred_file(path, passes=1, verbose=False)
        self.assertTrue(result)
        self.assertFalse(os.path.exists(path), "File should not exist after shred")

    def test_returns_false_for_nonexistent_file(self):
        result = sd.shred_file("/nonexistent/path/file.txt", passes=1, verbose=False)
        self.assertFalse(result)

    def test_multi_pass_shred(self):
        path = self._make_temp(b"X" * 1024)
        result = sd.shred_file(path, passes=3, verbose=False)
        self.assertTrue(result)
        self.assertFalse(os.path.exists(path))

    def test_empty_file_shred(self):
        fd, path = tempfile.mkstemp()
        os.close(fd)
        result = sd.shred_file(path, passes=1, verbose=False)
        self.assertTrue(result)
        self.assertFalse(os.path.exists(path))

    def test_large_file_shred(self):
        fd, path = tempfile.mkstemp()
        with os.fdopen(fd, "wb") as f:
            f.write(b"A" * (5 * 1024 * 1024))  # 5 MB
        result = sd.shred_file(path, passes=1, verbose=False)
        self.assertTrue(result)
        self.assertFalse(os.path.exists(path))


# ===========================================================================
# shred_directory
# ===========================================================================
class TestShredDirectory(unittest.TestCase):
    def test_directory_and_contents_deleted(self):
        tmpdir = tempfile.mkdtemp()
        # Create a few files
        for name in ("a.txt", "b.dat", "c.bin"):
            with open(os.path.join(tmpdir, name), "wb") as f:
                f.write(b"data " * 100)
        success, failed = sd.shred_directory(tmpdir, passes=1, verbose=False)
        self.assertEqual(success, 3)
        self.assertEqual(failed, 0)
        self.assertFalse(os.path.exists(tmpdir))

    def test_nested_directory(self):
        tmpdir = tempfile.mkdtemp()
        subdir = os.path.join(tmpdir, "sub")
        os.makedirs(subdir)
        with open(os.path.join(subdir, "file.txt"), "wb") as f:
            f.write(b"nested")
        success, failed = sd.shred_directory(tmpdir, passes=1, verbose=False)
        self.assertEqual(success, 1)
        self.assertFalse(os.path.exists(tmpdir))

    def test_nonexistent_directory(self):
        success, failed = sd.shred_directory("/no/such/dir", passes=1, verbose=False)
        self.assertEqual(success, 0)
        self.assertEqual(failed, 1)


# ===========================================================================
# carve_drive (file-based — does not need admin / raw drive access)
# ===========================================================================
class TestCarveDrive(unittest.TestCase):
    def _write_mock_drive(self, path, payload: bytes):
        """Write a small mock 'drive' image with embedded file signatures."""
        with open(path, "wb") as f:
            # Padding, then payload, then more padding
            f.write(b"\x00" * 512)
            f.write(payload)
            f.write(b"\x00" * 512)

    def test_carve_jpg(self):
        with tempfile.TemporaryDirectory() as out_dir:
            with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
                mock_path = f.name
            try:
                # Minimal JPEG: SOI + a few bytes + EOI
                jpg = b"\xFF\xD8\xFF\xE0" + b"\x00" * 16 + b"\xFF\xD9"
                self._write_mock_drive(mock_path, jpg)
                found = sd.carve_drive(mock_path, out_dir, max_scan_bytes=0, types=["jpg"])
                self.assertGreaterEqual(found, 1)
                recovered = [f for f in os.listdir(out_dir) if f.endswith(".jpg")]
                self.assertTrue(len(recovered) >= 1)
            finally:
                os.unlink(mock_path)

    def test_carve_pdf(self):
        with tempfile.TemporaryDirectory() as out_dir:
            with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
                mock_path = f.name
            try:
                pdf = b"%PDF-1.4\n%some content here\n%%EOF"
                self._write_mock_drive(mock_path, pdf)
                found = sd.carve_drive(mock_path, out_dir, max_scan_bytes=0, types=["pdf"])
                self.assertGreaterEqual(found, 1)
            finally:
                os.unlink(mock_path)

    def test_carve_sqlite(self):
        with tempfile.TemporaryDirectory() as out_dir:
            with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
                mock_path = f.name
            try:
                # Minimal SQLite header: magic + 100-byte header + some zeros
                sqlite = b"SQLite format 3\x00" + b"\x00" * 100
                self._write_mock_drive(mock_path, sqlite)
                found = sd.carve_drive(mock_path, out_dir, max_scan_bytes=0, types=["sqlite"])
                self.assertGreaterEqual(found, 1)
            finally:
                os.unlink(mock_path)

    def test_no_match_returns_zero(self):
        with tempfile.TemporaryDirectory() as out_dir:
            with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
                mock_path = f.name
            try:
                # Random noise — no known signatures
                import secrets
                with open(mock_path, "wb") as f:
                    f.write(secrets.token_bytes(4096))
                found = sd.carve_drive(mock_path, out_dir, max_scan_bytes=0, types=["pdf"])
                self.assertEqual(found, 0)
            finally:
                os.unlink(mock_path)

    def test_stop_event_halts_scan(self):
        with tempfile.TemporaryDirectory() as out_dir:
            with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
                mock_path = f.name
            try:
                with open(mock_path, "wb") as f:
                    f.write(b"\x00" * (8 * 1024 * 1024))
                stop = threading.Event()
                stop.set()  # Pre-set — carve should abort immediately
                found = sd.carve_drive(mock_path, out_dir, max_scan_bytes=0,
                                       types=["jpg"], stop_event=stop)
                self.assertEqual(found, 0)
            finally:
                os.unlink(mock_path)


# ===========================================================================
# VERSION constant
# ===========================================================================
class TestVersion(unittest.TestCase):
    def test_version_exists(self):
        self.assertTrue(hasattr(sd, "VERSION"))

    def test_version_is_string(self):
        self.assertIsInstance(sd.VERSION, str)

    def test_version_non_empty(self):
        self.assertTrue(sd.VERSION.strip())


# ===========================================================================
# _TeeStream (audit log)
# ===========================================================================
class TestTeeStream(unittest.TestCase):
    def test_tee_writes_to_both(self):
        import io
        terminal = io.StringIO()
        log = io.StringIO()
        tee = sd._TeeStream(terminal, log)
        tee.write("hello world\n")
        self.assertEqual(terminal.getvalue(), "hello world\n")
        self.assertEqual(log.getvalue(), "hello world\n")

    def test_tee_flush(self):
        import io
        tee = sd._TeeStream(io.StringIO(), io.StringIO())
        tee.flush()  # Should not raise


# ===========================================================================
if __name__ == "__main__":
    unittest.main(verbosity=2)
