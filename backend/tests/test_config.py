import unittest

from app.config import LLM_PRESETS, is_external_url, settings


class ConfigTest(unittest.TestCase):
    def test_paths_are_settings_properties(self):
        self.assertEqual(settings.db_path.name, "protocol.db")
        self.assertEqual(settings.upload_dir.name, "uploads")
        self.assertEqual(settings.work_dir.name, "work")

    def test_external_is_derived_from_address(self):
        self.assertTrue(is_external_url("https://integrate.api.nvidia.com/v1"))
        self.assertTrue(is_external_url("https://api.openai.com/v1"))
        self.assertFalse(is_external_url("http://ollama:11434/v1"))
        self.assertFalse(is_external_url("http://10.19.26.5:8000/v1"))
        self.assertFalse(is_external_url("http://nim.internal:8000/v1"))

    def test_presets_have_required_fields(self):
        for pid, preset in LLM_PRESETS.items():
            with self.subTest(pid):
                self.assertTrue({"title", "base_url", "key_env", "model", "note"} <= preset.keys())


if __name__ == "__main__":
    unittest.main()
