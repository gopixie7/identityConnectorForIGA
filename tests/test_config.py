"""Tests for configuration loading."""

import json
import os
from pathlib import Path

import pytest
import yaml

from iga_connector.config.config_manager import ConnectorConfig, load_config
from iga_connector.core.exceptions import ConfigurationError


class TestLoadConfig:
    def test_from_dict(self):
        cfg = load_config({"connector_type": "rest", "connection": {"base_url": "http://x"}})
        assert cfg.connector_type == "rest"
        assert cfg.connection["base_url"] == "http://x"

    def test_from_yaml(self, tmp_path: Path):
        data = {
            "connector_type": "scim",
            "connection": {"base_url": "https://scim.example.com"},
        }
        f = tmp_path / "test.yaml"
        f.write_text(yaml.dump(data))
        cfg = load_config(f)
        assert cfg.connector_type == "scim"

    def test_from_json(self, tmp_path: Path):
        data = {
            "connector_type": "rest",
            "connection": {"base_url": "https://api.example.com"},
        }
        f = tmp_path / "test.json"
        f.write_text(json.dumps(data))
        cfg = load_config(f)
        assert cfg.connector_type == "rest"

    def test_env_var_resolution(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("MY_URL", "https://resolved.example.com")
        cfg = load_config({
            "connector_type": "rest",
            "connection": {"base_url": "${MY_URL}"},
        })
        assert cfg.connection["base_url"] == "https://resolved.example.com"

    def test_missing_env_var_raises(self):
        with pytest.raises(ConfigurationError, match="not set"):
            load_config({
                "connector_type": "rest",
                "connection": {"base_url": "${NONEXISTENT_VAR_12345}"},
            })

    def test_missing_file_raises(self):
        with pytest.raises(ConfigurationError, match="not found"):
            load_config("/tmp/does_not_exist_xyz.yaml")
