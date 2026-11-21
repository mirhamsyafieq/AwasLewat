"""Test tabel kepadatan."""

from pathlib import Path

from backend.routing.crowd import CrowdConfig, crowd_multiplier, load_crowd_config
from backend.routing.models import DRIVE, WALK

FIXTURE = Path(__file__).parent / "fixtures" / "crowd.json"
PEAK_HOUR = 7
OFF_PEAK_HOUR = 11


def test_default_peak_and_off_peak() -> None:
    config = CrowdConfig()
    assert crowd_multiplier(config, "KRL-X:0", "krl", PEAK_HOUR) == 2.0
    assert crowd_multiplier(config, "KRL-X:0", "krl", OFF_PEAK_HOUR) == 1.0
    assert crowd_multiplier(config, "TJ-1:0", "brt", PEAK_HOUR) == 1.8


def test_walking_and_driving_are_neutral() -> None:
    config = CrowdConfig()
    assert crowd_multiplier(config, None, WALK, PEAK_HOUR) == 1.0
    assert crowd_multiplier(config, None, DRIVE, PEAK_HOUR) == 1.0


def test_route_override_wins_over_mode() -> None:
    config = load_crowd_config(FIXTURE)
    # Override hanya untuk arah :0; arah :1 memakai angka per moda.
    assert crowd_multiplier(config, "KRL-BOGOR:0", "krl", PEAK_HOUR) == 2.5
    assert crowd_multiplier(config, "KRL-BOGOR:0", "krl", OFF_PEAK_HOUR) == 1.2
    assert crowd_multiplier(config, "KRL-BOGOR:1", "krl", PEAK_HOUR) == 2.0


def test_loaded_config_matches_defaults_except_overrides() -> None:
    loaded = load_crowd_config(FIXTURE)
    default = CrowdConfig()
    assert loaded.peak_hours == default.peak_hours
    assert loaded.peak_by_mode == default.peak_by_mode
    assert loaded.off_peak_by_mode == default.off_peak_by_mode
