# Raspberry Pi UPS Monitoring Script

> **Fork notice:** This is a fork of the original [BTCups](https://github.com/Schnema1/x120x-UPS-for-sbc) project, updated for gpiod v2 compatibility and tested on Raspberry Pi 5. Updated with AI assistance. Use at your own risk.

---

This project provides two Python scripts for monitoring and managing Suptronics X120X series UPS boards on Raspberry Pi 5:

- **BTCups.py** — Intended for manual operation, testing, and troubleshooting. Run this script directly for single checks or interactive monitoring. Recommended for initial setup, diagnostics, or development. Output is printed to the console.
- **BTCupsSystemd.py** — Designed for continuous, unattended operation as a systemd service. Use this script for automatic startup and safe shutdown in production environments. All output is logged (not printed) and is suitable for background/system use.

**Summary:** Use `BTCups.py` for manual checks and debugging. Use `BTCupsSystemd.py` for 24/7 monitoring as a background service (systemd).

Both scripts provide battery monitoring, charging control, and automatic safe shutdown functionality.

Tested with **Raspberry Pi 5 only**. If your SBC matches the Pi 5 pin layout, it should work as well.

Intended for use with Bitcoin Fullnode projects like [RaspiBlitz](https://github.com/raspiblitz/raspiblitz), [RaspiBolt](https://raspibolt.org/), or similar. With Lightning enabled, you don't want to risk a power loss and get a corrupted database. This script allows you to run for some hours without power and, if the batteries are close to empty, perform a graceful shutdown.

---

## What Changed in This Fork

- **gpiod v1 → v2 API** — fully updated for `gpiod` 2.x (required on Pi 5 with recent Raspberry Pi OS)
- **Pi 5 `vcgencmd` output parser** — fixed power consumption parsing for the Pi 5 `pmic_read_adc` format
- **I2C address moved to constant** — cleaner configuration at the top of the script
- **Tested on Pi 5 with Suptronics X1200**

---

## Features

- **Battery Monitoring** — real-time voltage and capacity monitoring using MAX17040/MAX17041 fuel gauge
- **Smart Charging Control** — charging is disabled when voltage reaches or exceeds 4.10V and remains off for a configurable pause time (`CHARGE_PAUSE_TIME`) before resuming
- **Power Loss Detection** — monitors AC power status via GPIO
- **Safe Shutdown** — automatic shutdown on critical battery conditions
- **Logging** — comprehensive logging with configurable levels
- **Service Integration** — `BTCupsSystemd.py` can run as a systemd service for automatic startup

---

## Hardware Requirements

- Raspberry Pi 5 (or GPIO compatible boards)
- Suptronics X1200 series UPS board (X1200, X1201, X1202)
- I2C enabled on Raspberry Pi

---

## Dependencies

```bash
pip install smbus2 gpiod
```

Make sure I2C is enabled:

```bash
sudo raspi-config
# Interface Options -> I2C -> Enable
```

Verify the UPS chip is detected on the I2C bus:

```bash
sudo i2cdetect -y 1
# Should show a device at address 0x36
```

---

## Installation

```bash
# Clone or copy the scripts
sudo cp BTCupsSystemd.py /usr/local/bin/btcups.py
sudo chmod +x /usr/local/bin/btcups.py

# Create the systemd service
sudo nano /etc/systemd/system/btcups.service
```

Paste the following into the service file:

```ini
[Unit]
Description=BTCups UPS Monitor
After=network.target
Wants=network.target

[Service]
Type=simple
User=root
ExecStart=/usr/bin/python3 /usr/local/bin/btcups.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

> If using a virtualenv, replace `/usr/bin/python3` with your venv path e.g. `/home/mato/python/bin/python3`

Enable and start the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable btcups
sudo systemctl start btcups
sudo systemctl status btcups
```

View live logs:

```bash
sudo journalctl -u btcups -f
```

---

## Configuration

All user-configurable variables are at the top of each script:

| Variable | Default | Description |
|---|---|---|
| `SHUTDOWN_THRESHOLD` | `3` | Consecutive failures before shutdown |
| `SLEEP_TIME` | `60` | Seconds between checks |
| `CRITICAL_VOLTAGE_THRESHOLD` | `3.4V` | Voltage that triggers shutdown |
| `MAX_CHARGE_VOLTAGE` | `4.10V` | Voltage at which charging stops |
| `CHARGE_PAUSE_TIME` | `600s` | Seconds to pause before resuming charge |
| `CHARGE_CONTROL_PIN` | `16` | GPIO pin for charging control |
| `CHARGE_ENABLE_STATE` | `0` | GPIO state to enable charging (0=low) |

---

## GPIO Pin Configuration

| Pin | Role | Direction |
|---|---|---|
| GPIO 6 | Power Loss Detection (PLD) | Input |
| GPIO 16 | Charging Control | Output |

---

## Battery Status Levels

| Status | Voltage Range |
|---|---|
| Full | 3.87V - 4.2V |
| High | 3.7V - 3.87V |
| Medium | 3.55V - 3.7V |
| Low | 3.4V - 3.55V |
| Critical | < 3.4V |

---

## Charging Logic

Charging is disabled when battery voltage reaches or exceeds `MAX_CHARGE_VOLTAGE` (default 4.10V). It remains off for `CHARGE_PAUSE_TIME` seconds (default 600s / 10 min) before being allowed to resume. This prevents constant charge cycling at full capacity and extends battery life.

---

## Safety Features

- **Multiple failure threshold** — requires consecutive failures before triggering shutdown
- **Graceful cleanup** — properly releases GPIO resources on exit
- **Charging protection** — prevents overcharging with voltage monitoring and timed pause
- **Comprehensive logging** — all events logged with timestamps
- **Error handling** — continues operation even when individual sensor reads fail

---

## License

This script is provided as-is for educational and practical use with Suptronics X120X UPS boards.

---

## Contributing

Feel free to submit issues, feature requests, or improvements via pull requests.

---

## Support

For hardware-specific issues, consult the [Suptronics X120X documentation](http://www.suptronics.com/).

---

> **Warning:** This script can trigger automatic system shutdown. Test thoroughly before deploying in production environments.