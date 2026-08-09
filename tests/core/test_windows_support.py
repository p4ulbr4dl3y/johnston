import asyncio
import os
import signal
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from PIL import Image

from core.platform_utils import (
    get_clipboard_image_or_file,
    is_image_file,
    is_windows,
    johnston_config_dir,
    shell_env,
    shell_executable,
    shell_subprocess_kwargs,
    terminate_process,
)


class TestPlatformUtils(unittest.TestCase):
    def test_is_windows_real_posix(self):
        with patch("core.platform_utils.os.name", "posix"):
            self.assertFalse(is_windows())

    def test_is_windows_real_nt(self):
        with patch("core.platform_utils.os.name", "nt"):
            self.assertTrue(is_windows())

    def test_windows_config_dir_uses_appdata(self):
        with (
            patch("core.platform_utils.is_windows", return_value=True),
            patch.dict(os.environ, {"APPDATA": r"C:\Users\me\AppData\Roaming"}),
        ):
            self.assertEqual(johnston_config_dir(), Path(r"C:\Users\me\AppData\Roaming") / "johnston")

    def test_windows_config_dir_without_appdata(self):
        with (
            patch("core.platform_utils.is_windows", return_value=True),
            patch.dict(os.environ, {"APPDATA": ""}),
        ):
            self.assertEqual(johnston_config_dir(), Path.home() / ".johnston")

    def test_non_windows_config_dir(self):
        with patch("core.platform_utils.is_windows", return_value=False):
            self.assertEqual(johnston_config_dir(), Path.home() / ".johnston")

    def test_shell_executable_windows_finds_first_candidate(self):
        with (
            patch("core.platform_utils.is_windows", return_value=True),
            patch(
                "core.platform_utils.shutil.which",
                side_effect=lambda name: rf"C:\tools\{name}.exe",
            ),
        ):
            self.assertEqual(shell_executable(), r"C:\tools\pwsh.exe")

    def test_shell_executable_windows_finds_second_candidate(self):
        def fake_which(name):
            return "/usr/bin/powershell" if name == "powershell" else None

        with (
            patch("core.platform_utils.is_windows", return_value=True),
            patch("core.platform_utils.shutil.which", side_effect=fake_which),
        ):
            self.assertEqual(shell_executable(), "/usr/bin/powershell")

    def test_shell_executable_windows_none_found(self):
        with (
            patch("core.platform_utils.is_windows", return_value=True),
            patch("core.platform_utils.shutil.which", return_value=None),
        ):
            self.assertIsNone(shell_executable())

    def test_shell_executable_unix_uses_shell_env(self):
        with (
            patch("core.platform_utils.is_windows", return_value=False),
            patch.dict(os.environ, {"SHELL": "/bin/zsh"}),
        ):
            self.assertEqual(shell_executable(), "/bin/zsh")

    def test_shell_executable_unix_falls_back_to_which(self):
        with (
            patch("core.platform_utils.is_windows", return_value=False),
            patch.dict(os.environ, {"SHELL": ""}),
            patch("core.platform_utils.shutil.which", return_value="/usr/bin/sh"),
        ):
            self.assertEqual(shell_executable(), "/usr/bin/sh")

    def test_shell_executable_unix_hardcoded_sh(self):
        with (
            patch("core.platform_utils.is_windows", return_value=False),
            patch.dict(os.environ, {"SHELL": ""}),
            patch("core.platform_utils.shutil.which", return_value=None),
        ):
            self.assertEqual(shell_executable(), "/bin/sh")

    def test_shell_subprocess_kwargs_windows_creationflags(self):
        with (
            patch("core.platform_utils.is_windows", return_value=True),
            patch("core.platform_utils.subprocess.CREATE_NEW_PROCESS_GROUP", 0x100, create=True),
        ):
            self.assertEqual(shell_subprocess_kwargs(), {"creationflags": 0x100})

    def test_shell_subprocess_kwargs_windows_no_flag(self):
        with (
            patch("core.platform_utils.is_windows", return_value=True),
            patch("core.platform_utils.subprocess.CREATE_NEW_PROCESS_GROUP", 0, create=True),
        ):
            self.assertEqual(shell_subprocess_kwargs(), {})

    def test_shell_subprocess_kwargs_unix(self):
        with patch("core.platform_utils.is_windows", return_value=False):
            self.assertEqual(shell_subprocess_kwargs(), {"start_new_session": True})

    def test_shell_env_contains_noninteractive_variables(self):
        env = shell_env()
        self.assertEqual(env.get("CI"), "1")
        self.assertEqual(env.get("DEBIAN_FRONTEND"), "noninteractive")
        self.assertEqual(env.get("FORCE_COLOR"), "0")
        self.assertEqual(env.get("CLI_AUTO_PROMPT"), "0")
        self.assertEqual(env.get("PAGER"), "cat")
        self.assertEqual(env.get("GIT_PAGER"), "cat")
        self.assertEqual(env.get("TERM"), "dumb")
        self.assertEqual(env.get("NO_COLOR"), "1")

    def test_is_image_file(self):
        self.assertTrue(is_image_file("photo.png"))
        self.assertTrue(is_image_file("image.JPG"))
        self.assertTrue(is_image_file("/path/to/graphic.svg"))
        self.assertFalse(is_image_file("document.pdf"))
        self.assertFalse(is_image_file("script.py"))


