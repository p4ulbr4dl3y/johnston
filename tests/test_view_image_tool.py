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
        catalog._vision.append("test-vision-model")
        self.assertTrue(catalog.supports_vision("custom", "test-vision-model"))
        self.assertFalse(catalog.supports_vision("custom", "text-only-model-v1"))

    async def test_fallback_vision_analysis(self):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4")
            temp_path = f.name

        try:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "choices": [{"message": {"content": "This is a 1x1 PNG image."}}]
            }

            with patch("httpx.AsyncClient.post", return_value=mock_resp):
                res = await analyze_image_with_fallback(temp_path, "Describe")
                self.assertIn("Vision Sub-Agent Analysis", res)
                self.assertIn("1x1 PNG image", res)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)


if __name__ == "__main__":
    unittest.main()

