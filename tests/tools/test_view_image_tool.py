import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from tools.read import ReadTool
from tools.view_image import ViewImageTool, analyze_image_with_fallback


class TestViewImageTool(unittest.IsolatedAsyncioTestCase):

    async def test_view_image_tool(self):
        # Standard call to ViewImageTool
        tool = ViewImageTool()
        res = await tool.execute({"path": "tests/test_app.py"})
        self.assertIn("Error:", res)  # test_app.py is not an image

        # Call ReadTool on non-existent image
        read_tool = ReadTool()
        res_nonexistent = await read_tool.execute({"path": "nonexistent_image.png"})
        self.assertIn("not found", res_nonexistent)

    def test_supports_vision(self):
        from core.models_catalog import catalog

        model_id = "test-vision-model"
        try:
            catalog._vision.append(model_id)
            self.assertTrue(catalog.supports_vision("custom", model_id))
            self.assertFalse(catalog.supports_vision("custom", "text-only-model-v1"))
        finally:
            catalog.remove_vision_override(model_id)
            catalog._vision = [m for m in catalog._vision if m != model_id]
            catalog._match_cache.clear()

    async def test_fallback_vision_analysis(self):
        from core.models_catalog import catalog

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4")
            temp_path = f.name

        try:
            old_fallback = catalog.get_fallback_vision_model()
            test_model = "test-fallback-vision-model"
            catalog.set_fallback_vision_model("test-provider", test_model)
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "choices": [{"message": {"content": "This is a 1x1 PNG image."}}]
            }

            providers = {
                "test-provider": {
                    "base_url": "https://example.com/v1",
                    "model": test_model,
                    "api_key": "test-key",
                    "api_type": "openai",
                }
            }
            with patch("core.provider_manager.ProviderManager.load_providers", return_value=providers), patch(
                "httpx.AsyncClient.post", return_value=mock_resp
            ):
                res = await analyze_image_with_fallback(temp_path, "Describe")
                self.assertIn("Vision Analysis", res)
                self.assertIn("1x1 PNG image", res)
        finally:
            catalog.set_fallback_vision_model(*old_fallback)
            catalog.remove_vision_override(test_model)
            if os.path.exists(temp_path):
                os.remove(temp_path)


    def test_set_fallback_vision_on_selection(self):
        from unittest.mock import patch

        from core.models_catalog import catalog
        with patch.object(catalog, "save_cache"):
            catalog.add_vision_override("my-vision-model")
            catalog.set_fallback_vision_model("my-provider", "my-vision-model")
            fb_p, fb_m = catalog.get_fallback_vision_model()
            self.assertEqual(fb_p, "my-provider")
            self.assertEqual(fb_m, "my-vision-model")
            catalog.remove_vision_override("my-vision-model")
            self.assertNotIn("my-vision-model", catalog._user_overrides)
            catalog.set_fallback_vision_model("", "")


class TestProcessAndEncodeImage(unittest.TestCase):
    def test_encode_real_png(self):
        import tempfile

        from PIL import Image

        from tools.view_image import process_and_encode_image

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            temp_path = f.name
        try:
            img = Image.new("RGB", (50, 50), color=(255, 0, 0))
            img.save(temp_path, format="PNG")
            b64_url, mime = process_and_encode_image(temp_path)
            self.assertTrue(b64_url.startswith("data:image/jpeg;base64,"))
            self.assertEqual(mime, "image/jpeg")
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_encode_resizes_large_image(self):
        import tempfile

        from PIL import Image

        from tools.view_image import process_and_encode_image

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            temp_path = f.name
        try:
            img = Image.new("RGB", (3000, 2000), color=(0, 255, 0))
            img.save(temp_path, format="PNG")
            b64_url, mime = process_and_encode_image(temp_path, max_dim=500)
            self.assertTrue(b64_url.startswith("data:image/jpeg;base64,"))
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_encode_fallback_non_image(self):
        import tempfile

        from tools.view_image import process_and_encode_image

        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"not an image at all")
            temp_path = f.name
        try:
            b64_url, mime = process_and_encode_image(temp_path)
            self.assertTrue(b64_url.startswith("data:"))
            self.assertIn("base64,", b64_url)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)


class TestViewImageToolErrors(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_cwd = os.getcwd()
        os.chdir(self.temp_dir.name)

    def tearDown(self):
        os.chdir(self.old_cwd)
        self.temp_dir.cleanup()

    async def test_file_not_found(self):
        tool = ViewImageTool()
        res = await tool.execute({"path": "missing.png"})
        self.assertIn("Error", res)
        self.assertIn("not found", res)

    async def test_unsupported_format(self):
        import tempfile
        tool = ViewImageTool()
        with tempfile.NamedTemporaryFile(suffix=".xyz", delete=False, dir=".") as f:
            f.write(b"binary data")
            temp_path = f.name
        try:
            res = await tool.execute({"path": temp_path})
            self.assertIn("Error", res)
            self.assertIn("not a supported image", res)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    async def test_svg_inspection(self):
        import tempfile
        tool = ViewImageTool()
        svg_content = '<svg xmlns="http://www.w3.org/2000/svg"><rect width="100" height="100"/></svg>'
        with tempfile.NamedTemporaryFile(suffix=".svg", delete=False, mode="w", encoding="utf-8", dir=".") as f:
            f.write(svg_content)
            temp_path = f.name
        try:
            res = await tool.execute({"path": temp_path})
            self.assertIn("[SVG Inspection", res)
            self.assertIn("<svg", res)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    async def test_svg_read_error(self):
        import tempfile
        tool = ViewImageTool()
        with tempfile.NamedTemporaryFile(suffix=".svg", delete=False, dir=".") as f:
            f.write(b"\xff\xfe invalid binary")
            temp_path = f.name
        try:
            res = await tool.execute({"path": temp_path})
            self.assertIn("Error reading SVG file", res)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    async def test_custom_prompt_passed(self):
        import tempfile

        from PIL import Image

        from core.models_catalog import catalog

        tool = ViewImageTool()
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False, dir=".") as f:
            temp_path = f.name
        try:
            old_fallback = catalog.get_fallback_vision_model()
            test_model = "test-custom-prompt-vision-model"
            catalog.set_fallback_vision_model("test-provider", test_model)
            img = Image.new("RGB", (10, 10), color=(0, 0, 255))
            img.save(temp_path, format="PNG")
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"choices": [{"message": {"content": "Blue square"}}]}
            providers = {
                "test-provider": {
                    "base_url": "https://example.com/v1",
                    "model": test_model,
                    "api_key": "test-key",
                    "api_type": "openai",
                }
            }
            with patch("core.provider_manager.ProviderManager.load_providers", return_value=providers), patch(
                "httpx.AsyncClient.post", return_value=mock_resp
            ):
                res = await tool.execute({"path": temp_path, "prompt": "What color is this?"})
                self.assertIn("Vision Analysis", res)
        finally:
            catalog.set_fallback_vision_model(*old_fallback)
            catalog.remove_vision_override(test_model)
            if os.path.exists(temp_path):
                os.remove(temp_path)


if __name__ == "__main__":
    unittest.main()
