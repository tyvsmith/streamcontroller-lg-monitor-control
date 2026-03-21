"""Shared helpers for interacting with ddcutil from inside the flatpak sandbox."""

from __future__ import annotations

import functools
import re
import subprocess
import threading
from pathlib import Path
from typing import TypedDict

try:
    from .monitor_profile import MonitorProfile, get_default, get_profile
except ImportError:
    from monitor_profile import MonitorProfile, get_default, get_profile

# Default binary name (searched in PATH)
DEFAULT_BIN: str = "ddcutil"

# Cache immutable runtime values
_IN_FLATPAK: bool = Path("/.flatpak-info").is_file()
_HOME_DIR: Path = Path.home()
_HOST_PREFIX: list[str] = ["flatpak-spawn", "--host"] if _IN_FLATPAK else []

# Serialize all I2C bus access — prevents concurrent ddcutil calls from colliding
_lock: threading.Lock = threading.Lock()

# --- VCP constants (kept for action code and tests) ---

VCP_LG_INPUT: int = 0xF4
VCP_LG_PBP: int = 0xD7
VCP_INPUT: int = 0x60
VCP_BRIGHTNESS: int = 0x10
VCP_CONTRAST: int = 0x12
VCP_VOLUME: int = 0x62
VCP_MUTE: int = 0x8D
VCP_SHARPNESS: int = 0x87
VCP_BLACK_STABILIZER: int = 0xF9
VCP_POWER: int = 0xD6

# --- Legacy constants (kept for backward compatibility with action code) ---

LG_INPUT_DP: int = 0xD0
LG_INPUT_USBC: int = 0xD1
LG_INPUT_HDMI1: int = 0x90
LG_INPUT_HDMI2: int = 0x91

PBP_NONE: int = 0x01
PBP_LR_50_50: int = 0x05

POWER_ON: int = 0x01
POWER_STANDBY: int = 0x04
POWER_OFF: int = 0x05

INPUT_NAMES: dict[int, str] = {
    LG_INPUT_DP: "DP",
    LG_INPUT_USBC: "USB-C",
    LG_INPUT_HDMI1: "HDMI 1",
    LG_INPUT_HDMI2: "HDMI 2",
    # Standard MCCS values
    0x0F: "DP",
    0x11: "HDMI 1",
    0x12: "HDMI 2",
}


class Display(TypedDict):
    """A parsed ddcutil display entry."""

    display_number: int
    mfg_id: str
    model: str
    product_code: int
    is_lg: bool


class VcpValue(TypedDict):
    """A parsed VCP feature value."""

    current: int
    max: int


def _run(args: list[str], timeout: float = 3.0) -> subprocess.CompletedProcess[str]:
    """Run a host command with the I2C lock held."""
    with _lock:
        return subprocess.run(
            _HOST_PREFIX + args,
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            start_new_session=True,
            cwd=_HOME_DIR,
        )


def _bin(bin_path: str = "") -> str:
    """Return the ddcutil binary path."""
    return bin_path.strip() or DEFAULT_BIN


# --- Display detection ---

_DISPLAY_RE: re.Pattern[str] = re.compile(
    r"Display\s+(?P<num>\d+)\s*\n"
    r"(?:.*?\n)*?"
    r"\s+Mfg id:\s+(?P<mfg>\w+)"
    r"(?:.*?\n)*?"
    r"\s+Model:\s+(?P<model>[^\n]+)"
    r"(?:.*?\n)*?"
    r"\s+Product code:\s+(?P<code>\d+)",
    re.MULTILINE,
)


@functools.lru_cache(maxsize=1)
def detect_displays(bin_path: str = "") -> list[Display]:
    """Parse output of ``ddcutil detect`` into a list of Display dicts.

    Result is cached — monitors don't change at runtime.
    """
    try:
        result = _run([_bin(bin_path), "detect"], timeout=10.0)
        if result.returncode != 0:
            return []
    except (subprocess.TimeoutExpired, OSError):
        return []

    displays: list[Display] = []
    for m in _DISPLAY_RE.finditer(result.stdout):
        mfg = m.group("mfg")
        displays.append(
            Display(
                display_number=int(m.group("num")),
                mfg_id=mfg,
                model=m.group("model").strip(),
                product_code=int(m.group("code")),
                is_lg=mfg == "GSM",
            )
        )
    return displays


