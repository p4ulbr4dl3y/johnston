import os
import subprocess
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

from PIL import Image

from tools.read import (
    _DOC_CACHE,
    MAX_DOC_CACHE,
    ReadTool,
    _communicate_cancellable,
    convert_doc_to_markdown_sync,
    get_cached_doc_markdown,
    process_image_file_sync,
    set_cached_doc_markdown,
)


class TestReadToolCoverage(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_dir = self.temp_dir.name
        _DOC_CACHE.clear()

    def tearDown(self):
        _DOC_CACHE.clear()
        self.temp_dir.cleanup()

    # --- Cache Function Tests ---
    def test_get_cached_doc_markdown_getmtime_error(self):
        with patch("os.path.getmtime", side_effect=OSError("File missing")):
            res = get_cached_doc_markdown("/nonexistent/file.pdf")
            self.assertIsNone(res)

    def test_get_cached_doc_markdown_hit(self):
        fake_path = "/tmp/fake.pdf"
        now = time.monotonic()
        with patch("os.path.getmtime", return_value=12345.0):
            _DOC_CACHE[fake_path] = (12345.0, now, "valid cached content")
            res = get_cached_doc_markdown(fake_path)
            self.assertEqual(res, "valid cached content")

    def test_get_cached_doc_markdown_expired(self):
        fake_path = "/tmp/fake.pdf"
        with patch("os.path.getmtime", return_value=12345.0):
            _DOC_CACHE[fake_path] = (12345.0, time.monotonic() - 1000.0, "old content")
            res = get_cached_doc_markdown(fake_path)
            self.assertIsNone(res)
            self.assertNotIn(fake_path, _DOC_CACHE)

    def test_set_cached_doc_markdown_getmtime_error(self):
        fake_path = "/nonexistent/file.pdf"
        with patch("os.path.getmtime", side_effect=OSError("File missing")):
            set_cached_doc_markdown(fake_path, "some content")
            self.assertNotIn(fake_path, _DOC_CACHE)

    def test_set_cached_doc_markdown_eviction(self):
        with patch("os.path.getmtime", return_value=100.0):
            for i in range(MAX_DOC_CACHE):
                p = f"/tmp/doc_{i}.pdf"
                _DOC_CACHE[p] = (100.0, time.monotonic() - (100 - i), f"content {i}")

            oldest_path = "/tmp/doc_0.pdf"
            self.assertIn(oldest_path, _DOC_CACHE)

            new_path = "/tmp/doc_new.pdf"
            set_cached_doc_markdown(new_path, "new content")
            self.assertNotIn(oldest_path, _DOC_CACHE)
            self.assertIn(new_path, _DOC_CACHE)

    # --- Document Conversion Tests ---
    def test_convert_doc_to_markdown_sync_cache_hit(self):
        fake_path = "/tmp/cached.docx"
        with patch("tools.read.get_cached_doc_markdown", return_value="# Cached Doc"):
            res = convert_doc_to_markdown_sync(fake_path)
            self.assertEqual(res, "# Cached Doc")

    def test_convert_doc_to_markdown_sync_cli_fallback(self):
        fake_path = "/tmp/cli_doc.docx"
        with (
            patch("tools.read.get_cached_doc_markdown", return_value=None),
            patch("shutil.which", return_value="/usr/local/bin/markitdown"),
            patch("subprocess.Popen") as mock_popen,
        ):
            proc = MagicMock()
            proc.communicate.return_value = ("# CLI Output", "")
            proc.returncode = 0
            proc.poll.return_value = 0
            mock_popen.return_value = proc
            # Force python import to fail
            with patch.dict("sys.modules", {"markitdown": None}):
                res = convert_doc_to_markdown_sync(fake_path)
                self.assertEqual(res, "# CLI Output")

    def test_convert_doc_to_markdown_sync_failure_raises(self):
        fake_path = "/tmp/failed.docx"
        with patch("tools.read.get_cached_doc_markdown", return_value=None), patch("shutil.which", return_value=None):
            with patch.dict("sys.modules", {"markitdown": None}):
                with self.assertRaises(RuntimeError) as ctx:
                    convert_doc_to_markdown_sync(fake_path)
                self.assertIn("Unable to convert", str(ctx.exception))

    def test_convert_doc_to_markdown_sync_cooperative_cancel(self):
        # A pre-set cancel_event makes the worker skip the CLI fallback and
        # skip caching, returning without launching the subprocess.
        import threading

        cancel_event = threading.Event()
        cancel_event.set()
        fake_path = "/tmp/cancel_doc.docx"
        with (
            patch("tools.read.get_cached_doc_markdown", return_value=None),
            patch("shutil.which", return_value="/usr/local/bin/markitdown"),
            patch("subprocess.Popen") as mock_popen,
            patch.dict("sys.modules", {"markitdown": None}),
        ):
            # Post-cancel the worker skips the CLI fallback, so no subprocess is
            # launched and no result is produced -> returns empty instead of
            # leaking an unreachable exception.
            res = convert_doc_to_markdown_sync(fake_path, cancel_event=cancel_event)
            self.assertEqual(res, "")
            mock_popen.assert_not_called()

    def test_communicate_cancellable_kills_on_cancel(self):
        import threading

        cancel_fired = threading.Event()

        def fake_communicate(timeout=None):
            # First poll raises so the loop can re-check cancellation; once the
            # cancel event is set, communicate returns (reaps the killed proc).
            if not cancel_fired.is_set():
                cancel_fired.set()
                raise subprocess.TimeoutExpired("cmd", timeout or 0.25)
            return ("out", "")

        proc = MagicMock()
        proc.poll.return_value = None  # Process still running
        proc.communicate.side_effect = fake_communicate

        def _interrupted() -> bool:
            return cancel_fired.is_set()

        _communicate_cancellable(proc, _interrupted, timeout=30)
        proc.kill.assert_called_once()
        self.assertEqual(proc.communicate.call_count, 2)

    def test_process_image_file_sync_cooperative_cancel(self):
        import threading

        cancel_event = threading.Event()
        path = os.path.join(self.test_dir, "cancel_me.png")
        Image.new("RGB", (1200, 1200), (10, 20, 30)).save(path, format="PNG")

        # Pre-set event -> worker aborts before heavy resize/encode.
        cancel_event.set()
        res = process_image_file_sync(path, cancel_event=cancel_event)
        self.assertEqual(res, "")

    # --- Image Processing Sync Tests ---
    def test_process_image_file_sync_rgba_la_p_cmyk(self):
        # Test RGBA composite conversion
        rgba_path = os.path.join(self.test_dir, "test_rgba.png")
        img_rgba = Image.new("RGBA", (100, 100), (255, 0, 0, 128))
        img_rgba.save(rgba_path, format="PNG")
        res_rgba = process_image_file_sync(rgba_path)
        self.assertIn('"media_type": "image/jpeg"', res_rgba)

        # Test CMYK conversion
        cmyk_path = os.path.join(self.test_dir, "test_cmyk.jpg")
        img_cmyk = Image.new("CMYK", (100, 100), (0, 255, 255, 0))
        img_cmyk.save(cmyk_path, format="JPEG")
        res_cmyk = process_image_file_sync(cmyk_path)
        self.assertIn('"media_type": "image/jpeg"', res_cmyk)

        # Test LA mode conversion
        la_path = os.path.join(self.test_dir, "test_la.png")
        img_la = Image.new("LA", (100, 100), (128, 128))
        img_la.save(la_path, format="PNG")
        res_la = process_image_file_sync(la_path)
        self.assertIn('"media_type": "image/jpeg"', res_la)

    def test_process_image_file_sync_png_format_preserved(self):
        png_path = os.path.join(self.test_dir, "small.png")
        img_png = Image.new("RGB", (100, 100), color=(0, 255, 0))
        img_png.save(png_path, format="PNG")

        res = process_image_file_sync(png_path)
        self.assertIn('"media_type": "image/png"', res)

    # --- ReadTool.execute Tests ---
    async def test_read_nonexistent_file_hints(self):
        tool = ReadTool()
        parent_dir = os.path.join(self.test_dir, "folder")
        os.makedirs(parent_dir, exist_ok=True)

        with open(os.path.join(parent_dir, "apple.txt"), "w") as f:
            f.write("apple")
        with open(os.path.join(parent_dir, "banana.txt"), "w") as f:
            f.write("banana")

        # Close match hint
        res_match = await tool.execute({"path": os.path.join(parent_dir, "applc.txt")})
        self.assertIn("Did you mean one of these in", res_match)
        self.assertIn("apple.txt", res_match)

        # No match hint (fallback sample files list)
        res_sample = await tool.execute({"path": os.path.join(parent_dir, "1234567890")})
        self.assertIn("Files available in", res_sample)
        self.assertIn("apple.txt", res_sample)

    async def test_read_empty_directory(self):
        tool = ReadTool()
        empty_dir = os.path.join(self.test_dir, "empty_dir")
        os.makedirs(empty_dir, exist_ok=True)

        res = await tool.execute({"path": empty_dir})
        self.assertIn("(empty directory)", res)

    async def test_read_directory_with_subdirs(self):
        tool = ReadTool()
        parent_dir = os.path.join(self.test_dir, "dir_with_sub")
        os.makedirs(os.path.join(parent_dir, "child_folder"), exist_ok=True)
        with open(os.path.join(parent_dir, "file.txt"), "w") as f:
            f.write("text")

        res = await tool.execute({"path": parent_dir})
        self.assertIn("child_folder/", res)
        self.assertIn("file.txt", res)

    async def test_read_directory_exception(self):
        tool = ReadTool()
        with patch("os.listdir", side_effect=PermissionError("Permission denied")):
            res = await tool.execute({"path": self.test_dir})
            self.assertIn("ERR: listing", res)

    async def test_read_file_getsize_oserror(self):
        tool = ReadTool()
        file_path = os.path.join(self.test_dir, "test.txt")
        with open(file_path, "w") as f:
            f.write("content")

        with patch("os.path.getsize", side_effect=OSError("Disk read error")):
            res = await tool.execute({"path": file_path})
            self.assertIn("ERR: check", res)

    async def test_read_doc_conversion_error(self):
        tool = ReadTool()
        doc_path = os.path.join(self.test_dir, "broken.docx")
        with open(doc_path, "w") as f:
            f.write("not a real docx")

        with patch("tools.read.convert_doc_to_markdown_sync", side_effect=RuntimeError("Doc convert fail")):
            res = await tool.execute({"path": doc_path})
            self.assertIn("ERR: doc", res)

    async def test_read_content_offset_parsing_and_error(self):
        tool = ReadTool()
        file_path = os.path.join(self.test_dir, "offset.txt")
        with open(file_path, "wb") as f:
            f.write(b"0123456789ABCDEF")

        # Valid offset
        res_offset = await tool.execute({"path": file_path, "content_offset": 10})
        self.assertIn("ABCDEF", res_offset)

        # Invalid string content_offset -> fallback to 0
        res_invalid_offset = await tool.execute({"path": file_path, "content_offset": "invalid_number"})
        self.assertIn("0123456789ABCDEF", res_invalid_offset)

        # File read exception inside _read_file_lines
        with patch("builtins.open", side_effect=IOError("Read error")):
            res_err = await tool.execute({"path": file_path})
            self.assertIn("ERR: file", res_err)

    async def test_read_offset_alias_maps_to_start_line(self):
        tool = ReadTool()
        file_path = os.path.join(self.test_dir, "lines.txt")
        with open(file_path, "w") as f:
            f.write("line 1\nline 2\nline 3\nline 4\n")

        res = await tool.execute({"path": file_path, "offset": 3})
        self.assertIn("line 3", res)
        self.assertNotIn("line 1", res)

    @patch("tools.web_fetch.WebFetchTool.execute")
    async def test_read_http_url_delegates_to_web_fetch(self, mock_web_execute):
        mock_web_execute.return_value = "# Web Page Content"
        tool = ReadTool()
        res = await tool.execute({"path": "https://example.com/page.html"})

        self.assertEqual(res, "# Web Page Content")
        mock_web_execute.assert_called_once()
        args, kwargs = mock_web_execute.call_args
        self.assertEqual(args[0], {"url": "https://example.com/page.html", "raw": False})


if __name__ == "__main__":
    unittest.main()
