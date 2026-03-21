"""Tests for the ddcutil helper module."""

from unittest.mock import patch, MagicMock
import subprocess

from ddcutil import (
    _DISPLAY_RE,
    _GETVCP_RE,
    _GETVCP_SL_RE,
    detect_displays,
    getvcp,
    setvcp,
    is_lg,
    switch_input,
    set_pbp,
    disable_pbp,
    get_brightness,
    set_brightness,
    get_volume,
    set_volume,
    get_mute,
    set_mute,
    shutdown,
    VCP_BRIGHTNESS,
    VCP_VOLUME,
    VCP_MUTE,
    LG_INPUT_DP,
    LG_INPUT_USBC,
)
from monitor_profile import MonitorProfile, InputConfig, PbpConfig

_LG_PROFILE = MonitorProfile(
    name="LG Test",
    mfg_id="GSM",
    inputs=InputConfig(vcp=0xF4, i2c_source_addr="x50"),
    pbp=PbpConfig(vcp=0xD7, i2c_source_addr="x51", off=0x01, split_50_50=0x05),
)

_DEFAULT_PROFILE = MonitorProfile()


DETECT_OUTPUT = """\
Display 1
   I2C bus:  /dev/i2c-3
   DRM connector:           card1-DP-1
   EDID synopsis:
      Mfg id:               GSM - LG Electronics
      Model:                LG ULTRAGEAR+
      Product code:         40605  (0x9e9d)
      Serial number:        ABC123
      Binary serial number: 12345 (0x00003039)
      Manufacture year:     2024,  Week: 10
   VCP version:         2.1

Display 2
   I2C bus:  /dev/i2c-5
   DRM connector:           card1-HDMI-A-1
   EDID synopsis:
      Mfg id:               DEL - Dell Inc.
      Model:                DELL U2723QE
      Product code:         16611  (0x40e3)
      Serial number:        XYZ789
      Binary serial number: 67890 (0x00010932)
      Manufacture year:     2023,  Week: 20
   VCP version:         2.1
"""

GETVCP_BRIGHTNESS_OUTPUT = """\
VCP code 0x10 (Brightness                    ): current value =    75, max value =   100
"""

GETVCP_MFG_OUTPUT = """\
VCP code 0xf4 (Manufacturer Specific         ): mh=0x00, ml=0x01, sh=0x00, sl=0xD0
"""

GETVCP_BARE_SL_OUTPUT = """\
VCP code 0xd6 (Power mode                    ): DPM: On,  DPMS: Off (sl=0x01)
"""


def _mock_run(stdout="", returncode=0):
    """Create a mock CompletedProcess."""
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=""
    )


class TestDetectParsing:
    def test_parse_two_displays(self):
        matches = list(_DISPLAY_RE.finditer(DETECT_OUTPUT))
        assert len(matches) == 2

        assert matches[0].group("num") == "1"
        assert matches[0].group("mfg") == "GSM"
        assert matches[0].group("model").strip() == "LG ULTRAGEAR+"
        assert matches[0].group("code") == "40605"

        assert matches[1].group("num") == "2"
        assert matches[1].group("mfg") == "DEL"
        assert matches[1].group("model").strip() == "DELL U2723QE"
        assert matches[1].group("code") == "16611"

    @patch("ddcutil._run")
    def test_detect_displays(self, mock_run):
        detect_displays.cache_clear()
        mock_run.return_value = _mock_run(DETECT_OUTPUT)

        displays = detect_displays()
        assert len(displays) == 2

        assert displays[0]["display_number"] == 1
        assert displays[0]["mfg_id"] == "GSM"
        assert displays[0]["model"] == "LG ULTRAGEAR+"
        assert displays[0]["product_code"] == 40605
        assert displays[0]["is_lg"] is True

        assert displays[1]["display_number"] == 2
        assert displays[1]["mfg_id"] == "DEL"
        assert displays[1]["is_lg"] is False

        detect_displays.cache_clear()

    @patch("ddcutil._run")
    def test_detect_displays_failure(self, mock_run):
        detect_displays.cache_clear()
        mock_run.return_value = _mock_run(returncode=1)
        assert detect_displays() == []
        detect_displays.cache_clear()

    @patch("ddcutil._run")
    def test_detect_displays_timeout(self, mock_run):
        detect_displays.cache_clear()
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="ddcutil", timeout=10)
        assert detect_displays() == []
        detect_displays.cache_clear()

    @patch("ddcutil._run")
    def test_detect_displays_oserror(self, mock_run):
        detect_displays.cache_clear()
        mock_run.side_effect = OSError("No such file")
        assert detect_displays() == []
        detect_displays.cache_clear()


