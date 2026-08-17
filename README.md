# ESP32 RAM-Aware Task Scheduler

A MicroPython-based task scheduling system for the ESP32 that dynamically manages sensor tasks according to available RAM.

The system dynamically monitors available RAM and adjusts sensor task execution based on memory availability. Higher-priority tasks are preserved when memory becomes limited, while lower-priority tasks are skipped to maintain system stability. Sensor readings are buffered in RAM and periodically stored on an SD card, with a Wi-Fi interface providing live system status.

## Features

- **RAM-aware scheduling** — Monitors available ESP32 heap memory at runtime.
- **Priority-based execution** — Assigns different priorities to sensor tasks based on importance.
- **Dynamic task skipping** — Suspends lower-priority tasks when available memory decreases.
- **Circular buffering** — Temporarily stores sensor readings before SD-card writes.
- **SD-card logging** — Stores sensor readings and scheduler decisions in CSV files.
- **Wi-Fi monitoring** — Provides HTTP endpoints for live system and sensor data.
- **Fault-tolerant operation** — Handles sensor, SD-card, and network errors without unnecessarily stopping the scheduler.

## System Architecture

The system is built around an ESP32 WROOM that monitors sensor tasks based on available RAM and task priority.

![System Architecture](system_architecture.png)
The system follows a modular architecture where the ESP32 collects sensor data, 
the RAM-aware scheduler prioritizes tasks based on available memory, and a 
shared buffer temporarily stores readings before they are written to the SD card.

The ESP32 can also host a lightweight web server that provides live sensor and 
scheduler information through a browser dashboard.

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