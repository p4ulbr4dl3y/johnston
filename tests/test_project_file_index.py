import asyncio
import os
import tempfile

from johnston_core.infrastructure.runtime.project_file_index import ProjectFileIndex


def test_project_file_index_scan_and_cache():
    with tempfile.TemporaryDirectory() as tmpdir:
        f1 = os.path.join(tmpdir, "main.py")
        f2 = os.path.join(tmpdir, "test.txt")
        sub = os.path.join(tmpdir, "pkg")
        os.makedirs(sub)
        f3 = os.path.join(sub, "mod.py")

        for f in (f1, f2, f3):
            with open(f, "w") as fp:
                fp.write("content")

        idx = ProjectFileIndex(ttl=5.0)
        files = idx.scan_sync(tmpdir)

        assert "main.py" in files
        assert "test.txt" in files
        assert "pkg/mod.py" in files
        assert "pkg/" in files


def test_project_file_index_async():
    async def _test():
        with tempfile.TemporaryDirectory() as tmpdir:
            f1 = os.path.join(tmpdir, "file.py")
            with open(f1, "w") as fp:
                fp.write("code")

            idx = ProjectFileIndex(ttl=1.0)
            res1 = await idx.get_files(tmpdir)
            assert "file.py" in res1

            # Invalidate
            idx.invalidate()
            res2 = await idx.get_files(tmpdir)
            assert "file.py" in res2

    asyncio.run(_test())