class TestGetvcp:
    def test_parse_brightness_output(self):
        m = _GETVCP_RE.search(GETVCP_BRIGHTNESS_OUTPUT)
        assert m is not None
        assert m.group(1) == "75"
        assert m.group(2) == "100"

    def test_parse_mfg_output(self):
        from ddcutil import _GETVCP_MFG_RE

        m = _GETVCP_MFG_RE.search(GETVCP_MFG_OUTPUT)
        assert m is not None
        assert int(m.group(4), 16) == 0xD0  # sl
        assert int(m.group(2), 16) == 0x01  # ml

    def test_parse_bare_sl_output(self):
        m = _GETVCP_SL_RE.search(GETVCP_BARE_SL_OUTPUT)
        assert m is not None
        assert int(m.group(1), 16) == 0x01

    @patch("ddcutil._run")
    def test_getvcp_bare_sl(self, mock_run):
        mock_run.return_value = _mock_run(GETVCP_BARE_SL_OUTPUT)
        result = getvcp(1, 0xD6)
        assert result is not None
        assert result["current"] == 1
        assert result["max"] == 0

    @patch("ddcutil._run")
    def test_getvcp_brightness(self, mock_run):
        mock_run.return_value = _mock_run(GETVCP_BRIGHTNESS_OUTPUT)
        result = getvcp(1, VCP_BRIGHTNESS)
        assert result is not None
        assert result["current"] == 75
        assert result["max"] == 100

    @patch("ddcutil._run")
    def test_getvcp_lg_sidechannel(self, mock_run):
        mock_run.return_value = _mock_run(GETVCP_MFG_OUTPUT)
        result = getvcp(1, 0xF4, src_addr="x50")
        assert result is not None
        assert result["current"] == 0xD0
        assert result["max"] == 1  # ml=0x01 from mh/ml/sh/sl format

    @patch("ddcutil._run")
    def test_getvcp_failure(self, mock_run):
        mock_run.return_value = _mock_run(returncode=1)
        assert getvcp(1, VCP_BRIGHTNESS) is None

    @patch("ddcutil._run")
    def test_getvcp_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="ddcutil", timeout=3)
        assert getvcp(1, VCP_BRIGHTNESS) is None

    @patch("ddcutil._run")
    def test_getvcp_unparseable(self, mock_run):
        mock_run.return_value = _mock_run("some garbage output")
        assert getvcp(1, VCP_BRIGHTNESS) is None

    @patch("ddcutil._run")
    def test_getvcp_src_addr_in_args(self, mock_run):
        mock_run.return_value = _mock_run(GETVCP_MFG_OUTPUT)
        getvcp(1, 0xF4, src_addr="x50")
        args = mock_run.call_args[0][0]
        assert "--i2c-source-addr=x50" in args