def _find_display(display: int, bin_path: str = "") -> Display | None:
    """Find a display by number."""
    for d in detect_displays(bin_path):
        if d["display_number"] == display:
            return d
    return None


def is_lg(display: int, bin_path: str = "") -> bool:
    """Check if display N is an LG monitor."""
    d = _find_display(display, bin_path)
    return d["is_lg"] if d else False


@functools.lru_cache(maxsize=8)
def profile_for(display: int, bin_path: str = "") -> MonitorProfile:
    """Get the monitor profile for a display number."""
    d = _find_display(display, bin_path)
    if d:
        return get_profile(d["mfg_id"], d["product_code"])
    return get_default()


# --- VCP get/set ---

_GETVCP_RE: re.Pattern[str] = re.compile(
    r"current value\s*=\s*(\d+)(?:.*?max value\s*=\s*(\d+))?"
)

_GETVCP_SL_RE: re.Pattern[str] = re.compile(r"sl=0x([0-9A-Fa-f]+)")

_GETVCP_MFG_RE: re.Pattern[str] = re.compile(
    r"mh=0x([0-9A-Fa-f]+),\s*ml=0x([0-9A-Fa-f]+),"
    r"\s*sh=0x([0-9A-Fa-f]+),\s*sl=0x([0-9A-Fa-f]+)"
)


def getvcp(
    display: int,
    feature: int,
    bin_path: str = "",
    src_addr: str = "",
) -> VcpValue | None:
    """Read a VCP feature value. Returns None on failure."""
    args = [_bin(bin_path), "-d", str(display), "getvcp", f"0x{feature:02X}"]
    if src_addr:
        args.append(f"--i2c-source-addr={src_addr}")
    try:
        result = _run(args)
        if result.returncode != 0:
            return None
    except (subprocess.TimeoutExpired, OSError):
        return None

    # Try standard "current value = X, max value = Y" format first
    m = _GETVCP_RE.search(result.stdout)
    if m:
        return VcpValue(
            current=int(m.group(1)),
            max=int(m.group(2)) if m.group(2) else 0,
        )

    # Try manufacturer-specific "mh=0xNN, ml=0xNN, sh=0xNN, sl=0xNN" format
    m = _GETVCP_MFG_RE.search(result.stdout)
    if m:
        current = (int(m.group(3), 16) << 8) | int(m.group(4), 16)
        max_val = (int(m.group(1), 16) << 8) | int(m.group(2), 16)
        return VcpValue(current=current, max=max_val)

    # Try bare "sl=0xNN" format (fallback for simpler output)
    m = _GETVCP_SL_RE.search(result.stdout)
    if m:
        return VcpValue(current=int(m.group(1), 16), max=0)

    return None


def setvcp(
    display: int,
    feature: int,
    value: int,
    bin_path: str = "",
    src_addr: str = "",
    noverify: bool = True,
) -> bool:
    """Set a VCP feature value. Returns True on success."""
    args = [
        _bin(bin_path),
        "-d",
        str(display),
        "setvcp",
        f"0x{feature:02X}",
        str(value),
    ]
    if src_addr:
        args.append(f"--i2c-source-addr={src_addr}")
    if noverify:
        args.append("--noverify")
    try:
        result = _run(args)
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


# --- High-level operations (profile-driven) ---


def switch_input(display: int, input_code: int, bin_path: str = "") -> bool:
    """Switch monitor input using the appropriate VCP code from the monitor profile."""
    p = profile_for(display, bin_path)
    return setvcp(
        display, p.inputs.vcp, input_code, bin_path, src_addr=p.inputs.i2c_source_addr
    )


def get_input(display: int, bin_path: str = "") -> VcpValue | None:
    """Read current input source. May be unreliable on some monitors."""
    p = profile_for(display, bin_path)
    return getvcp(display, p.inputs.vcp, bin_path, src_addr=p.inputs.i2c_source_addr)


def get_pbp(display: int, bin_path: str = "") -> VcpValue | None:
    """Read PBP mode status."""
    p = profile_for(display, bin_path)
    if not p.has_pbp:
        return None
    return getvcp(display, p.pbp.vcp, bin_path, src_addr=p.pbp.i2c_source_addr)


