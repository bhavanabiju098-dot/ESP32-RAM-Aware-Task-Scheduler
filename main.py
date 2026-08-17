"""
main.py — ESP32 RAM-aware task scheduler entry point

Part of the ESP32 RAM-aware task scheduler project.

This module:
    - Registers sensor tasks with the scheduler
    - Initializes the shared sensor buffer
    - Initializes SD-card logging
    - Runs the scheduler at a fixed interval
    - Flushes buffered readings to the SD card

Run using:
    - Thonny (F5)
    - VS Code + mpremote
"""


import time
import gc

import sensors
import scheduler
import buffer
import sd_logger  
import web_server

# ─────────────────────────────────────────────────────────────────────────────
# Task registration
# ─────────────────────────────────────────────────────────────────────────────
# Each task is registered with a priority.
# Lower priority number = higher execution priority.

scheduler.register_task('mq4',   sensors.read_mq4,   priority=1)
scheduler.register_task('dht11', sensors.read_dht11,  priority=2)
scheduler.register_task('ir',    sensors.read_ir,     priority=3)
scheduler.register_task('sound', sensors.read_sound,  priority=4)


# ─────────────────────────────────────────────────────────────────────────────
# Shared sensor buffer
# ─────────────────────────────────────────────────────────────────────────────
# The buffer temporarily stores sensor readings before they are
# written to the SD card.
#
# Capacity = 30 readings per sensor.
# With four sensors, the buffer can hold up to approximately
# 120 sensor readings depending on the data structure used.

buf = buffer.SensorBuffer(capacity=30)


# ─────────────────────────────────────────────────────────────────────────────
# SD-card logger initialization
# ─────────────────────────────────────────────────────────────────────────────
# If SD-card initialization fails, the scheduler continues to run
# without logging rather than stopping the entire application.

try:
    sd_logger.init()          
    logger = sd_logger
    print('SD card OK')

except Exception as e:
    print('SD init failed, logging disabled:', e)
    logger = None

# Start WiFi web server
web_server.start()

# ─────────────────────────────────────────────────────────────────────────────
# Main scheduler loop
# ─────────────────────────────────────────────────────────────────────────────

TICK_INTERVAL_MS = 500    # run scheduler every 500 ms → ~2 ticks/sec

tick_count = 0

print('Scheduler started. Free RAM:', gc.mem_free(), 'bytes')

while True:
    # Record the start time of the current scheduler tick.
    t0 = time.ticks_ms()

    # Run one scheduler tick.
    # The scheduler:
    #   1. Checks available memory.
    #   2. Determines the current memory tier.
    #   3. Selects sensor tasks according to priority.
    #   4. Reads the selected sensors.
    #   5. Adds readings to the shared buffer.
    #   6. Optionally logs scheduler information.

    tick_info = scheduler.schedule_tasks(
        sensor_buffer = buf,
        logger        = logger,
    )

    web_server.update_data(tick_info)
    web_server.poll()

    tick_count += 1

    # ─────────────────────────────────────────────────────────────────────────
    # Periodic buffer flushing
    # ─────────────────────────────────────────────────────────────────────────
    # Flush the buffer when:
    #   - the configured flush interval is reached, or
    #   - the buffer reaches the configured capacity threshold.

    if logger is not None and buffer.should_flush(buf, tick_count):
        n = buf.flush(logger.write_sensor)
        if n:
            print('# flushed {} readings to SD'.format(n))

    # Optional human-readable scheduler status.
    # Keep disabled when using the serial plotter because additional
    # text can interfere with numerical plotter output.
    # print(scheduler.status_line(tick_info))

    # ─────────────────────────────────────────────────────────────────────────
    # Maintain fixed scheduler interval
    # ─────────────────────────────────────────────────────────────────────────

    elapsed = time.ticks_diff(time.ticks_ms(), t0)
    sleep_ms = max(0, TICK_INTERVAL_MS - elapsed)
    time.sleep_ms(sleep_ms)