class TestSetvcp:
    @patch("ddcutil._run")
    def test_setvcp_success(self, mock_run):
        mock_run.return_value = _mock_run()
        assert setvcp(1, VCP_BRIGHTNESS, 50) is True

    @patch("ddcutil._run")
    def test_setvcp_args(self, mock_run):
        mock_run.return_value = _mock_run()
        setvcp(1, 0xF4, 0xD0, src_addr="x50")
        args = mock_run.call_args[0][0]
        assert "-d" in args
        assert "1" in args
        assert "setvcp" in args
        assert "0xF4" in args
        assert "208" in args  # 0xD0 = 208
        assert "--i2c-source-addr=x50" in args
        assert "--noverify" in args

    @patch("ddcutil._run")
    def test_setvcp_failure(self, mock_run):
        mock_run.return_value = _mock_run(returncode=1)
        assert setvcp(1, VCP_BRIGHTNESS, 50) is False

    @patch("ddcutil._run")
    def test_setvcp_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="ddcutil", timeout=3)
        assert setvcp(1, VCP_BRIGHTNESS, 50) is False


class TestIsLg:
    @patch("ddcutil.detect_displays")
    def test_is_lg_true(self, mock_detect):
        mock_detect.return_value = [
            {
                "display_number": 1,
                "mfg_id": "GSM",
                "model": "LG",
                "product_code": 1,
                "is_lg": True,
            }
        ]
        assert is_lg(1) is True

    @patch("ddcutil.detect_displays")
    def test_is_lg_false(self, mock_detect):
        mock_detect.return_value = [
            {
                "display_number": 2,
                "mfg_id": "DEL",
                "model": "Dell",
                "product_code": 2,
                "is_lg": False,
            }
        ]
        assert is_lg(2) is False

    @patch("ddcutil.detect_displays")
    def test_is_lg_unknown_display(self, mock_detect):
        mock_detect.return_value = []
        assert is_lg(99) is False


class TestSwitchInput:
    @patch("ddcutil.profile_for")
    @patch("ddcutil.setvcp")
    def test_switch_input_lg(self, mock_setvcp, mock_profile):
        mock_profile.return_value = _LG_PROFILE
        mock_setvcp.return_value = True
        assert switch_input(1, LG_INPUT_DP) is True
        mock_setvcp.assert_called_once_with(1, 0xF4, LG_INPUT_DP, "", src_addr="x50")

    @patch("ddcutil.profile_for")
    @patch("ddcutil.setvcp")
    def test_switch_input_non_lg(self, mock_setvcp, mock_profile):
        mock_profile.return_value = _DEFAULT_PROFILE
        mock_setvcp.return_value = True
        assert switch_input(2, LG_INPUT_DP) is True
        mock_setvcp.assert_called_once_with(2, 0x60, LG_INPUT_DP, "", src_addr="")


class TestPbp:
    @patch("ddcutil.profile_for")
    @patch("ddcutil.setvcp")
    def test_set_pbp(self, mock_setvcp, mock_profile):
        mock_profile.return_value = _LG_PROFILE
        mock_setvcp.return_value = True
        assert set_pbp(1, LG_INPUT_DP, LG_INPUT_USBC) is True
        assert mock_setvcp.call_count == 3
        calls = mock_setvcp.call_args_list
        # Step 1: left input
        assert calls[0] == (
            (1, 0xF4, LG_INPUT_DP, ""),
            {"src_addr": "x50"},
        )
        # Step 2: enable PBP
        assert calls[1] == (
            (1, 0xD7, 0x05, ""),
            {"src_addr": "x51"},
        )
        # Step 3: right input
        assert calls[2] == (
            (1, 0xF4, LG_INPUT_USBC, ""),
            {"src_addr": "x50"},
        )

    @patch("ddcutil.profile_for")
    @patch("ddcutil.setvcp")
    def test_set_pbp_fails_on_first_step(self, mock_setvcp, mock_profile):
        mock_profile.return_value = _LG_PROFILE
        mock_setvcp.return_value = False
        assert set_pbp(1, LG_INPUT_DP, LG_INPUT_USBC) is False
        assert mock_setvcp.call_count == 1

    @patch("ddcutil.profile_for")
    @patch("ddcutil.setvcp")
    def test_disable_pbp(self, mock_setvcp, mock_profile):
        mock_profile.return_value = _LG_PROFILE
        mock_setvcp.return_value = True
        assert disable_pbp(1) is True
        mock_setvcp.assert_called_once_with(1, 0xD7, 0x01, "", src_addr="x51")

    @patch("ddcutil.profile_for")
    @patch("ddcutil.setvcp")
    def test_set_pbp_no_support(self, mock_setvcp, mock_profile):
        mock_profile.return_value = _DEFAULT_PROFILE
        assert set_pbp(1, LG_INPUT_DP, LG_INPUT_USBC) is False
        mock_setvcp.assert_not_called()


