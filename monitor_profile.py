"""Monitor profile loader — reads TOML profiles to configure VCP codes per monitor model."""

from __future__ import annotations

import logging
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

_PROFILES_DIR: Path = Path(__file__).parent / "monitors"


@dataclass
class InputConfig:
    vcp: int = 0x60
    i2c_source_addr: str = ""
    sources: dict[str, int] = field(default_factory=lambda: {})


@dataclass
class PbpConfig:
    vcp: int = 0
    i2c_source_addr: str = ""
    off: int = 0
    split_50_50: int = 0


@dataclass
class FeatureConfig:
    vcp: int = 0


@dataclass
class MuteConfig:
    vcp: int = 0x8D
    muted: int = 1
    unmuted: int = 2


@dataclass
class PowerConfig:
    vcp: int = 0xD6
    on: int = 0x01
    standby: int = 0x04
    off: int = 0x05


@dataclass
class MonitorProfile:
    name: str = "Generic DDC/CI Monitor"
    mfg_id: str = ""
    product_codes: list[int] = field(default_factory=lambda: [])

    inputs: InputConfig = field(default_factory=InputConfig)
    pbp: PbpConfig = field(default_factory=PbpConfig)
    brightness: FeatureConfig = field(default_factory=lambda: FeatureConfig(vcp=0x10))
    contrast: FeatureConfig = field(default_factory=lambda: FeatureConfig(vcp=0x12))
    volume: FeatureConfig = field(default_factory=lambda: FeatureConfig(vcp=0x62))
    mute: MuteConfig = field(default_factory=MuteConfig)
    sharpness: FeatureConfig = field(default_factory=FeatureConfig)
    black_stabilizer: FeatureConfig = field(default_factory=FeatureConfig)
    power: PowerConfig = field(default_factory=PowerConfig)

    @property
    def has_pbp(self) -> bool:
        return self.pbp.vcp != 0

    @property
    def has_sharpness(self) -> bool:
        return self.sharpness.vcp != 0

    @property
    def has_black_stabilizer(self) -> bool:
        return self.black_stabilizer.vcp != 0


def _load_toml(path: Path) -> MonitorProfile:
    with open(path, "rb") as f:
        data = tomllib.load(f)

    mon = data.get("monitor", {})
    inp = data.get("inputs", {})
    pbp = data.get("pbp", {})
    mute = data.get("mute", {})
    power = data.get("power", {})

    return MonitorProfile(
        name=mon.get("name", "Unknown"),
        mfg_id=mon.get("mfg_id", ""),
        product_codes=mon.get("product_codes", []),
        inputs=InputConfig(
            vcp=inp.get("vcp", 0x60),
            i2c_source_addr=inp.get("i2c_source_addr", ""),
            sources=inp.get("sources", {}),
        ),
        pbp=PbpConfig(
            vcp=pbp.get("vcp", 0),
            i2c_source_addr=pbp.get("i2c_source_addr", ""),
            off=pbp.get("off", 0),
            split_50_50=pbp.get("split_50_50", 0),
        ),
        brightness=FeatureConfig(vcp=data.get("brightness", {}).get("vcp", 0x10)),
        contrast=FeatureConfig(vcp=data.get("contrast", {}).get("vcp", 0x12)),
        volume=FeatureConfig(vcp=data.get("volume", {}).get("vcp", 0x62)),
        mute=MuteConfig(
            vcp=mute.get("vcp", 0x8D),
            muted=mute.get("muted", 1),
            unmuted=mute.get("unmuted", 2),
        ),
        sharpness=FeatureConfig(vcp=data.get("sharpness", {}).get("vcp", 0)),
        black_stabilizer=FeatureConfig(
            vcp=data.get("black_stabilizer", {}).get("vcp", 0)
        ),
        power=PowerConfig(
            vcp=power.get("vcp", 0xD6),
            on=power.get("on", 0x01),
            standby=power.get("standby", 0x04),
            off=power.get("off", 0x05),
        ),
    )


def _load_all_profiles() -> list[MonitorProfile]:
    profiles: list[MonitorProfile] = []
    if not _PROFILES_DIR.is_dir():
        return profiles
    for path in sorted(_PROFILES_DIR.glob("*.toml")):
        if path.name == "default.toml":
            continue
        try:
            profiles.append(_load_toml(path))
        except Exception:
            log.warning("Failed to load monitor profile: %s", path, exc_info=True)
    return profiles


_profiles: list[MonitorProfile] | None = None
_default: MonitorProfile | None = None


def _ensure_loaded() -> None:
    global _profiles, _default
    if _profiles is None:
        _profiles = _load_all_profiles()
        default_path = _PROFILES_DIR / "default.toml"
        if default_path.is_file():
            try:
                _default = _load_toml(default_path)
            except Exception:
                log.warning("Failed to load default profile", exc_info=True)
                _default = MonitorProfile()
        else:
            _default = MonitorProfile()


def get_profile(mfg_id: str, product_code: int = 0) -> MonitorProfile:
    """Match by mfg_id, then narrow by product_code. Falls back to default."""
    _ensure_loaded()
    assert _profiles is not None
    assert _default is not None

    candidates = [p for p in _profiles if p.mfg_id == mfg_id]
    if not candidates:
        return _default

    for p in candidates:
        if p.product_codes and product_code in p.product_codes:
            return p

    return candidates[0]


def get_default() -> MonitorProfile:
    _ensure_loaded()
    assert _default is not None
    return _default