class TestClipboardRetrieval(unittest.TestCase):
    def test_get_clipboard_image_from_pil(self):
        mock_img = Image.new("RGB", (10, 10))
        with patch("PIL.ImageGrab.grabclipboard", return_value=mock_img):
            file_path, img = get_clipboard_image_or_file()
            self.assertIsNone(file_path)
            self.assertEqual(img, mock_img)

    def test_get_clipboard_file_from_pil(self):
        with (
            patch("PIL.ImageGrab.grabclipboard", return_value=["/tmp/test.png"]),
            patch("os.path.exists", return_value=True),
        ):
            file_path, img = get_clipboard_image_or_file()
            self.assertEqual(file_path, "/tmp/test.png")
            self.assertIsNone(img)

    def test_get_clipboard_str_path_from_pil(self):
        with (
            patch("PIL.ImageGrab.grabclipboard", return_value="/tmp/shot.png"),
            patch("os.path.exists", return_value=True),
            patch("core.platform_utils.is_windows", return_value=True),
        ):
            file_path, img = get_clipboard_image_or_file()
            self.assertEqual(file_path, "/tmp/shot.png")
            self.assertIsNone(img)

    def test_get_clipboard_pil_raises(self):
        with (
            patch("PIL.ImageGrab.grabclipboard", side_effect=RuntimeError("no clipboard")),
            patch("core.platform_utils.is_windows", return_value=True),
        ):
            file_path, img = get_clipboard_image_or_file()
            self.assertIsNone(file_path)
            self.assertIsNone(img)

    def test_get_clipboard_empty_returns_none(self):
        with (
            patch("PIL.ImageGrab.grabclipboard", return_value=None),
            patch("core.platform_utils.is_windows", return_value=True),
        ):
            file_path, img = get_clipboard_image_or_file()
            self.assertIsNone(file_path)
            self.assertIsNone(img)

    def test_get_clipboard_macos_jxa_file(self):
        tmp_dir = tempfile.mkdtemp()
        res = subprocess.CompletedProcess([], 0, stdout="FILE:/tmp/clip.png\n")
        with (
            patch("core.config.TEMP_IMAGES_DIR", tmp_dir),
            patch("core.platform_utils.is_windows", return_value=False),
            patch("core.platform_utils.shutil.which", return_value="/usr/bin/osascript"),
            patch("core.platform_utils.subprocess.run", return_value=res),
        ):
            file_path, img = get_clipboard_image_or_file()
            self.assertEqual(file_path, "/tmp/clip.png")
            self.assertIsNone(img)

    def test_get_clipboard_macos_jxa_data(self):
        tmp_dir = tempfile.mkdtemp()
        clip_file = os.path.join(tmp_dir, "raw_clip_12345.tmp")
        Image.new("RGB", (4, 4), "red").save(clip_file, format="PNG")
        res = subprocess.CompletedProcess([], 0, stdout="DATA\n")
        with (
            patch("core.config.TEMP_IMAGES_DIR", tmp_dir),
            patch("os.getpid", return_value=12345),
            patch("core.platform_utils.is_windows", return_value=False),
            patch("core.platform_utils.shutil.which", return_value="/usr/bin/osascript"),
            patch("core.platform_utils.subprocess.run", return_value=res),
        ):
            file_path, img = get_clipboard_image_or_file()
            self.assertIsNone(file_path)
            self.assertIsInstance(img, Image.Image)
        self.assertFalse(os.path.exists(clip_file))

    def test_get_clipboard_macos_jxa_remove_fails(self):
        tmp_dir = tempfile.mkdtemp()
        clip_file = os.path.join(tmp_dir, "raw_clip_999.tmp")
        Image.new("RGB", (2, 2)).save(clip_file, format="PNG")
        res = subprocess.CompletedProcess([], 0, stdout="DATA\n")
        with (
            patch("core.config.TEMP_IMAGES_DIR", tmp_dir),
            patch("os.getpid", return_value=999),
            patch("core.platform_utils.is_windows", return_value=False),
            patch("core.platform_utils.shutil.which", return_value="/usr/bin/osascript"),
            patch("core.platform_utils.subprocess.run", return_value=res),
            patch("os.remove", side_effect=OSError("locked")),
        ):
            file_path, img = get_clipboard_image_or_file()
            self.assertIsNone(file_path)
            self.assertIsInstance(img, Image.Image)

    def test_get_clipboard_macos_jxa_raises(self):
        tmp_dir = tempfile.mkdtemp()
        with (
            patch("core.config.TEMP_IMAGES_DIR", tmp_dir),
            patch("core.platform_utils.is_windows", return_value=False),
            patch("core.platform_utils.shutil.which", return_value="/usr/bin/osascript"),
            patch("core.platform_utils.subprocess.run", side_effect=OSError("osascript failed")),
        ):
            file_path, img = get_clipboard_image_or_file()
            self.assertIsNone(file_path)
            self.assertIsNone(img)

    def test_get_clipboard_macos_empty_result_falls_to_linux(self):
        tmp_dir = tempfile.mkdtemp()
        res = subprocess.CompletedProcess([], 0, stdout="")
        with (
            patch("core.config.TEMP_IMAGES_DIR", tmp_dir),
            patch("core.platform_utils.is_windows", return_value=False),
            patch(
                "core.platform_utils.shutil.which",
                side_effect=lambda name: "/usr/bin/osascript" if name == "osascript" else None,
            ),
            patch("core.platform_utils.subprocess.run", return_value=res),
        ):
            file_path, img = get_clipboard_image_or_file()
            self.assertIsNone(file_path)
            self.assertIsNone(img)

    def test_get_clipboard_linux_wl_paste(self):
        mock_img = MagicMock()
        res = subprocess.CompletedProcess([], 0, stdout=b"png-bytes")
        with (
            patch("PIL.Image.open", return_value=mock_img),
            patch("core.platform_utils.is_windows", return_value=False),
            patch(
                "core.platform_utils.shutil.which",
                side_effect=lambda name: "/usr/bin/wl-paste" if name == "wl-paste" else None,
            ),
            patch("core.platform_utils.subprocess.run", return_value=res),
        ):
            file_path, img = get_clipboard_image_or_file()
            self.assertIsNone(file_path)
            self.assertIs(img, mock_img)

    def test_get_clipboard_linux_wl_paste_no_output(self):
        res = subprocess.CompletedProcess([], 1, stdout=b"")
        with (
            patch("core.platform_utils.is_windows", return_value=False),
            patch(
                "core.platform_utils.shutil.which",
                side_effect=lambda name: "/usr/bin/wl-paste" if name == "wl-paste" else None,
            ),
            patch("core.platform_utils.subprocess.run", return_value=res),
        ):
            file_path, img = get_clipboard_image_or_file()
            self.assertIsNone(file_path)
            self.assertIsNone(img)

    def test_get_clipboard_linux_xclip(self):
        mock_img = MagicMock()
        res = subprocess.CompletedProcess([], 0, stdout=b"png-bytes")
        with (
            patch("PIL.Image.open", return_value=mock_img),
            patch("core.platform_utils.is_windows", return_value=False),
            patch(
                "core.platform_utils.shutil.which",
                side_effect=lambda name: "/usr/bin/xclip" if name == "xclip" else None,
            ),
            patch("core.platform_utils.subprocess.run", return_value=res),
        ):
            file_path, img = get_clipboard_image_or_file()
            self.assertIsNone(file_path)
            self.assertIs(img, mock_img)


