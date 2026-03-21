"""Tests for the monitor profile loader."""

from pathlib import Path

from monitor_profile import (
    MonitorProfile,
    _load_toml,
    get_default,
    get_profile,
)

_MONITORS_DIR = Path(__file__).parent.parent / "monitors"


class TestLoadToml:
    def test_load_lg_profile(self):
        p = _load_toml(_MONITORS_DIR / "lg_ultragear_45gx950a.toml")
        assert p.name == "LG ULTRAGEAR+ 45GX950A"
        assert p.mfg_id == "GSM"
        assert 40605 in p.product_codes
        assert p.inputs.vcp == 0xF4
        assert p.inputs.i2c_source_addr == "x50"
        assert p.inputs.sources["dp"] == 0xD0
        assert p.inputs.sources["usbc"] == 0xD1
        assert p.pbp.vcp == 0xD7
        assert p.pbp.off == 0x01
        assert p.pbp.split_50_50 == 0x05
        assert p.has_pbp is True
        assert p.brightness.vcp == 0x10
        assert p.sharpness.vcp == 0x87
        assert p.has_sharpness is True
        assert p.black_stabilizer.vcp == 0xF9
        assert p.has_black_stabilizer is True

    def test_load_default_profile(self):
        p = _load_toml(_MONITORS_DIR / "default.toml")
        assert p.inputs.vcp == 0x60
        assert p.inputs.i2c_source_addr == ""
        assert p.has_pbp is False
        assert p.has_sharpness is False
        assert p.has_black_stabilizer is False
        assert p.brightness.vcp == 0x10


class TestProfileMatching:
    def test_match_lg_by_mfg_and_product(self):
        p = get_profile("GSM", 40605)
        assert p.mfg_id == "GSM"
        assert p.inputs.vcp == 0xF4

    def test_match_lg_by_mfg_only(self):
        p = get_profile("GSM", 99999)
        assert p.mfg_id == "GSM"

    def test_unknown_mfg_returns_default(self):
        p = get_profile("XYZ", 12345)
        assert p.inputs.vcp == 0x60
        assert p.has_pbp is False

    def test_get_default(self):
        p = get_default()
        assert p.name == "Generic DDC/CI Monitor"


class TestMonitorProfileDefaults:
    def test_empty_profile_has_standard_vcp(self):
        p = MonitorProfile()
        assert p.brightness.vcp == 0x10
        assert p.contrast.vcp == 0x12
        assert p.volume.vcp == 0x62
        assert p.mute.vcp == 0x8D
        assert p.power.vcp == 0xD6
        assert p.has_pbp is False
        assert p.has_sharpness is False
        assert p.has_black_stabilizer is False
