"""
sd_logger.py — SD card logger for ESP32

Logs sensor readings and scheduler decisions to CSV files.
"""

import machine
import os
import time

try:
    import sdcard          
except ImportError:
    sdcard = None

# ─────────────────────────────────────────────────────────────────────────────
# SD card configuration
# ─────────────────────────────────────────────────────────────────────────────

SD_CS_PIN   = 15      
SD_SCK_PIN  = 18
SD_MOSI_PIN = 23
SD_MISO_PIN = 19

# ─────────────────────────────────────────────────────────────────────────────
# File paths (on SD card)
# ─────────────────────────────────────────────────────────────────────────────

MOUNT_POINT    = '/sd'
SENSOR_LOG     = MOUNT_POINT + '/sensor_log.csv'
SCHEDULER_LOG  = MOUNT_POINT + '/scheduler_log.csv'

# ─────────────────────────────────────────────────────────────────────────────
# CSV headers
# ─────────────────────────────────────────────────────────────────────────────

_SENSOR_HEADER    = 'timestamp_ms,sensor,temp_c,humid_pct,ir,sound_raw,mq4_raw,mq4_voltage,mq4_rs_ro\n'
_SCHEDULER_HEADER = 'timestamp_ms,free_ram_bytes,tier,ran,skipped\n'

# ─────────────────────────────────────────────────────────────────────────────
# Module state
# ─────────────────────────────────────────────────────────────────────────────

_mounted = False
_sd      = None
_vfs     = None


# ─────────────────────────────────────────────────────────────────────────────
# Initialization
# ─────────────────────────────────────────────────────────────────────────────

def init():
    """
    Initialize and mount the SD card.

    Creates the sensor and scheduler log files if they do not exist.
    """
    global _mounted, _sd, _vfs

    if sdcard is None:
        raise ImportError(
            "sdcard module not found. Copy sdcard.py to the board.\n"
        )

    spi = machine.SPI(
        1,
        baudrate  = 1_000_000,     # 1 MHz for init; sdcard driver bumps it later
        polarity  = 0,
        phase     = 0,
        sck       = machine.Pin(SD_SCK_PIN),
        mosi      = machine.Pin(SD_MOSI_PIN),
        miso      = machine.Pin(SD_MISO_PIN),
    )

    cs   = machine.Pin(SD_CS_PIN, machine.Pin.OUT)

    _sd  = sdcard.SDCard(spi, cs)
    _vfs = os.VfsFat(_sd)

    os.mount(_vfs, MOUNT_POINT)
    _mounted = True

    _ensure_headers()
    print('[SD] Mounted at', MOUNT_POINT)


def _ensure_headers():
    """Create log files with headers if they are missing or empty."""

    _write_header(SENSOR_LOG,    _SENSOR_HEADER)
    _write_header(SCHEDULER_LOG, _SCHEDULER_HEADER)


def _write_header(path, header):
    """Write a CSV header when the file does not exist or is empty."""
    try:
        size = os.stat(path)[6]  
        if size == 0:
            raise OSError          # treat empty file same as missing

    except OSError:
        with open(path, 'w') as f:
            f.write(header)


def is_mounted():
    """Return True if the SD card is currently mounted."""
    return _mounted


# ─────────────────────────────────────────────────────────────────────────────
# Sensor logging
# ─────────────────────────────────────────────────────────────────────────────

