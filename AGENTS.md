# AGENTS.md

Guidance for AI coding agents working on this repository.

## Project Overview

StreamController plugin (`me_tysmith_LgMonitorControls`) that controls LG monitor inputs, PBP mode, brightness, and volume via ddcutil DDC/CI from an Elgato Stream Deck. Built for [StreamController](https://github.com/StreamController/StreamController) which runs as a Flatpak.

## Architecture

```
main.py                 # PluginBase — registers actions, plugin-level settings UI
ddcutil.py              # Shared ddcutil helper — subprocess wrapper, VCP constants, I2C lock, LG detection
monitor_profile.py      # TOML profile loader — configures VCP codes per monitor model
action_base.py          # MonitorActionMixin — thread-safe polling with exponential backoff
icons.py                # Icon tinting utilities for active/inactive state display
actions/
  slider_base.py        # SliderAction base for numeric cycling actions (5 actions inherit this)
  InputSwitch/          # Switch monitor input (DP, USB-C, HDMI1, HDMI2)
  PbpMode/              # PBP 50/50 split with left/right input selection
  Brightness/           # Brightness cycling (key-press step + dial)
  Volume/               # Volume cycling + mute toggle (key-press step + dial)
  Contrast/             # Contrast cycling (key-press step + dial)
  Sharpness/            # Sharpness cycling — LG-specific (key-press step + dial)
  BlackStabilizer/      # Black stabilizer cycling — LG-specific (key-press step + dial)
  PowerMode/            # Toggle on/standby
monitors/               # TOML monitor profiles (VCP codes per model)
locales/en_US.json      # All user-facing strings (locale keys)
manifest.json           # StreamController plugin metadata (id, version, author, app-version)
assets/                 # 72x72 action icons
store/Thumbnail.png     # 256x256 store thumbnail
pyproject.toml          # Project metadata, dev dependencies (uv), ruff and pyright config
```

## Key Constraints

- **Flatpak sandbox**: All subprocess calls to the host must use `flatpak-spawn --host`. The `_host_prefix()` helper in `ddcutil.py` handles this automatically. Never call host binaries directly.
- **StreamController imports**: `src.backend.*` and `GtkHelper.*` imports only resolve inside the StreamController Flatpak runtime. LSP errors on these are expected and unavoidable during local development.
- **GTK4/Adwaita**: UI uses `gi.repository.Adw` and `gi.repository.Gtk` (version 4.0). These come from the Flatpak runtime, not pip.
- **`__pycache__` must be cleared** after code changes for StreamController to pick them up on restart. The plugin is symlinked from `~/.var/app/com.core447.StreamController/data/plugins/me_tysmith_LgMonitorControls`.
- **`set_media()` is overridden by user custom assets** — if a user sets an icon via the sidebar icon selector, all `set_media()` calls are silently ignored.
- **I2C bus serialization**: All ddcutil calls go through a module-level `threading.Lock` in `ddcutil.py` to prevent concurrent I2C access from multiple actions.

## Plugin API Patterns

- **Plugin-level settings**: Override `get_settings_area()` on PluginBase, return `Adw.PreferencesGroup`. Uses `self.get_settings()`/`self.set_settings()` on PluginBase.
- **Per-action settings**: Override `get_config_rows()` on ActionBase, return list of `Adw.PreferencesRow`. Uses `self.get_settings()`/`self.set_settings()` on the action instance.
- **Events**: Override `event_callback(self, event, data)`. Use `Input.Key.Events.SHORT_UP` for short press and `Input.Key.Events.HOLD_START` for long press. These are mutually exclusive.
- **Color pickers**: `from GtkHelper.GenerativeUI.ColorButtonRow import ColorButtonRow` — auto-persists to action settings. RGBA tuples use 0-255 range.
- **`Adw.EntryRow`** does not support subtitles — title doubles as placeholder.

## Development

Uses [uv](https://docs.astral.sh/uv/) for dependency management. Dev dependencies and tool config are in `pyproject.toml`.

```bash
# Install dev dependencies and activate venv (direnv does this automatically)
uv sync
source .venv/bin/activate

# Type check (strict mode on ddcutil.py only)
uv run pyright

# Lint
uv run ruff check .
uv run ruff format --check .

# Test
uv run pytest tests/ -v

# Clear cache after changes
find . -type d -name __pycache__ -exec rm -rf {} +
```

## Type System

- `ddcutil.py` is checked with **pyright strict** mode — all functions are fully annotated
- `Display` and `VcpValue` TypedDicts define the shapes returned by helper functions
- `main.py` and `actions/` are excluded from type checking (depend on Flatpak-only imports)
- `tests/` are excluded from pyright (mock parameters don't type well) — validated by pytest + ruff instead

## Locale Strings

All user-facing text must go through locale keys in `locales/en_US.json`, accessed via `self.plugin_base.lm.get("key.name")`. Add new keys there before referencing them in code.

## ddcutil Details

- **LG sidechannel (DDC2AB)**: LG monitors use `--i2c-source-addr=x50` for input switching (VCP 0xF4) and `--i2c-source-addr=x51` for PBP control (VCP 0xD7)
- **LG detection**: `detect_displays()` parses `ddcutil detect` output; `mfg_id == "GSM"` indicates LG Electronics
- **Standard VCP**: Brightness (0x10), Volume (0x62), Mute (0x8D) work on any DDC/CI monitor
- **PBP sequence**: left input → enable PBP → right input (3 separate setvcp calls)

## Versioning

- **Two places**: `manifest.json` `"version"` field (StreamController) and `pyproject.toml` `version` field — keep them in sync
- `main.py` reads version from `manifest.json` at import time — never hardcode it

## Design Decisions

- Display number `0` in per-action settings means "use plugin default"
- Short press cycles values; long press (`HOLD_START`) does a special action (full brightness, mute toggle)
- `on_tick()` polls every 5 seconds to update key display with current monitor state
- LG input getvcp via sidechannel may be unreliable — InputSwitch treats it as fire-and-forget
