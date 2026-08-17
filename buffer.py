"""
buffer.py — Circular buffer for sensor readings

Part of the ESP32 RAM-aware task scheduler project.

This module:
    - Temporarily stores sensor readings in RAM
    - Decouples sensor execution from SD-card writes
    - Uses a pre-allocated circular buffer
    - Prevents frequent memory allocation during sensor execution
    - Flushes buffered readings through a user-provided callback

Design:
    - One shared circular buffer stores readings from all sensors.
    - push() operates in O(1) time.
    - When the buffer is full, the oldest reading is overwritten.
    - flush() writes pending readings in chronological order.
    - Storage is pre-allocated during initialization to reduce
      heap fragmentation.
"""

import time

# ─────────────────────────────────────────────────────────────────────────────
# Sensor buffer
# ─────────────────────────────────────────────────────────────────────────────

class SensorBuffer:
    """
    Shared circular buffer for sensor readings.

    Example:

        buf = SensorBuffer(capacity=30)

        buf.push(
            "dht11",
            {"temp": 27.5, "humidity": 60}
        )

        buf.push(
            "mq4",
            {"ratio": 0.82}
        )

        buf.flush(write_to_sd)

    The capacity represents the maximum number of readings stored
    per sensor when four sensors are being used.
    """

    def __init__(self, capacity=30):
        """
        Initialize the sensor buffer.

        Parameters:
            capacity:
                Maximum number of readings allocated per sensor.

                With four sensors:

                    30 × 4 = 120 total slots

                The actual buffer is allocated for four sensors.
                If the buffer becomes full, the oldest readings
                are overwritten.
        """
        self._cap   = capacity

        # Pre-allocate storage for up to four sensors.
        self._buf = [None] * (capacity * 4)

        # Index where the next reading will be written.
        self._head = 0

        # Number of currently stored readings.
        self._count = 0

        # Total number of slots in the circular buffer.
        self._size = capacity * 4

    # ─────────────────────────────────────────────────────────────────────────
    # Write path
    # ─────────────────────────────────────────────────────────────────────────

    def push(self, sensor_name, value):
        """
        Store one sensor reading in the buffer.

        Parameters:
            sensor_name:
                Sensor identifier such as:
                "dht11", "mq4", "ir", or "sound".

            value:
                Value returned by the sensor task.

        Notes:
            Each entry stores:

                (sensor_name, timestamp_ms, value)

            The operation is O(1).
        """

        self._buf[self._head] = (sensor_name, time.ticks_ms(), value)

        # Move to the next circular position.
        self._head  = (self._head + 1) % self._size

        # Increase the number of stored entries until the
        # buffer reaches its maximum capacity.
        if self._count < self._size:
            self._count += 1
        # When the buffer is full, advancing head automatically
        # overwrites the oldest entry.


    # ─────────────────────────────────────────────────────────────────────────
    # Buffer status
    # ─────────────────────────────────────────────────────────────────────────

    def pending(self):
        """
        Return the number of unread entries currently stored.
        """
        return self._count

    def is_full(self):
        """
        Return True when the buffer has reached its capacity.
        """
        return self._count >= self._size

    def fill_ratio(self):
        """
        Return the current buffer fill level.

        Returns:
            Float between 0.0 and 1.0.

            Example:
                0.5 → buffer is 50% full
                0.8 → buffer is 80% full
                1.0 → buffer is completely full
        """

        return self._count / self._size
    # ─────────────────────────────────────────────────────────────────────────
    # Read / flush path
    # ─────────────────────────────────────────────────────────────────────────

    def flush(self, write_fn):
        """
        Write all pending readings using the supplied callback.

        Parameters:
            write_fn:
                Function that receives:

                    sensor_name
                    timestamp_ms
                    value

                Typically this is:

                    sd_logger.write_sensor

        Returns:
            Number of successfully written entries.
        """
        if self._count == 0:
            return 0

        # Calculate the position of the oldest stored entry.
        tail  = (self._head - self._count) % self._size
        count = self._count
        n     = 0

        # Process entries from oldest to newest.
        for i in range(count):
            idx   = (tail + i) % self._size
            entry = self._buf[idx]
            if entry is not None:
                try:
                    write_fn(entry[0], entry[1], entry[2])
                    n += 1

                except Exception as e:
                    # A single SD-card write failure should not
                    # terminate the entire flush operation.
                    print('BUF FLUSH ERR [{}]: {}'.format(entry[0], e))

                # Release the reference stored in this slot.   
                self._buf[idx] = None   

        # Reset the buffer after flushing.
        self._count = 0
        self._head  = 0 

        return n

    # ─────────────────────────────────────────────────────────────────────────
    # Latest reading
    # ─────────────────────────────────────────────────────────────────────────
    def peek_latest(self, sensor_name):
        """
        Return the most recent buffered reading for a sensor.

        The reading is not removed from the buffer.

        Parameters:
            sensor_name:
                Sensor to search for.

        Returns:
            Most recent sensor value, or None if no matching
            reading is currently buffered.

        Complexity:
            O(n), where n is the number of buffered entries.
        """
        # Start from the most recently written position.
        pos = (self._head - 1) % self._size

        for _ in range(self._count):
            entry = self._buf[pos]
            if entry is not None and entry[0] == sensor_name:
                return entry[2]
            pos = (pos - 1) % self._size
        return None

    # ─────────────────────────────────────────────────────────────────────────
    # Debug representation
    # ─────────────────────────────────────────────────────────────────────────

    def __repr__(self):
        return 'SensorBuffer(capacity={}, pending={}, fill={:.0%})'.format(
            self._cap, self._count, self.fill_ratio()
        )


# ─────────────────────────────────────────────────────────────────────────────
# Flush policy
# ─────────────────────────────────────────────────────────────────────────────

FLUSH_EVERY_N_TICKS = 10      # flush at least every 10 scheduler ticks
FLUSH_FILL_THRESHOLD = 0.80   # flush if buffer is ≥ 80 % full

def should_flush(buf, tick_count):
    """
    Determine whether the sensor buffer should be flushed.

    The buffer is flushed when either:

        1. It reaches the configured fill threshold, or
        2. The configured number of scheduler ticks has elapsed.

    Parameters:
        buf:
            SensorBuffer instance.

        tick_count:
            Monotonically increasing scheduler tick counter.

    Returns:
        True if the buffer should be flushed,
        otherwise False.
    """

    if buf.fill_ratio() >= FLUSH_FILL_THRESHOLD:
        return True
    
    if tick_count % FLUSH_EVERY_N_TICKS == 0:
        return True
    
    return False