def write_sensor(sensor_name, timestamp_ms, value):
    """
    Append one sensor reading to sensor_log.csv.

    The value format depends on the sensor:
        DHT11 → (temperature, humidity)
        IR    → detection state
        Sound → ADC value
        MQ4   → (raw ADC, voltage, Rs/Ro)
    """

    if not _mounted:
        return

    # Build a row dict with None for columns not relevant to this sensor
    row = {
        'ts':          timestamp_ms,
        'sensor':      sensor_name,
        'temp':        '',
        'humid':       '',
        'ir':          '',
        'sound_raw':   '',
        'mq4_raw':     '',
        'mq4_voltage': '',
        'mq4_rs_ro':   '',
    }

    if sensor_name == 'dht11' and value is not None:
        temp, humid = value
        row['temp']  = '' if temp  is None else '{:.1f}'.format(temp)
        row['humid'] = '' if humid is None else '{:.1f}'.format(humid)

    elif sensor_name == 'ir' and value is not None:
        row['ir'] = str(value)

    elif sensor_name == 'sound' and value is not None:
        row['sound_raw'] = str(value)

    elif sensor_name == 'mq4' and value is not None:
        raw, voltage, rs_ro = value
        row['mq4_raw']     = str(raw)
        row['mq4_voltage'] = '{:.3f}'.format(voltage)
        row['mq4_rs_ro']   = '{:.3f}'.format(rs_ro)

    line = '{},{},{},{},{},{},{},{},{}\n'.format(
        row['ts'], row['sensor'],
        row['temp'], row['humid'], row['ir'],
        row['sound_raw'], row['mq4_raw'],
        row['mq4_voltage'], row['mq4_rs_ro'],
    )

    _append(SENSOR_LOG, line)


# ─────────────────────────────────────────────────────────────────────────────
# Scheduler logging
# ─────────────────────────────────────────────────────────────────────────────

def write_scheduler(tick_info):
    """
    Append one scheduler tick to scheduler_log.csv.

    Stores:
        free RAM
        memory tier
        executed tasks
        skipped tasks
    """

    if not _mounted:
        return

    ran     = '|'.join(tick_info.get('ran',     []))
    skipped = '|'.join(tick_info.get('skipped', []))

    line = '{},{},{},{},{}\n'.format(
        time.ticks_ms(),
        tick_info.get('free_ram', ''),
        tick_info.get('tier',     ''),
        ran,
        skipped,
    )

    _append(SCHEDULER_LOG, line)


# ─────────────────────────────────────────────────────────────────────────────
# File operations
# ─────────────────────────────────────────────────────────────────────────────

def _append(path, line):
    """Append a line to a file without stopping the scheduler on failure."""
    try:
        with open(path, 'a') as f:
            f.write(line)

    except OSError as e:
        print('[SD] Write error on {}: {}'.format(path, e))


# ─────────────────────────────────────────────────────────────────────────────
# SD card information
# ─────────────────────────────────────────────────────────────────────────────

def free_space_kb():
    """Return available SD-card space in KB."""

    if not _mounted:
        return None
    try:
        stats = os.statvfs(MOUNT_POINT)
        # statvfs: [0]=block_size [2]=total_blocks [3]=free_blocks
        return (stats[0] * stats[3]) // 1024
    except OSError:
        return None


def log_sizes():
    """Return the sizes of the sensor and scheduler log files in bytes."""
    def _size(path):
        try:
            return os.stat(path)[6]
        except OSError:
            return 0
    return _size(SENSOR_LOG), _size(SCHEDULER_LOG)


# ─────────────────────────────────────────────────────────────────────────────
# Quick test
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    init()
    print('Free space:', free_space_kb(), 'KB')

    # Simulate a DHT11 flush
    write_sensor('dht11', time.ticks_ms(), (27.0, 65.0))
    write_sensor('mq4',   time.ticks_ms(), (820, 0.66, 0.82))
    write_sensor('ir',    time.ticks_ms(), 1)
    write_sensor('sound', time.ticks_ms(), 1200)

    # Simulate a scheduler tick
    write_scheduler({
        'free_ram': 42000,
        'tier':     'ALL',
        'ran':      ['mq4', 'dht11', 'ir', 'sound'],
        'skipped':  [],
    })

    s_sz, sc_sz = log_sizes()
    print('sensor_log.csv    :', s_sz,  'bytes')
    print('scheduler_log.csv :', sc_sz, 'bytes')