# LG Monitor Controls — StreamController Plugin

A [StreamController](https://github.com/StreamController/StreamController) plugin that controls monitor settings via [ddcutil](https://www.ddcutil.com/) DDC/CI from an Elgato Stream Deck.

> **Personal project.** Built for and tested on a single monitor — the **LG 45GX950A (ULTRAGEAR+ 45" OLED)**. It may work on other LG monitors or DDC/CI-compatible displays, but no guarantees. Contributions and monitor profiles welcome.

## Features

| Action | Key Press | Long Press / Dial Press | Dial Turn |
|--------|-----------|------------------------|-----------|
| **Input Switch** | Switch to configured input | — | — |
| **PBP Mode** | Toggle PBP 50/50 split | — | — |
| **Brightness** | Cycle in steps | Set to 100% | Adjust up/down |
| **Volume** | Cycle in steps | Toggle mute | Adjust up/down |
| **Contrast** | Cycle in steps | Reset to 70% | Adjust up/down |
| **Sharpness** | Cycle in steps | Reset to 50% | Adjust up/down |
| **Black Stabilizer** | Cycle in steps | Reset to 50% | Adjust up/down |
| **Power Mode** | Toggle on/standby | — | — |

- Active input and PBP state shown with green/white icon tinting
- All ddcutil calls run in background threads — no UI blocking
- Per-action display number config with plugin-level default
- Dial support for brightness, volume, contrast, sharpness, and black stabilizer

## Requirements

- [StreamController](https://github.com/StreamController/StreamController) (Flatpak)
- [ddcutil](https://www.ddcutil.com/) installed on the host system
- I2C kernel module loaded and permissions configured

### ddcutil setup

1. Install ddcutil (e.g., `sudo pacman -S ddcutil` on Arch, `sudo apt install ddcutil` on Debian/Ubuntu)

2. Load the I2C kernel module:
   ```bash
   sudo modprobe i2c-dev
   ```
   To load on boot, add `i2c-dev` to `/etc/modules-load.d/i2c.conf`.

3. Grant your user access to the I2C bus:
   ```bash
   sudo usermod -aG i2c $USER
   ```
   Log out and back in for the group change to take effect.

4. Verify ddcutil can see your monitor:
   ```bash
   ddcutil detect
   ddcutil getvcp 0x10   # should return brightness value
   ```

See the [ddcutil documentation](https://www.ddcutil.com/config/) for troubleshooting.

## Installation

### From StreamController (recommended)

1. Open StreamController and go to the **Store**
2. Click the **+** button to add a custom repository
3. Enter the URL: `https://github.com/tyvsmith/streamcontroller-lg-monitor-control`
4. Install the plugin from the store
5. Restart StreamController

### Manual (for development)

1. Clone this repo:
   ```bash
   git clone https://github.com/tyvsmith/streamcontroller-lg-monitor-control.git
   ```

2. Symlink into the StreamController plugins directory:
   ```bash
   ln -s /path/to/streamcontroller-lg-monitor-control \
     ~/.var/app/com.core447.StreamController/data/plugins/me_tysmith_LgMonitorControls
   ```

3. Restart StreamController.

## Monitor Profiles

The plugin uses TOML profiles in `monitors/` to configure VCP codes per monitor model. This is how it knows which DDC/CI commands to send for your specific monitor.

### Included Profiles

- **`lg_ultragear_45gx950a.toml`** — LG 45GX950A (tested, fully working except power mode)
- **`default.toml`** — Generic DDC/CI monitor (standard MCCS codes, no PBP/sharpness/black stabilizer)

### How Profiles Work

On startup, the plugin runs `ddcutil detect` to identify connected monitors by manufacturer ID and product code. It then matches against profiles in `monitors/`:

1. Exact match on `mfg_id` + `product_codes` → use that profile
2. Match on `mfg_id` only → use the first matching profile
3. No match → fall back to `default.toml`

### Adding a Profile for Your Monitor

1. Run `ddcutil detect` to get your monitor's manufacturer ID and product code
2. Copy `monitors/default.toml` to `monitors/your_monitor.toml`
3. Fill in the VCP codes. Test each one with:
   ```bash
   # Read a VCP value
   ddcutil -d 1 getvcp 0x10

   # Write a VCP value
   ddcutil -d 1 setvcp 0x10 50 --noverify

   # LG sidechannel (if applicable)
   ddcutil -d 1 getvcp 0xF4 --i2c-source-addr=x50
   ```
4. Set features you don't want to `vcp = 0` to disable them

### Profile Format

```toml
[monitor]
name = "My Monitor Model"
mfg_id = "GSM"                    # from ddcutil detect (GSM = LG, DEL = Dell, etc.)
product_codes = [12345]            # optional, for exact model matching

[inputs]
vcp = 0x60                         # standard MCCS input select
i2c_source_addr = ""               # LG uses "x50" for sidechannel
[inputs.sources]
dp = 0x0F                          # input source values vary by manufacturer
hdmi1 = 0x11

[pbp]
vcp = 0xD7                         # set to 0 if not supported
i2c_source_addr = "x51"
off = 0x01
split_50_50 = 0x05

[brightness]
vcp = 0x10                         # standard MCCS

[contrast]
vcp = 0x12                         # standard MCCS

[volume]
vcp = 0x62                         # standard MCCS

[mute]
vcp = 0x8D
muted = 1
unmuted = 2

[sharpness]
vcp = 0x87                         # set to 0 if not supported

[black_stabilizer]
vcp = 0xF9                         # set to 0 if not supported

[power]
vcp = 0xD6
on = 0x01
standby = 0x04
off = 0x05
```

## LG DDC2AB Sidechannel

LG monitors use a non-standard DDC/CI mechanism called DDC2AB for input switching and PBP control. Instead of the standard I2C address, commands are sent via alternate source addresses:

- **`--i2c-source-addr=x50`** — Input switching (VCP 0xF4)
- **`--i2c-source-addr=x51`** — PBP/PiP mode (VCP 0xD7)

Standard VCP codes (brightness, contrast, volume, etc.) work normally without the sidechannel.

See the [ddcutil wiki](https://github.com/rockowitz/ddcutil/wiki/Switching-input-source-on-LG-monitors) for details.

## Known Limitations

- **Power mode**: Reads correctly but writes are ignored on the 45GX950A (common on gaming monitors/OLEDs)
- **PiP**: Not controllable via DDC/CI on the 45GX950A — OSD only
- **Input state read**: The LG sidechannel `getvcp 0xF4` returns unreliable values, so InputSwitch uses fire-and-forget with visual tracking
- **Response time**: Returns 0xFF on the 45GX950A — not supported via DDC/CI on OLED panels
- **Hot-plugging**: Monitor detection is cached at startup — plugging or unplugging a monitor requires restarting StreamController
- **Polling**: Auto-update is off by default. When enabled per-action, polls at the plugin-wide interval (default 30s). Polling causes I2C bus access which may cause frame drops in games.

## Development

```bash
# Install dev dependencies (direnv does this automatically)
uv sync

# Run tests
uv run pytest tests/ -v

# Lint + format
uv run ruff check .
uv run ruff format --check .

# Type check
uv run pyright

# Clear cache after code changes (required for StreamController to reload)
find . -type d -name __pycache__ -exec rm -rf {} +
```

## License

Apache-2.0
