## Usage

### Manual Operation (`BTCups.py`)

```bash
# Single check and exit (Loop = False by default)
sudo python3 BTCups.py

# Continuous monitoring (set Loop = True in the script)
sudo python3 BTCups.py
```

- The script will **limit charging at 4.10V** and pause charging for a configurable time (`CHARGE_PAUSE_TIME`, default 600s) before resuming.
- Status and warnings are printed to the console.

### Service Operation (`BTCupsSystemd.py`)

- Designed for use as a **systemd service** (continuous monitoring, Loop = True).
- Automatically handles UPS monitoring, charging control, and safe shutdown.
- All status and warnings are logged to the system journal.

**To view logs:**

```bash
journalctl -u btcups.service -f
```

### Output

- **BTCups.py**: Prints status and warnings to the console.
- **BTCupsSystemd.py**: Logs status and warnings to the system journal.

## GPIO Pin Configuration

The scripts use the following GPIO pins:

- **GPIO 6**: Power Loss Detection (PLD) - Input
- **GPIO 16**: Charging Control - Output

### Manual Charging Control

You can manually control charging using pinctrl commands:

```bash
# Enable charging (drive GPIO 16 LOW)
sudo pinctrl set 16 op dl

# Disable charging (drive GPIO 16 HIGH)
sudo pinctrl set 16 op dh

# Check current GPIO 16 state
sudo pinctrl get 16
```

## Charging Logic

- Charging is **enabled** when battery voltage is below 4.10V and the pause time has passed.
- Charging is **disabled** when battery voltage reaches or exceeds 4.10V, and remains off for `CHARGE_PAUSE_TIME` seconds before resuming.
