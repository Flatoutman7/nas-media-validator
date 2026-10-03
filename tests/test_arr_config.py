import json

from nas_checker.arr.arr_config import (
    load_arr_config,
    normalize_arr_config,
    save_arr_config,
    validate_arr_service_config,
)


def test_save_and_load_arr_config_persists_enabled_url_and_api_key(tmp_path):
    config_path = tmp_path / "arr_config.json"

    save_arr_config(
        {
            "sonarr": {
                "enabled": True,
                "base_url": "http://localhost:8989/",
                "api_key": "sonarr-key",
            },
            "radarr": {
                "enabled": False,
                "base_url": "http://localhost:7878",
                "api_key": "radarr-key",
            },
        },
        str(config_path),
    )

    loaded = load_arr_config(str(config_path))

    assert loaded == {
        "sonarr": {
            "enabled": True,
            "base_url": "http://localhost:8989",
            "api_key": "sonarr-key",
        },
        "radarr": {
            "enabled": False,
            "base_url": "http://localhost:7878",
            "api_key": "radarr-key",
        },
    }


def test_normalize_arr_config_defaults_missing_services_to_disabled():
    normalized = normalize_arr_config({"sonarr": {"base_url": " http://sonarr:8989/ "}})

    assert normalized["sonarr"] == {
        "enabled": False,
        "base_url": "http://sonarr:8989",
        "api_key": "",
    }
    assert normalized["radarr"] == {
        "enabled": False,
        "base_url": "",
        "api_key": "",
    }


def test_validate_arr_service_config_requires_enabled_url_and_api_key():
    errors = validate_arr_service_config(
        "sonarr",
        {"enabled": True, "base_url": "localhost:8989", "api_key": ""},
    )

    assert "Sonarr base URL must start with http:// or https://." in errors
    assert "Sonarr API key is required." in errors


def test_arr_config_is_written_as_json_object(tmp_path):
    config_path = tmp_path / "arr_config.json"

    save_arr_config({"sonarr": {"enabled": True}}, str(config_path))
    payload = json.loads(config_path.read_text(encoding="utf-8"))

    assert set(payload) == {"sonarr", "radarr"}
    assert payload["sonarr"]["enabled"] is True
    assert payload["radarr"]["enabled"] is False
