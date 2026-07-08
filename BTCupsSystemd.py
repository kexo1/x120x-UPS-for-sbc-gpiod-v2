#!/usr/bin/python3

import logging
import struct
import time
from pathlib import Path
from subprocess import CalledProcessError, call, check_output

import gpiod
import smbus2
from gpiod.line import Direction, Value

# User-configurable variables
SHUTDOWN_THRESHOLD = 3  # Number of consecutive failures required for shutdown
SLEEP_TIME = 60  # Time in seconds to wait between failure checks
Loop = True  # Always loop for systemd service

# Critical thresholds for shutdown
CRITICAL_VOLTAGE_THRESHOLD = 3.4  # Critical voltage threshold for shutdown (V)
CRITICAL_CAPACITY_THRESHOLD = 20  # Critical capacity threshold for shutdown (%)

# Charging control variables
MAX_CHARGE_VOLTAGE = 4.10  # Maximum charging voltage (V)
CHARGE_PAUSE_TIME = 600  # Time in seconds to pause charging after reaching max voltage
CHARGE_CONTROL_PIN = 16  # GPIO pin to control charging (per Suptronics X120X manual)
CHARGE_ENABLE_STATE = (
    0  # GPIO state to enable charging: 0 = enable (low), 1 = disable (high)
)

# Logging frequency control (seconds)
LOG_INTERVAL = 600  # default 10 minutes between detailed status logs

# GPIO / I2C config
GPIO_CHIP = "/dev/gpiochip0"  # Pi 5 uses gpiochip0 with pinctrl-rp1
PLD_PIN = 6  # Power loss detection pin
I2C_BUS = 1
I2C_ADDRESS = 0x36

# Logging setup
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# ─── I2C / Battery ────────────────────────────────────────────────────────────


def readVoltage(bus):
    try:
        read = bus.read_word_data(I2C_ADDRESS, 2)
        swapped = struct.unpack("<H", struct.pack(">H", read))[0]
        return swapped * 1.25 / 1000 / 16
    except Exception as e:
        logger.error(f"Error reading voltage: {e}")
        return None


def readCapacity(bus):
    try:
        read = bus.read_word_data(I2C_ADDRESS, 4)
        swapped = struct.unpack("<H", struct.pack(">H", read))[0]
        return swapped / 256
    except Exception as e:
        logger.error(f"Error reading capacity: {e}")
        return None


def quick_start_fuel_gauge(bus):
    try:
        bus.write_word_data(I2C_ADDRESS, 6, 0x4000)
        time.sleep(1)
    except Exception as e:
        logger.error(f"Error performing quick-start: {e}")


def get_battery_status(voltage):
    if voltage is None:
        return "Unknown"
    elif voltage >= 3.87:
        return "Full"
    elif voltage >= 3.7:
        return "High"
    elif voltage >= 3.55:
        return "Medium"
    elif voltage >= 3.4:
        return "Low"
    else:
        return "Critical"


# ─── System metrics ───────────────────────────────────────────────────────────


def read_hardware_metric(command_args, strip_chars):
    try:
        output = check_output(command_args).decode("utf-8").strip()
        value_str = output.split("=")[-1].strip().rstrip(strip_chars)
        return float(value_str)
    except (CalledProcessError, ValueError, IndexError) as e:
        logger.error(f"Error reading hardware metric: {e}")
        return None


def read_cpu_volts():
    return read_hardware_metric(["vcgencmd", "pmic_read_adc", "VDD_CORE_V"], "V")


def read_cpu_amps():
    return read_hardware_metric(["vcgencmd", "pmic_read_adc", "VDD_CORE_A"], "A")


def read_cpu_temp():
    return read_hardware_metric(["vcgencmd", "measure_temp"], "'C")


def read_input_voltage():
    return read_hardware_metric(["vcgencmd", "pmic_read_adc", "EXT5V_V"], "V")


def get_fan_rpm():
    try:
        fan_files = list(Path("/sys/devices/platform/cooling_fan").rglob("fan1_input"))
        if not fan_files:
            return "No fan detected"
        with open(fan_files[0], "r") as f:
            return f"{f.read().strip()} RPM"
    except FileNotFoundError:
        return "Fan RPM file not found"
    except PermissionError:
        return "Permission denied accessing fan RPM"
    except Exception as e:
        return f"Fan error: {e}"


