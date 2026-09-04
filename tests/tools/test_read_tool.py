import os
import tempfile
import time
import unittest
from unittest.mock import patch

from PIL import Image

from tools.read import (
    _DOC_CACHE,
    MAX_DOC_CACHE,
    ReadTool,
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
            _DOC_CACHE.put(fake_path, (12345.0, now, "valid cached content"))
            res = get_cached_doc_markdown(fake_path)
            self.assertEqual(res, "valid cached content")

    def test_get_cached_doc_markdown_expired(self):
        fake_path = "/tmp/fake.pdf"
        with patch("os.path.getmtime", return_value=12345.0):
            _DOC_CACHE.put(fake_path, (12345.0, time.monotonic() - 1000.0, "old content"))
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
                _DOC_CACHE.put(p, (100.0, time.monotonic() - (100 - i), f"content {i}"))

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

    def test_convert_doc_to_markdown_sync_success(self):
        fake_path = "/tmp/doc.docx"
        with (
            patch("tools.read.get_cached_doc_markdown", return_value=None),
            patch("core.infrastructure.converter.convert_file", return_value="# Doc Output"),
        ):
            res = convert_doc_to_markdown_sync(fake_path)
            self.assertEqual(res, "# Doc Output")

    def test_convert_doc_to_markdown_sync_failure_raises(self):
        fake_path = "/tmp/failed.docx"
        with (
            patch("tools.read.get_cached_doc_markdown", return_value=None),
            patch("core.infrastructure.converter.convert_file", side_effect=RuntimeError("fail")),
        ):
            with self.assertRaises(RuntimeError) as ctx:
                convert_doc_to_markdown_sync(fake_path)
            self.assertIn("Unable to convert", str(ctx.exception))

    def test_empty_conversion_result_not_cached(self):
        fake_path = "/tmp/empty_not_cached.pdf"
        if fake_path in _DOC_CACHE:
            del _DOC_CACHE[fake_path]
        try:
            with (
                patch("tools.read.get_cached_doc_markdown", return_value=None),
                patch("core.infrastructure.converter.convert_file", return_value=""),
            ):
                res = convert_doc_to_markdown_sync(fake_path)
                self.assertEqual(res, "")
                self.assertNotIn(fake_path, _DOC_CACHE)
        finally:
            if fake_path in _DOC_CACHE:
                del _DOC_CACHE[fake_path]

    def test_convert_doc_to_markdown_sync_cooperative_cancel(self):
        import threading

        cancel_event = threading.Event()
        cancel_event.set()
        fake_path = "/tmp/cancel_doc.docx"
        with (
            patch("tools.read.get_cached_doc_markdown", return_value=None),
            patch("core.infrastructure.converter.convert_file", side_effect=RuntimeError("fail")),
        ):
            res = convert_doc_to_markdown_sync(fake_path, cancel_event=cancel_event)
            self.assertEqual(res, "")

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
        res_match = str(await tool.execute({"path": os.path.join(parent_dir, "applc.txt")}))
        self.assertIn("did you mean:", res_match)
        self.assertIn("apple.txt", res_match)

        # No match hint (fallback sample files list)
        res_sample = str(await tool.execute({"path": os.path.join(parent_dir, "1234567890")}))
        self.assertIn("available files:", res_sample)
        self.assertIn("apple.txt", res_sample)

    async def test_read_empty_directory(self):
        tool = ReadTool()
        empty_dir = os.path.join(self.test_dir, "empty_dir")
        os.makedirs(empty_dir, exist_ok=True)

        res = await tool.execute({"path": empty_dir})
        self.assertIn("empty", res.content)

    async def test_read_directory_with_subdirs(self):
        tool = ReadTool()
        parent_dir = os.path.join(self.test_dir, "dir_with_sub")
        os.makedirs(os.path.join(parent_dir, "child_folder"), exist_ok=True)
        with open(os.path.join(parent_dir, "file.txt"), "w") as f:
            f.write("text")

        res = str(await tool.execute({"path": parent_dir}))
        self.assertIn("child_folder/", res)
        self.assertIn("file.txt", res)

    async def test_read_directory_exception(self):
        tool = ReadTool()
        with patch("os.listdir", side_effect=PermissionError("Permission denied")):
            res = str(await tool.execute({"path": self.test_dir}))
            self.assertIn("ERR: listing", res)

    async def test_read_file_getsize_oserror(self):
        tool = ReadTool()
        file_path = os.path.join(self.test_dir, "test.txt")
        with open(file_path, "w") as f:
            f.write("content")

        with patch("os.path.getsize", side_effect=OSError("Disk read error")):
            res = str(await tool.execute({"path": file_path}))
            self.assertIn("ERR: check", res)

    async def test_read_doc_conversion_error(self):
        tool = ReadTool()
        doc_path = os.path.join(self.test_dir, "broken.docx")
        with open(doc_path, "w") as f:
            f.write("not a real docx")

        with patch("tools.read.convert_doc_to_markdown_sync", side_effect=RuntimeError("Doc convert fail")):
            res = str(await tool.execute({"path": doc_path}))
            self.assertIn("ERR: doc", res)

    async def test_read_content_offset_parsing_and_error(self):
        tool = ReadTool()
        file_path = os.path.join(self.test_dir, "offset.txt")
        with open(file_path, "wb") as f:
            f.write(b"0123456789ABCDEF")

        # Valid offset
        res_offset = str(await tool.execute({"path": file_path, "content_offset": 10}))
        self.assertIn("ABCDEF", res_offset)

        # Invalid string content_offset -> fallback to 0
        res_invalid_offset = str(await tool.execute({"path": file_path, "content_offset": "invalid_number"}))
        self.assertIn("0123456789ABCDEF", res_invalid_offset)

        # File read exception inside _read_file_lines
        with patch("builtins.open", side_effect=IOError("Read error")):
            res_err = str(await tool.execute({"path": file_path}))
            self.assertIn("ERR: execute", res_err)

    async def test_read_start_line_offsets_window(self):
        tool = ReadTool()
        file_path = os.path.join(self.test_dir, "lines.txt")
        with open(file_path, "w") as f:
            f.write("line 1\nline 2\nline 3\nline 4\n")

        res = str(await tool.execute({"path": file_path, "start_line": 3}))
        self.assertIn("line 3", res)
        self.assertNotIn("line 1", res)

    async def test_read_offset_alias_rejected(self):
        # 'offset' is no longer aliased to start_line; it is ignored by the reader.
        tool = ReadTool()
        file_path = os.path.join(self.test_dir, "lines.txt")
        with open(file_path, "w") as f:
            f.write("line 1\nline 2\nline 3\nline 4\n")

        res = str(await tool.execute({"path": file_path, "offset": 3}))
        self.assertIn("line 1", res)

    async def test_read_empty_or_missing_path(self):
        tool = ReadTool()
        res_empty = str(await tool.execute({"path": ""}))
        self.assertIn("ERR: params 'path': missing or empty", res_empty)

        res_none = str(await tool.execute({"path": None}))
        self.assertIn("ERR: params 'path': missing or empty", res_none)

        res_missing = str(await tool.execute({}))
        self.assertIn("ERR: params 'path': missing or empty", res_missing)

    async def test_read_nonexistent_file(self):
        tool = ReadTool()
        res = str(await tool.execute({"path": "https://example.com/page.html"}))
        self.assertIn("not found", res)

    @patch("tools.read.convert_doc_to_markdown_sync")
    async def test_read_doc_truncation_saves_markdown_snapshot(self, mock_convert):
        long_md = "\n".join([f"# Header {i}\nParagraph content line {i}" for i in range(1, 600)])
        mock_convert.return_value = long_md

        tool = ReadTool()
        file_path = os.path.join(self.test_dir, "large_report.pdf")
        with open(file_path, "wb") as f:
            f.write(b"%PDF-1.4 dummy")

        res = await tool.execute({"path": file_path})

        self.assertIn("converted ", res.content)
        self.assertIn(".md", res.content)

        import asyncio
        import re

        await asyncio.sleep(0.05)

        # Extract path and verify file exists on disk
        m = re.search(r'converted\s+([^\]\s]+)', res.content)
        self.assertIsNotNone(m)
        saved_path = m.group(1)
        self.assertTrue(os.path.exists(saved_path))
        with open(saved_path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), long_md)

    async def test_read_directory_listing(self):
        tool = ReadTool()
        subdir = os.path.join(self.test_dir, "sub")
        os.makedirs(subdir, exist_ok=True)
        with open(os.path.join(self.test_dir, "file_a.txt"), "w") as f:
            f.write("hello")
        res = await tool.execute({"path": self.test_dir})
        self.assertIn("[dir ", res.content)
        self.assertIn("sub/", res.content)
        self.assertIn("file_a.txt", res.content)

    async def test_read_directory_empty(self):
        tool = ReadTool()
        empty_dir = os.path.join(self.test_dir, "empty_folder")
        os.makedirs(empty_dir, exist_ok=True)
        res = await tool.execute({"path": empty_dir})
        self.assertIn("total 0", res.content)

    async def test_read_zip_archive(self):
        import zipfile
        tool = ReadTool()
        zip_path = os.path.join(self.test_dir, "sample.zip")
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("src/", "")
            zf.writestr("src/main.py", "print(1)")
            zf.writestr("README.md", "# Hello")
            zf.writestr("__MACOSX/._test", "junk")
        res = await tool.execute({"path": zip_path})
        self.assertIn("[archive ", res.content)
        self.assertIn("total 3", res.content)
        self.assertIn("src/", res.content)
        self.assertIn("src/main.py", res.content)
        self.assertIn("README.md", res.content)
        self.assertNotIn("__MACOSX", res.content)

    async def test_read_tar_archive(self):
        import tarfile
        tool = ReadTool()
        tar_path = os.path.join(self.test_dir, "sample.tar.gz")
        with tarfile.open(tar_path, "w:gz") as tf:
            ti = tarfile.TarInfo("docs/")
            ti.type = tarfile.DIRTYPE
            tf.addfile(ti)
            data = b"content"
            ti2 = tarfile.TarInfo("docs/guide.txt")
            ti2.size = len(data)
            import io
            tf.addfile(ti2, io.BytesIO(data))
        res = await tool.execute({"path": tar_path})
        self.assertIn("[archive ", res.content)
        self.assertIn("docs/", res.content)
        self.assertIn("docs/guide.txt", res.content)

    async def test_read_archive_empty(self):
        import zipfile
        tool = ReadTool()
        zip_path = os.path.join(self.test_dir, "empty.zip")
        with zipfile.ZipFile(zip_path, "w"):
            pass
        res = await tool.execute({"path": zip_path})
        self.assertIn("total 0", res.content)

    async def test_read_archive_truncated(self):
        import zipfile
        tool = ReadTool()
        zip_path = os.path.join(self.test_dir, "many.zip")
        with zipfile.ZipFile(zip_path, "w") as zf:
            for i in range(70):
                zf.writestr(f"item_{i}.txt", f"data {i}")
        res = await tool.execute({"path": zip_path})
        self.assertIn("truncated", res.content)
        self.assertIn("total 70", res.content)

    async def test_read_archive_corrupted(self):
        tool = ReadTool()
        bad_zip = os.path.join(self.test_dir, "bad.zip")
        with open(bad_zip, "wb") as f:
            f.write(b"not a real zip content")
        res = await tool.execute({"path": bad_zip})
        self.assertIn("ERR: archive", str(res))

    async def test_read_directory_pagination(self):
        tool = ReadTool()
        paged_dir = os.path.join(self.test_dir, "paged_dir")
        os.makedirs(paged_dir, exist_ok=True)
        for i in range(25):
            with open(os.path.join(paged_dir, f"file_{i:02d}.txt"), "w") as f:
                f.write(f"content {i}")

        # Request first 10 items
        res1 = await tool.execute({"path": paged_dir, "start_line": 1, "end_line": 10})
        self.assertIn("entries 1..10 of 25", res1.content)
        self.assertIn("file_00.txt", res1.content)
        self.assertNotIn("file_15.txt", res1.content)

        # Request next items
        res2 = await tool.execute({"path": paged_dir, "start_line": 11, "end_line": 20})
        self.assertIn("entries 11..20 of 25", res2.content)
        self.assertIn("file_10.txt", res2.content)
        self.assertNotIn("file_00.txt", res2.content)

    async def test_read_directory_metadata_and_hidden_order(self):
        tool = ReadTool()
        meta_dir = os.path.join(self.test_dir, "meta_dir")
        os.makedirs(meta_dir, exist_ok=True)
        # Normal dir and file
        sub = os.path.join(meta_dir, "my_sub")
        os.makedirs(sub, exist_ok=True)
        with open(os.path.join(sub, "child.txt"), "w") as f:
            f.write("data")
        with open(os.path.join(meta_dir, "app.py"), "w") as f:
            f.write("print('hi')")
        # Hidden dir and file
        hidden_dir = os.path.join(meta_dir, ".hidden_sub")
        os.makedirs(hidden_dir, exist_ok=True)
        with open(os.path.join(meta_dir, ".env"), "w") as f:
            f.write("SECRET=1")

        res = await tool.execute({"path": meta_dir})
        self.assertIn("my_sub/ (1 item)", res.content)
        self.assertIn("app.py (11 B)", res.content)
        self.assertIn(".hidden_sub/", res.content)
        self.assertIn(".env (8 B)", res.content)

        # Normal files and dirs must appear BEFORE hidden items
        lines = res.content.splitlines()
        app_idx = next(i for i, line in enumerate(lines) if "app.py" in line)
        env_idx = next(i for i, line in enumerate(lines) if ".env" in line)
        self.assertLess(app_idx, env_idx)

    async def test_read_archive_pagination(self):
        import zipfile
        tool = ReadTool()
        zip_path = os.path.join(self.test_dir, "paged.zip")
        with zipfile.ZipFile(zip_path, "w") as zf:
            for i in range(30):
                zf.writestr(f"archive_file_{i:02d}.txt", f"data {i}")

        res = await tool.execute({"path": zip_path, "start_line": 5, "end_line": 15})
        self.assertIn("entries 5..15 of 30", res.content)
        self.assertIn("archive_file_04.txt", res.content)
        self.assertNotIn("archive_file_25.txt", res.content)


if __name__ == "__main__":
    unittest.main()

