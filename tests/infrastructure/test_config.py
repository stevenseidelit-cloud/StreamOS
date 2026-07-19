import json
import os
import tempfile
import unittest
from pathlib import Path

from streamos.infrastructure.config import (
    ConfigError,
    SecretValue,
    load_config,
    prepare_directories,
)


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.environment = {"APPDATA": str(self.root)}

    def write(self, name, content):
        path = self.root / name
        path.write_text(content, encoding="utf-8")
        return path

    def test_defaults_are_side_effect_free(self):
        config = load_config(environ=self.environment)
        self.assertEqual(self.root / "StreamOS", config.data_dir)
        self.assertEqual(config.data_dir / "streamos.db", config.database.path)
        self.assertFalse(config.data_dir.exists())

    def test_json_env_and_override_precedence(self):
        json_path = self.write(
            "config.json",
            json.dumps({"twitch": {"client_id": "from_json"}}),
        )
        env_path = self.write("settings.env", "STREAMOS_TWITCH_CLIENT_ID=from_env_file")
        config = load_config(
            json_path=json_path,
            env_path=env_path,
            environ={
                **self.environment,
                "STREAMOS_TWITCH_CLIENT_ID": "from_process",
            },
            overrides={"twitch.client_id": "from_override"},
        )
        self.assertEqual("from_override", config.twitch.client_id)

    def test_env_loading_does_not_mutate_process_environment(self):
        path = self.write("settings.env", "STREAMOS_TWITCH_CLIENT_ID=isolated")
        before = os.environ.get("STREAMOS_TWITCH_CLIENT_ID")
        load_config(env_path=path, environ=self.environment)
        self.assertEqual(before, os.environ.get("STREAMOS_TWITCH_CLIENT_ID"))

    def test_secret_is_redacted(self):
        secret = "never-print-this-token"
        config = load_config(
            environ={
                **self.environment,
                "STREAMOS_TWITCH_ACCESS_TOKEN": secret,
            }
        )
        self.assertNotIn(secret, repr(config))
        self.assertNotIn(secret, repr(config.twitch.access_token))
        self.assertEqual("<redacted>", str(config.twitch.access_token))
        self.assertEqual(secret, config.twitch.access_token.reveal())

    def test_duplicate_and_unknown_json_keys_are_rejected(self):
        duplicate = self.write(
            "duplicate.json",
            '{"twitch":{"client_id":"one","client_id":"two"}}',
        )
        with self.assertRaises(ConfigError):
            load_config(json_path=duplicate, environ=self.environment)
        unknown = self.write("unknown.json", '{"twitch":{"typo":"value"}}')
        with self.assertRaises(ConfigError):
            load_config(json_path=unknown, environ=self.environment)

    def test_non_finite_json_is_rejected(self):
        path = self.write(
            "invalid.json",
            '{"database":{"timeout_seconds":NaN}}',
        )
        with self.assertRaises(ConfigError):
            load_config(json_path=path, environ=self.environment)

    def test_env_interpolation_and_duplicates_are_rejected(self):
        interpolation = self.write(
            "interpolation.env",
            "STREAMOS_DB_PATH=${HOME}/streamos.db",
        )
        with self.assertRaises(ConfigError):
            load_config(env_path=interpolation, environ=self.environment)
        duplicate = self.write(
            "duplicate.env",
            "STREAMOS_DB_PATH=one.db\nSTREAMOS_DB_PATH=two.db",
        )
        with self.assertRaises(ConfigError):
            load_config(env_path=duplicate, environ=self.environment)

    def test_unknown_streamos_environment_key_is_rejected(self):
        with self.assertRaises(ConfigError):
            load_config(
                environ={**self.environment, "STREAMOS_TYPO": "value"}
            )

    def test_database_path_must_stay_inside_data_directory(self):
        with self.assertRaises(ConfigError):
            load_config(
                environ={
                    **self.environment,
                    "STREAMOS_DB_PATH": str(self.root / "outside.db"),
                }
            )

    def test_invalid_client_and_redirect_are_rejected(self):
        with self.assertRaises(ConfigError):
            load_config(
                environ={
                    **self.environment,
                    "STREAMOS_TWITCH_CLIENT_ID": "contains spaces",
                }
            )
        with self.assertRaises(ConfigError):
            load_config(
                environ={
                    **self.environment,
                    "STREAMOS_TWITCH_REDIRECT_URI": "file:///secret",
                }
            )

    def test_explicit_missing_source_is_rejected(self):
        with self.assertRaises(ConfigError):
            load_config(
                json_path=self.root / "missing.json",
                environ=self.environment,
            )

    def test_prepare_directories_is_explicit(self):
        config = load_config(environ=self.environment)
        self.assertFalse(config.data_dir.exists())
        prepare_directories(config)
        self.assertTrue(config.data_dir.is_dir())

    def test_secret_rejects_blank_value_without_leaking(self):
        with self.assertRaises(ConfigError) as raised:
            SecretValue("")
        self.assertNotIn("never-print-this-token", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
