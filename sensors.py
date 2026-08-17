"""
sensors.py — ESP32 sensor read functions (MicroPython)

Part of the ESP32 RAM-aware task scheduler project.

Sensors:
    - MQ-4 gas sensor
    - DHT11 temperature/humidity sensor
    - IR obstacle sensor
    - Analog sound sensor

DHT11 Wiring:
    VCC  → 3.3V
    GND  → GND
    DATA → GPIO4
"""

import dht
import machine
import time

# ─────────────────────────────────────────────────────────────────────────────
# Pin configuration
# ─────────────────────────────────────────────────────────────────────────────

DHT11_PIN = 4        # GPIO4  — digital input
IR_PIN    = 15       # GPIO15 — digital input
SOUND_PIN = 34       # GPIO34 — ADC input
MQ4_PIN   = 35       # GPIO35 — ADC input


# ─────────────────────────────────────────────────────────────────────────────
# Sensor initialization
# ─────────────────────────────────────────────────────────────────────────────


_dht_sensor  = dht.DHT11(machine.Pin(DHT11_PIN))
_ir_pin      = machine.Pin(IR_PIN, machine.Pin.IN)
_sound_adc   = machine.ADC(machine.Pin(SOUND_PIN))
_mq4_adc     = machine.ADC(machine.Pin(MQ4_PIN))

# Configure ADC attenuation for the ESP32 input range.
_sound_adc.atten(machine.ADC.ATTN_11DB)
_mq4_adc.atten(machine.ADC.ATTN_11DB)


# ─────────────────────────────────────────────────────────────────────────────
# Estimated task RAM requirements
# ─────────────────────────────────────────────────────────────────────────────
# These are scheduler heuristics, not exact measured allocations.

TASK_RAM = {
    "dht11": 256,   
    "ir":     96,  
    "sound": 128,  
    "mq4":   128,   
}


# ─────────────────────────────────────────────────────────────────────────────
# DHT11
# ─────────────────────────────────────────────────────────────────────────────

_last_temp  = None
_last_humid = None
_last_dht_read_ms = 0

_DHT11_MIN_INTERVAL_MS = 1100

def read_dht11():
    """
    Read temperature and relative humidity from the DHT11.

    Returns:
        tuple:
            (temperature_c, humidity_pct)

        If a read fails, the last valid reading is returned.
        If no valid reading has been obtained yet, (None, None)
        is returned.
    """

    global _last_temp, _last_humid, _last_dht_read_ms

    now = time.ticks_ms()

    # Avoid reading the DHT11 too frequently.
    if time.ticks_diff(now, _last_dht_read_ms) < _DHT11_MIN_INTERVAL_MS:
        return _last_temp, _last_humid

    try:
        _dht_sensor.measure()

        temp  = _dht_sensor.temperature()
        humid = _dht_sensor.humidity()

        # Basic sanity check for DHT11 readings.
        if not (0 <= temp <= 50) or not (20 <= humid <= 90):
            raise ValueError("Reading out of DHT11 range: {}°C {}%".format(temp, humid))

        _last_temp  = float(temp)
        _last_humid = float(humid)

        # Update timestamp only after a successful reading.
        _last_dht_read_ms = now     

        return _last_temp, _last_humid

    except OSError as e:
        print("[DHT11] OSError:", e, "→ using last known values")
        return _last_temp, _last_humid

    except ValueError as e:
        print("[DHT11] ValueError:", e, "→ using last known values")
        return _last_temp, _last_humid


# ─────────────────────────────────────────────────────────────────────────────
# IR sensor
# ─────────────────────────────────────────────────────────────────────────────

def read_ir():
    """
    Read the IR obstacle sensor.

    Returns:
        int:
            1 = object detected
            0 = clear

    Most common IR obstacle modules are active-low,
    so the raw signal is inverted here.
    """

    raw = _ir_pin.value()

    return 1 if raw == 0 else 0   # invert: most modules are active-LOW


# ─────────────────────────────────────────────────────────────────────────────
# Sound sensor
# ─────────────────────────────────────────────────────────────────────────────

_SOUND_SAMPLES = 8   # number of ADC samples to average (reduces noise)

def read_sound():
    """
    Read the analog sound sensor.

    Returns:
        int:
            Averaged ADC reading.
    """

    total = 0

    for _ in range(_SOUND_SAMPLES):
        total += _sound_adc.read()

    return total // _SOUND_SAMPLES


# ─────────────────────────────────────────────────────────────────────────────
# MQ-4 gas sensor
# ─────────────────────────────────────────────────────────────────────────────

# Calibration constants.
# These should be adjusted according to the actual sensor/module and calibration conditions.

_MQ4_RO_CLEAN_AIR = 4.4
_MQ4_RL_KOHM      = 10.0   
_MQ4_VCC          = 3.3    

def read_mq4():
    """
    Read the MQ-4 gas sensor.

    Returns:
        tuple:
            (raw_adc, voltage, rs_ro_ratio)

        raw_adc:
            Raw ADC reading.

        voltage:
            Calculated sensor output voltage.

        rs_ro_ratio:
            Normalized sensor resistance ratio.

    Note:
        This function does NOT calculate methane concentration in ppm.
        A calibrated log-log curve based on the MQ-4 datasheet is required
        for ppm estimation.
    """

    raw = _mq4_adc.read()

    # Convert ADC reading to voltage
    voltage = (raw / 4095.0) * _MQ4_VCC

    # Prevent division by zero for an extremely low ADC reading.
    if voltage < 0.01:
        voltage = 0.01   

    # Sensor resistance using the voltage-divider relationship.    
    rs = (_MQ4_VCC - voltage) / voltage * _MQ4_RL_KOHM

    # Normalize using the clean-air baseline.
    rs_ro = rs / _MQ4_RO_CLEAN_AIR

    return raw, round(voltage, 3), round(rs_ro, 3)


# ─────────────────────────────────────────────────────────────────────────────
# Combined sensor read
# ─────────────────────────────────────────────────────────────────────────────

def read_all():
    """
    Read all four sensors.

    Returns:
        dict containing the latest values from all sensors.
    """

    temp, humid         = read_dht11()
    ir                  = read_ir()
    sound               = read_sound()
    mq4_raw, mq4_v, mq4_rs = read_mq4()

    return {
        "temp":       temp,
        "humid":      humid,
        "ir":         ir,
        "sound_raw":  sound,
        "mq4_raw":    mq4_raw,
        "mq4_voltage": mq4_v,
        "mq4_rs_ro":  mq4_rs,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Standalone sensor test
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Sensor self-test — reading every 2 s. Ctrl-C to stop.\n")

    while True:
        t, h = read_dht11()
        ir   = read_ir()
        snd  = read_sound()
        raw, v, rs = read_mq4()

        print("DHT11  → {:.1f} °C  {:.1f} % RH".format(t or 0, h or 0))
        print("IR     → {}".format("DETECTED" if ir else "clear"))
        print("Sound  → {} ADC".format(snd))
        print("MQ4    → {} ADC  {:.3f} V  Rs/Ro={:.3f}".format(raw, v, rs))
        print("─" * 42)

        time.sleep(2)