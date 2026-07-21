import unittest

from tools.read import ReadTool
from tools.view_image import ViewImageTool


class TestViewImageTool(unittest.IsolatedAsyncioTestCase):

    async def test_view_image_tool(self):
        # Обычный вызов ViewImageTool
        tool = ViewImageTool()
        res = await tool.execute({"path": "tests/test_app.py"})
        self.assertIn("Error:", res)  # test_app.py is not an image

        # Вызов ReadTool на не существующую картинку
        read_tool = ReadTool()
        res_nonexistent = await read_tool.execute({"path": "nonexistent_image.png"})
        self.assertIn("not found", res_nonexistent)


if __name__ == "__main__":
    unittest.main()