def power_consumption_watts():
    """
    Parse Pi 5 vcgencmd pmic_read_adc format:
      VDD_CORE_A current(7)=1.08053000A
      VDD_CORE_V volt(15)=0.72178200V
    """
    try:
        output = check_output(["vcgencmd", "pmic_read_adc"]).decode("utf-8")
        amperages, voltages = {}, {}
        for line in output.split("\n"):
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            label = parts[0]  # e.g. VDD_CORE_A
            value_str = parts[-1].split("=")[-1]  # e.g. current(7)=1.08A -> 1.08A
            try:
                val = float(value_str[:-1])  # strip trailing unit char
            except ValueError:
                continue
            if label.endswith("_A"):
                amperages[label[:-2]] = val
            elif label.endswith("_V"):
                voltages[label[:-2]] = val
        return sum(amperages[k] * voltages[k] for k in amperages if k in voltages)
    except Exception as e:
        logger.error(f"Error calculating power consumption: {e}")
        return None


# ─── Logging / display ────────────────────────────────────────────────────────


def log_system_stats(voltage, capacity, charging_enabled, ac_power_state):
    cpu_volts = read_cpu_volts()
    cpu_amps = read_cpu_amps()
    cpu_temp = read_cpu_temp()
    input_voltage = read_input_voltage()
    fan_rpm = get_fan_rpm()
    pwr_use = power_consumption_watts()
    charge_status = "enabled" if charging_enabled else "disabled"
    power_status = (
        "AC Power: OK - Power Adapter: OK"
        if ac_power_state == 1
        else "WARNING: Power Loss OR Power Adapter Failure"
    )

    def fv(v, unit, dec=3):
        return f"{v:.{dec}f} {unit}" if v is not None else "N/A"

    logger.info(
        f"UPS: {fv(voltage, 'V')} | Battery: {fv(capacity, '%')} | Charging: {charge_status} | "
        f"Input: {fv(input_voltage, 'V')} | CPU: {fv(cpu_volts, 'V')} {fv(cpu_amps, 'A')} | "
        f"Power: {fv(pwr_use, 'W')} | Temp: {fv(cpu_temp, 'C', 1)} | Fan: {fan_rpm} | {power_status}"
    )

    if ac_power_state != 1 and capacity:
        if capacity >= 51:
            logger.warning(
                f"Running on UPS Backup Power - Batteries @ {capacity:.2f}% - Voltage @ {fv(voltage, 'V')}"
            )
        elif capacity >= 25:
            logger.warning(
                f"UPS Power levels approaching critical - Batteries @ {capacity:.2f}% - Voltage @ {fv(voltage, 'V')}"
            )
        elif capacity >= 16:
            logger.warning(
                f"UPS Power levels critical - Batteries @ {capacity:.2f}% - Voltage @ {fv(voltage, 'V')}"
            )
        else:
            logger.critical(f"UPS Power failure imminent - Batteries @ {capacity:.2f}%")


# ─── Charging control ─────────────────────────────────────────────────────────


def control_charging(charge_line, voltage, current_charge_state, last_charge_stop_time):
    if voltage is None:
        logger.warning("Cannot control charging - voltage reading failed")
        return current_charge_state, last_charge_stop_time
    try:
        if voltage >= MAX_CHARGE_VOLTAGE and current_charge_state:
            charge_line.set_values({CHARGE_CONTROL_PIN: Value(1 - CHARGE_ENABLE_STATE)})
            logger.info(
                f"CHARGING STOPPED - Voltage {voltage:.3f}V >= {MAX_CHARGE_VOLTAGE}V"
            )
            return False, time.time()
        elif voltage < MAX_CHARGE_VOLTAGE and not current_charge_state:
            if (
                last_charge_stop_time is None
                or (time.time() - last_charge_stop_time) >= CHARGE_PAUSE_TIME
            ):
                charge_line.set_values({CHARGE_CONTROL_PIN: Value(CHARGE_ENABLE_STATE)})
                logger.info(
                    f"CHARGING RESUMED - Voltage {voltage:.3f}V < {MAX_CHARGE_VOLTAGE}V"
                )
                return True, last_charge_stop_time
        return current_charge_state, last_charge_stop_time
    except Exception as e:
        logger.error(f"Error controlling charging: {e}")
        return current_charge_state, last_charge_stop_time


# ─── Critical conditions ──────────────────────────────────────────────────────