def set_pbp(display: int, left: int, right: int, bin_path: str = "") -> bool:
    """Enable PBP 50/50 with specified left and right inputs.

    3-step sequence: set left input -> enable PBP -> set right input.
    """
    p = profile_for(display, bin_path)
    if not p.has_pbp:
        return False
    if not setvcp(
        display, p.inputs.vcp, left, bin_path, src_addr=p.inputs.i2c_source_addr
    ):
        return False
    if not setvcp(
        display,
        p.pbp.vcp,
        p.pbp.split_50_50,
        bin_path,
        src_addr=p.pbp.i2c_source_addr,
    ):
        return False
    return setvcp(
        display, p.inputs.vcp, right, bin_path, src_addr=p.inputs.i2c_source_addr
    )


def disable_pbp(display: int, bin_path: str = "") -> bool:
    """Disable PBP mode."""
    p = profile_for(display, bin_path)
    if not p.has_pbp:
        return False
    return setvcp(
        display, p.pbp.vcp, p.pbp.off, bin_path, src_addr=p.pbp.i2c_source_addr
    )


def get_brightness(display: int, bin_path: str = "") -> VcpValue | None:
    """Read current brightness."""
    p = profile_for(display, bin_path)
    return getvcp(display, p.brightness.vcp, bin_path)


def set_brightness(display: int, value: int, bin_path: str = "") -> bool:
    """Set brightness (0-100)."""
    p = profile_for(display, bin_path)
    return setvcp(display, p.brightness.vcp, value, bin_path)


def get_contrast(display: int, bin_path: str = "") -> VcpValue | None:
    """Read current contrast."""
    p = profile_for(display, bin_path)
    return getvcp(display, p.contrast.vcp, bin_path)


def set_contrast(display: int, value: int, bin_path: str = "") -> bool:
    """Set contrast (0-100)."""
    p = profile_for(display, bin_path)
    return setvcp(display, p.contrast.vcp, value, bin_path)


def get_volume(display: int, bin_path: str = "") -> VcpValue | None:
    """Read current volume."""
    p = profile_for(display, bin_path)
    return getvcp(display, p.volume.vcp, bin_path)


def set_volume(display: int, value: int, bin_path: str = "") -> bool:
    """Set volume (0-100)."""
    p = profile_for(display, bin_path)
    return setvcp(display, p.volume.vcp, value, bin_path)


def get_mute(display: int, bin_path: str = "") -> VcpValue | None:
    """Read mute state."""
    p = profile_for(display, bin_path)
    return getvcp(display, p.mute.vcp, bin_path)


def set_mute(display: int, muted: bool, bin_path: str = "") -> bool:
    """Set mute state."""
    p = profile_for(display, bin_path)
    return setvcp(
        display, p.mute.vcp, p.mute.muted if muted else p.mute.unmuted, bin_path
    )


def get_sharpness(display: int, bin_path: str = "") -> VcpValue | None:
    """Read current sharpness."""
    p = profile_for(display, bin_path)
    if not p.has_sharpness:
        return None
    return getvcp(display, p.sharpness.vcp, bin_path)


def set_sharpness(display: int, value: int, bin_path: str = "") -> bool:
    """Set sharpness (0-100)."""
    p = profile_for(display, bin_path)
    if not p.has_sharpness:
        return False
    return setvcp(display, p.sharpness.vcp, value, bin_path)


def get_black_stabilizer(display: int, bin_path: str = "") -> VcpValue | None:
    """Read current black stabilizer value."""
    p = profile_for(display, bin_path)
    if not p.has_black_stabilizer:
        return None
    return getvcp(display, p.black_stabilizer.vcp, bin_path)


def set_black_stabilizer(display: int, value: int, bin_path: str = "") -> bool:
    """Set black stabilizer (0-100)."""
    p = profile_for(display, bin_path)
    if not p.has_black_stabilizer:
        return False
    return setvcp(display, p.black_stabilizer.vcp, value, bin_path)


def get_power(display: int, bin_path: str = "") -> VcpValue | None:
    """Read power mode."""
    p = profile_for(display, bin_path)
    return getvcp(display, p.power.vcp, bin_path)


def set_power(display: int, mode: int, bin_path: str = "") -> bool:
    """Set power mode."""
    p = profile_for(display, bin_path)
    return setvcp(display, p.power.vcp, mode, bin_path)
