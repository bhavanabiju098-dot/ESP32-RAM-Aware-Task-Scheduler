"""
scheduler.py — RAM-aware task scheduler for ESP32

Part of the ESP32 RAM-aware task scheduler project.

This module:
    - Monitors available ESP32 heap memory
    - Determines the current memory tier
    - Executes registered sensor tasks according to priority
    - Skips lower-priority tasks when memory is limited
    - Sends sensor results to the shared buffer
    - Logs scheduler information when a logger is available
    - Produces serial-plotter-compatible output

Task priority:
    P1 → MQ4    — gas safety
    P2 → DHT11  — temperature and humidity
    P3 → IR     — motion/obstacle detection
    P4 → Sound  — lowest priority
"""

import gc
import time

# ─────────────────────────────────────────────────────────────────────────────
# RAM thresholds
# ─────────────────────────────────────────────────────────────────────────────
# Values represent the amount of FREE heap required to allow each
# scheduling tier.
#
# These thresholds are project-specific heuristics and should be
# tuned according to the actual runtime memory usage of the ESP32.

RAM_TIER_ALL    = 40_000   # ≥ 40 KB free  → run all 4 tasks (P1–P4)
RAM_TIER_NO_P4  = 28_000   # ≥ 28 KB free  → drop Sound (P4)
RAM_TIER_NO_P34 = 16_000   # ≥ 16 KB free  → drop IR + Sound (P3+P4)
# < 16 KB                  → emergency: only MQ4 runs, force gc.collect()

# ─────────────────────────────────────────────────────────────────────────────
# Task registry
# ─────────────────────────────────────────────────────────────────────────────
# Each registered task contains:
#     name     → task identifier
#     fn       → sensor function to execute
#     priority → execution priority (1 = highest)

_tasks = []

def register_task(name, fn, priority):
    """
    Register a sensor task with the scheduler.

    Parameters:
        name     : Unique task name.
        fn       : Callable sensor-reading function.
        priority : Integer priority where 1 is highest.

    Duplicate task names are ignored.
    Tasks are automatically sorted by priority.
    """
    # Prevent duplicate registration if this module is re-imported.
    for t in _tasks:
        if t['name'] == name:
            return   
        
    _tasks.append({'name': name, 'fn': fn, 'priority': priority})
    _tasks.sort(key=lambda t: t['priority'])


# ─────────────────────────────────────────────────────────────────────────────
# Scheduler state
# ─────────────────────────────────────────────────────────────────────────────
# Stores the most recent successful result from each registered task.

_last_results = {}


# ─────────────────────────────────────────────────────────────────────────────
# Memory monitoring
# ─────────────────────────────────────────────────────────────────────────────

def poll_free_ram():
    """
    Return the currently available ESP32 heap memory in bytes.

    Garbage collection is performed before measuring memory so that
    the scheduler works with a cleaner estimate of available heap.
    """
    
    gc.collect()
    return gc.mem_free()

# ─────────────────────────────────────────────────────────────────────────────
# Core scheduler
# ─────────────────────────────────────────────────────────────────────────────
def schedule_tasks(sensor_buffer=None, logger=None):
    """
    Execute one scheduler tick.

    The scheduler:
        1. Measures available RAM.
        2. Determines the current memory tier.
        3. Selects tasks according to priority.
        4. Executes the selected sensor functions.
        5. Stores successful readings in the shared buffer.
        6. Optionally logs scheduler information.
        7. Prints serial-plotter-compatible output.

    Parameters:
        sensor_buffer:
            SensorBuffer instance used to temporarily store
            sensor readings before SD-card logging.

        logger:
            SD logger object. If provided, scheduler information
            is written to the logger.

    Returns:
        dict containing:

            free_ram:
                Available heap memory before task execution.

            tier:
                Current memory tier:
                ALL, NO_P4, NO_P34, or EMERGENCY.

            ran:
                List of tasks executed during this tick.

            skipped:
                List of tasks skipped because of memory constraints.

            results:
                Dictionary containing the result of each task.
    """
    # ─────────────────────────────────────────────────────────────────────────
    # Check available memory
    # ─────────────────────────────────────────────────────────────────────────

    free = poll_free_ram()

    # ─────────────────────────────────────────────────────────────────────────
    # Determine memory tier
    # ─────────────────────────────────────────────────────────────────────────

    if free >= RAM_TIER_ALL:
        tier = 'ALL'
        max_priority = 4          # run P1 through P4
    elif free >= RAM_TIER_NO_P4:
        tier = 'NO_P4'
        max_priority = 3          # run P1–P3, skip P4 (Sound)
    elif free >= RAM_TIER_NO_P34:
        tier = 'NO_P34'
        max_priority = 2          # run P1–P2, skip P3+P4
    else:
        tier = 'EMERGENCY'
        max_priority = 1          # only MQ4 (P1); force GC
        gc.collect()              # Force garbage collection when memory is critically low.

    # ─────────────────────────────────────────────────────────────────────────
    # Execute registered tasks
    # ─────────────────────────────────────────────────────────────────────────

    ran      = []
    skipped  = []
    results  = {}

    for task in _tasks:

        # Execute tasks whose priority is allowed by the
        # current memory tier.
        if task['priority'] <= max_priority:

            try:
                value = task['fn']()
                results[task['name']] = value
                _last_results[task['name']] = value

                if sensor_buffer is not None:
                    sensor_buffer.push(task['name'], value)

                ran.append(task['name'])

            except Exception as e:
                # Log but don't crash the scheduler
                print('SCHED ERR [{}]: {}'.format(task['name'], e))
                results[task['name']] = None
        else:
            skipped.append(task['name'])
            results[task['name']] = None

    # ─────────────────────────────────────────────────────────────────────────
    # Build scheduler status information
    # ─────────────────────────────────────────────────────────────────────────

    tick_info = {
        'free_ram' : free,
        'tier'     : tier,
        'ran'      : ran,
        'skipped'  : skipped,
        'results'  : results,
    }

    # ─────────────────────────────────────────────────────────────────────────
    # Scheduler logging
    # ─────────────────────────────────────────────────────────────────────────

    if logger is not None:
        try:
            logger.write_scheduler(tick_info)
        except Exception as e:
            print('LOGGER ERR:', e)

    return tick_info


# ─────────────────────────────────────────────────────────────────────────────
# Human-readable scheduler status
# ─────────────────────────────────────────────────────────────────────────────

def status_line(tick_info):
    """
    Generate a one-line scheduler summary for the REPL 

    Returns:
        String containing timestamp, free RAM, memory tier,
        executed tasks, and skipped tasks.
    """

    return '[{}] free={}B tier={} ran={} skip={}'.format(
        time.ticks_ms(),
        tick_info['free_ram'],
        tick_info['tier'],
        ','.join(tick_info['ran'])     or '—',
        ','.join(tick_info['skipped']) or '—',
    )