class TestBrightnessVolume:
    @patch("ddcutil.profile_for")
    @patch("ddcutil.getvcp")
    def test_get_brightness(self, mock_getvcp, mock_profile):
        mock_profile.return_value = _DEFAULT_PROFILE
        mock_getvcp.return_value = {"current": 75, "max": 100}
        result = get_brightness(1)
        assert result == {"current": 75, "max": 100}
        mock_getvcp.assert_called_once_with(1, VCP_BRIGHTNESS, "")

    @patch("ddcutil.profile_for")
    @patch("ddcutil.setvcp")
    def test_set_brightness(self, mock_setvcp, mock_profile):
        mock_profile.return_value = _DEFAULT_PROFILE
        mock_setvcp.return_value = True
        assert set_brightness(1, 50) is True
        mock_setvcp.assert_called_once_with(1, VCP_BRIGHTNESS, 50, "")

    @patch("ddcutil.profile_for")
    @patch("ddcutil.getvcp")
    def test_get_volume(self, mock_getvcp, mock_profile):
        mock_profile.return_value = _DEFAULT_PROFILE
        mock_getvcp.return_value = {"current": 30, "max": 100}
        result = get_volume(1)
        assert result == {"current": 30, "max": 100}

    @patch("ddcutil.profile_for")
    @patch("ddcutil.setvcp")
    def test_set_volume(self, mock_setvcp, mock_profile):
        mock_profile.return_value = _DEFAULT_PROFILE
        mock_setvcp.return_value = True
        assert set_volume(1, 60) is True
        mock_setvcp.assert_called_once_with(1, VCP_VOLUME, 60, "")

    @patch("ddcutil.profile_for")
    @patch("ddcutil.getvcp")
    def test_get_mute(self, mock_getvcp, mock_profile):
        mock_profile.return_value = _DEFAULT_PROFILE
        mock_getvcp.return_value = {"current": 1, "max": 0}
        result = get_mute(1)
        assert result == {"current": 1, "max": 0}

    @patch("ddcutil.profile_for")
    @patch("ddcutil.setvcp")
    def test_set_mute_on(self, mock_setvcp, mock_profile):
        mock_profile.return_value = _DEFAULT_PROFILE
        mock_setvcp.return_value = True
        assert set_mute(1, True) is True
        mock_setvcp.assert_called_once_with(1, VCP_MUTE, 1, "")

    @patch("ddcutil.profile_for")
    @patch("ddcutil.setvcp")
    def test_set_mute_off(self, mock_setvcp, mock_profile):
        mock_profile.return_value = _DEFAULT_PROFILE
        mock_setvcp.return_value = True
        assert set_mute(1, False) is True
        mock_setvcp.assert_called_once_with(1, VCP_MUTE, 2, "")


class TestShutdown:
    def setup_method(self):
        """Reset shutdown state between tests."""
        import ddcutil

        ddcutil._shutting_down = False
        ddcutil._current_process = None

    def test_shutdown_sets_flag(self):
        import ddcutil

        shutdown()
        assert ddcutil._shutting_down is True

    @patch("ddcutil._run")
    def test_run_returns_failure_after_shutdown(self, mock_run):
        shutdown()
        assert getvcp(1, VCP_BRIGHTNESS) is None
        assert setvcp(1, VCP_BRIGHTNESS, 50) is False

    def test_shutdown_kills_current_process(self):
        """Verify shutdown kills a tracked subprocess."""
        import ddcutil

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # still running
        ddcutil._current_process = mock_proc
        shutdown()
        mock_proc.kill.assert_called_once()
