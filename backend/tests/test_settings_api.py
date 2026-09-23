"""Настройки из интерфейса: сохранение, проверка значений, перекрытие .env, сброс."""
import os
import tempfile
import unittest

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="socbrain-test-")

from fastapi.testclient import TestClient  # noqa: E402

from app.api.main import app  # noqa: E402
from app.config import settings  # noqa: E402


class SettingsApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        settings.data_dir = type(settings.data_dir)(os.environ["DATA_DIR"])
        cls.client = TestClient(app)
        cls.client.__enter__()  # lifespan: создаёт таблицы

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)

    def test_save_and_apply_appearance(self):
        r = self.client.put("/api/settings/appearance", json={"theme": "dark", "font_scale": "115"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.client.get("/api/config").json()["appearance"]["theme"], "dark")
        data = self.client.get("/api/settings").json()
        self.assertEqual(data["fields"]["appearance"]["theme"]["source"], "интерфейс")

    def test_invalid_value_rejected(self):
        r = self.client.put("/api/settings/appearance", json={"theme": "purple"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("theme", r.json()["detail"]["errors"])

    def test_unknown_field_and_section(self):
        self.assertEqual(self.client.put("/api/settings/appearance", json={"hack": 1}).status_code, 400)
        self.assertEqual(self.client.put("/api/settings/nope", json={}).status_code, 404)

    def test_llm_switch_to_nvidia_and_reset(self):
        self.client.put("/api/settings/llm", json={"provider": "nvidia"})
        self.assertEqual(settings.llm_base_url, "https://integrate.api.nvidia.com/v1")
        self.assertTrue(settings.llm_external)
        self.client.put("/api/settings/llm", json={"provider": "nvidia", "base_url": "http://10.0.0.5:8000/v1"})
        self.assertFalse(settings.llm_external)  # NIM в своей сети
        self.client.put("/api/settings/llm", json={"provider": "", "base_url": ""})
        self.assertEqual(self.client.get("/api/settings").json()["fields"]["llm"]["provider"]["source"] != "интерфейс", True)

    def test_secrets_never_returned(self):
        os.environ["SMTP_PASSWORD"] = "top-secret"
        try:
            body = self.client.get("/api/settings").text
            self.assertNotIn("top-secret", body)
            self.assertTrue(self.client.get("/api/settings").json()["secrets"]["mail"]["SMTP_PASSWORD"])
        finally:
            del os.environ["SMTP_PASSWORD"]


if __name__ == "__main__":
    unittest.main()