def check_critical_conditions(ac_power_state, voltage, capacity):
    conditions = []
    if voltage is not None and voltage < CRITICAL_VOLTAGE_THRESHOLD:
        conditions.append(
            f"critical battery voltage ({voltage:.3f}V < {CRITICAL_VOLTAGE_THRESHOLD}V)"
        )
    if (
        ac_power_state == 0
        and voltage is not None
        and voltage < CRITICAL_VOLTAGE_THRESHOLD
    ):
        conditions.append("AC power loss with critical battery voltage")
    return conditions


# ─── Main ─────────────────────────────────────────────────────────────────────

charging_enabled = True
bus = None
pld_line = None
charge_line = None
last_charge_stop_time = None
last_log_time = None

try:
    bus = smbus2.SMBus(I2C_BUS)

    # gpiod v2 API - Pi 5 compatible
    pld_line = gpiod.request_lines(
        GPIO_CHIP,
        consumer="PLD",
        config={PLD_PIN: gpiod.LineSettings(direction=Direction.INPUT)},
    )
    logger.info(f"Power loss detection initialized on GPIO {PLD_PIN}")

    try:
        charge_line = gpiod.request_lines(
            GPIO_CHIP,
            consumer="CHARGE_CTRL",
            config={
                CHARGE_CONTROL_PIN: gpiod.LineSettings(
                    direction=Direction.OUTPUT, output_value=Value(CHARGE_ENABLE_STATE)
                )
            },
        )
        logger.info(f"Charging control initialized on GPIO {CHARGE_CONTROL_PIN}")
    except Exception as e:
        logger.warning(
            f"Could not initialize charging control on GPIO {CHARGE_CONTROL_PIN}: {e}"
        )
        logger.warning("Continuing without charging control")
        charge_line = None

    quick_start_fuel_gauge(bus)

    logger.info("UPS monitoring started")
    logger.info(f"Critical voltage threshold: {CRITICAL_VOLTAGE_THRESHOLD}V")
    logger.info(
        "AC power loss will only trigger shutdown when combined with critical voltage"
    )

    while True:
        failure_counter = 0

        for _ in range(SHUTDOWN_THRESHOLD):
            # gpiod v2: get_values() returns a list in request order
            ac_power_state = pld_line.get_values()[0].value

            voltage = readVoltage(bus)
            capacity = readCapacity(bus)

            if charge_line is not None:
                charging_enabled, last_charge_stop_time = control_charging(
                    charge_line, voltage, charging_enabled, last_charge_stop_time
                )

            # Throttle detailed logging to reduce log volume
            try:
                now = time.time()
                if last_log_time is None or (now - last_log_time) >= LOG_INTERVAL:
                    log_system_stats(
                        voltage, capacity, charging_enabled, ac_power_state
                    )
                    last_log_time = now
            except Exception as e:
                logger.error(f"Error during throttled logging: {e}")

            critical_conditions = check_critical_conditions(
                ac_power_state, voltage, capacity
            )

            if critical_conditions:
                for condition in critical_conditions:
                    logger.warning(f"Critical condition detected: {condition}")
                failure_counter += 1
            else:
                failure_counter = 0
                if ac_power_state == 0:
                    logger.info(
                        "AC power loss detected but battery voltage above critical threshold - continuing"
                    )
                break

            if failure_counter < SHUTDOWN_THRESHOLD:
                time.sleep(SLEEP_TIME)

        if failure_counter >= SHUTDOWN_THRESHOLD:
            critical_conditions = check_critical_conditions(
                ac_power_state, voltage, capacity
            )
            shutdown_message = (
                "Critical conditions met due to: "
                + ", ".join(critical_conditions)
                + ". Initiating shutdown."
            )
            logger.critical(shutdown_message)

            if charge_line is not None:
                try:
                    charge_line.set_values(
                        {CHARGE_CONTROL_PIN: Value(1 - CHARGE_ENABLE_STATE)}
                    )
                    logger.info("Charging disabled before shutdown")
                except Exception as e:
                    logger.error(f"Error disabling charging before shutdown: {e}")

            call("sudo nohup shutdown -h now", shell=True)
        else:
            if Loop:
                time.sleep(SLEEP_TIME)
            else:
                logger.info("Single check completed, exiting")
                break

except KeyboardInterrupt:
    logger.info("Script interrupted by user")
except Exception as e:
    logger.error(f"Unexpected error: {e}")
finally:
    if charge_line is not None:
        try:
            charge_line.release()
        except Exception:
            pass
    if pld_line is not None:
        try:
            pld_line.release()
        except Exception:
            pass
    if bus is not None:
        try:
            bus.close()
        except Exception:
            pass
    logger.info("UPS monitoring stopped")
