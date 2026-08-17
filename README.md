# ESP32 RAM-Aware Task Scheduler

A memory-aware task scheduling system built on an ESP32 using MicroPython.

The system dynamically monitors available RAM and adjusts sensor task execution based on memory availability. Higher-priority tasks are preserved when memory becomes limited, while lower-priority tasks are skipped to maintain system stability.

## Features

- Dynamic RAM monitoring using `gc.mem_free()`
- Priority-based sensor task scheduling
- Memory-aware task execution
- Circular buffer for temporary sensor storage
- Periodic SD-card logging
- Wi-Fi connectivity
- HTTP server for live sensor and scheduler data
- Web-based monitoring dashboard
- Graceful handling of sensor and SD-card errors

## Hardware

- ESP32-WROOM
- DHT11 temperature and humidity sensor
- MQ-4 gas sensor
- IR obstacle sensor
- Sound sensor
- MicroSD card module

## Software

- MicroPython
- Thonny IDE
- VS Code
- Git / GitHub

## Sensor Task Priorities

| Priority | Sensor | Purpose |
|----------|--------|---------|
| P1 | MQ-4 | Gas safety monitoring |
| P2 | DHT11 | Temperature and humidity |
| P3 | IR | Obstacle detection |
| P4 | Sound | Sound-level monitoring |

When available RAM decreases, lower-priority tasks are skipped first.

## Memory-Aware Scheduling

The scheduler divides available memory into different tiers:

| Memory Condition | Tasks Executed |
|------------------|----------------|
| High memory | P1 + P2 + P3 + P4 |
| Moderate memory | P1 + P2 + P3 |
| Low memory | P1 + P2 |
| Critical memory | P1 only |

This allows the system to prioritize essential tasks instead of allowing memory pressure to affect the entire application.

## Project Structure

```text
ESP32-RAM-Aware-Task-Scheduler/
│
├── main.py
├── sensors.py
├── scheduler.py
├── buffer.py
├── sd_logger.py
├── web_server.py
├── dashboard.html
├── README.md
└── .gitignore