class TestTerminateProcess(unittest.TestCase):
    def test_terminate_process_none(self):
        asyncio.run(terminate_process(None))

    def test_terminate_process_unix_killpg(self):
        process = MagicMock()
        process.pid = 4242
        process.wait = AsyncMock()
        with (
            patch("core.platform_utils.is_windows", return_value=False),
            patch("core.platform_utils.os.killpg") as killpg,
        ):
            asyncio.run(terminate_process(process, timeout=0.5))
        killpg.assert_called_once_with(4242, signal.SIGTERM)
        process.wait.assert_awaited_once()

    def test_terminate_process_unix_no_pid(self):
        process = MagicMock()
        process.pid = None
        process.wait = AsyncMock()
        with patch("core.platform_utils.is_windows", return_value=False):
            asyncio.run(terminate_process(process, timeout=0.5))
        process.terminate.assert_called_once()

    def test_terminate_process_unix_killpg_fails(self):
        process = MagicMock()
        process.pid = 7
        process.wait = AsyncMock()
        with (
            patch("core.platform_utils.is_windows", return_value=False),
            patch("core.platform_utils.os.killpg", side_effect=OSError("no such process")),
        ):
            asyncio.run(terminate_process(process, timeout=0.5))
        process.terminate.assert_called_once()

    def test_terminate_process_windows(self):
        process = MagicMock()
        process.wait = AsyncMock()
        with patch("core.platform_utils.is_windows", return_value=True):
            asyncio.run(terminate_process(process, timeout=0.5))
        process.terminate.assert_called_once()

    def test_terminate_process_wait_fails_then_kill(self):
        process = MagicMock()
        process.pid = 1
        process.wait = AsyncMock(side_effect=asyncio.TimeoutError)
        with (
            patch("core.platform_utils.is_windows", return_value=False),
            patch("core.platform_utils.os.killpg"),
        ):
            asyncio.run(terminate_process(process, timeout=0.5))
        process.kill.assert_called_once()

    def test_terminate_process_kill_fails(self):
        process = MagicMock()
        process.wait = AsyncMock(side_effect=RuntimeError("wait failed"))
        process.kill.side_effect = OSError("kill failed")
        with patch("core.platform_utils.is_windows", return_value=False):
            asyncio.run(terminate_process(process, timeout=0.5))
        process.kill.assert_called_once()
