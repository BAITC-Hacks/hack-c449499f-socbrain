"""Секреты из интерфейса: шифрование, привязка к хосту, отсутствие утечки через API."""
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app import vault
from app.api.main import app
from app.config import settings

KEY = "nvapi-TEST-secret-value-1234"


class VaultTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="socbrain-vault-"))

    def test_stored_encrypted_and_bound_to_host(self):
        vault.set_secret(self.dir, "NVIDIA_API_KEY", KEY, "https://integrate.api.nvidia.com/v1")
        raw = sqlite3.connect(self.dir / "protocol.db").execute("SELECT value_enc FROM app_secrets").fetchone()[0]
        self.assertNotIn(KEY, raw)
        self.assertEqual(vault.get_secret(self.dir, "NVIDIA_API_KEY", "https://integrate.api.nvidia.com/v1"), KEY)
        # чужой адрес — ключ не отдаётся
        self.assertEqual(vault.get_secret(self.dir, "NVIDIA_API_KEY", "https://evil.example.com/v1"), "")
        if os.name == "posix":
            self.assertEqual((self.dir / ".secrets_key").stat().st_mode & 0o777, 0o600)

    def test_env_is_fallback(self):
        os.environ["SED_API_KEY"] = "from-env"
        try:
            self.assertEqual(vault.get_secret(self.dir, "SED_API_KEY"), "from-env")
            vault.set_secret(self.dir, "SED_API_KEY", "from-ui", None)
            self.assertEqual(vault.get_secret(self.dir, "SED_API_KEY"), "from-ui")
            vault.clear_secret(self.dir, "SED_API_KEY")
            self.assertEqual(vault.get_secret(self.dir, "SED_API_KEY"), "from-env")
        finally:
            del os.environ["SED_API_KEY"]


class SecretsApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old_dir = settings.data_dir
        settings.data_dir = Path(tempfile.mkdtemp(prefix="socbrain-secapi-"))
        cls.client = TestClient(app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        settings.data_dir = cls.old_dir
        settings.reload()

    def test_put_key_never_returned_and_used_by_llm(self):
        self.client.put("/api/settings/llm", json={"provider": "nvidia", "base_url": ""})
        r = self.client.put("/api/secrets/NVIDIA_API_KEY", json={"value": KEY})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["status"]["hint"], "…1234")
        for path in ("/api/settings", "/api/llm/providers", "/api/config"):
            self.assertNotIn(KEY, self.client.get(path).text, path)
        self.assertEqual(settings.llm_api_key, KEY)
        # адрес увели на чужой сервер — ключ не используется
        self.client.put("/api/settings/llm", json={"base_url": "https://evil.example.com/v1"})
        self.assertEqual(settings.llm_api_key, "")
        self.client.put("/api/settings/llm", json={"base_url": ""})
        self.assertEqual(settings.llm_api_key, KEY)
        self.client.delete("/api/secrets/NVIDIA_API_KEY")
        self.assertEqual(settings.llm_api_key, os.getenv("NVIDIA_API_KEY", ""))

    def test_unknown_and_invalid(self):
        self.assertEqual(self.client.put("/api/secrets/PATH", json={"value": "x"}).status_code, 404)
        self.assertEqual(self.client.put("/api/secrets/NVIDIA_API_KEY", json={"value": " "}).status_code, 400)
        self.assertEqual(self.client.put("/api/secrets/SMTP_PASSWORD", json={"value": "p"}).status_code, 400)


if __name__ == "__main__":
    unittest.main()
