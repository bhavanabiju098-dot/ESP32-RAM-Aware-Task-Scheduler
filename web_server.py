"""
web_server.py — ESP32 WiFi and HTTP server

Provides a lightweight HTTP interface for monitoring:
    - Sensor readings
    - Available RAM
    - Current scheduler tier
    - Running and skipped tasks

Endpoints:
    GET /data      → latest sensor and scheduler data
    GET /health    → uptime, RAM, and IP address
"""

import network
import socket
import json
import time
import gc

# ─────────────────────────────────────────────────────────────────────────────
# WiFi configuration
# ─────────────────────────────────────────────────────────────────────────────

WIFI_SSID     = "YOUR_WIFI_NAME"
WIFI_PASSWORD = "YOUR_WIFI_PASSWORD"

WIFI_TIMEOUT_S = 15    # seconds to wait for connection before giving up

# ─────────────────────────────────────────────────────────────────────────────
# Server state
# ─────────────────────────────────────────────────────────────────────────────

_server_sock  = None
_wlan         = None
_ip           = None
_start_time   = time.ticks_ms()

# Latest scheduler and sensor data served by /data.
_latest = {
    "tick":      0,
    "free_ram":  0,
    "tier":      "UNKNOWN",
    "ran":       [],
    "skipped":   [],
    "emergency": False,
    "sensors": {
        "mq4":   {"raw": None, "voltage": None, "rs_ro": None},
        "dht11": {"temp": None, "humid": None},
        "ir":    {"detected": None},
        "sound": {"raw": None},
    }
}

# ─────────────────────────────────────────────────────────────────────────────
# WiFi connection
# ─────────────────────────────────────────────────────────────────────────────

def connect_wifi():
    """
    Connect to the configured WiFi network.

    Returns:
        str: ESP32 IP address on success.
        None: If the connection fails or times out.
    """
    global _wlan, _ip

    _wlan = network.WLAN(network.STA_IF)

    # Reset the WiFi interface before connecting.
    _wlan.active(False)
    time.sleep(0.5)

    _wlan.active(True)
    time.sleep(0.5)

    if _wlan.isconnected():
        _ip = _wlan.ifconfig()[0]
        print("[wifi] Already connected — IP:", _ip)
        return _ip

    print("[wifi] Connecting to '{}'...".format(WIFI_SSID))

    try:
        _wlan.connect(WIFI_SSID, WIFI_PASSWORD)

    except OSError as e:
        
        print("[wifi] connect() raised OSError: {} — retrying after hard reset".format(e))
        # Retry after resetting the interface.
        _wlan.active(False)
        time.sleep(1)
        _wlan.active(True)
        time.sleep(0.5)
        _wlan.connect(WIFI_SSID, WIFI_PASSWORD)

    deadline = time.time() + WIFI_TIMEOUT_S

    while not _wlan.isconnected():
        if time.time() > deadline:
            print("[wifi] Connection timed out — check SSID/password and signal strength")
            return None
        time.sleep(0.5)

    _ip = _wlan.ifconfig()[0]
    print("[wifi] Connected — IP: {}  (open this in your browser)".format(_ip))
    return _ip


# ─────────────────────────────────────────────────────────────────────────────
# HTTP server
# ─────────────────────────────────────────────────────────────────────────────

def start_server(port=80):
    """
    Start a non-blocking HTTP server.

    The socket is checked periodically by poll() so that
    HTTP requests do not block the scheduler.
    """
    global _server_sock

    _server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    _server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    _server_sock.bind(("", port))
    _server_sock.listen(1)
    _server_sock.setblocking(False)   # non-blocking: poll each tick
    print("[server] Listening on {}:{}".format(_ip or "0.0.0.0", port))


def start(port=80):
    """
    Connect to WiFi and start the HTTP server.

    Returns:
        True  → server started successfully.
        False → WiFi connection failed.
    """
    ip = connect_wifi()
    if ip:
        start_server(port)
        return True
    print("[server] WiFi failed — web server disabled")
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Data update
# ─────────────────────────────────────────────────────────────────────────────

def update_data(tick_result, readings):
    """
    Update the web dashboard with the latest scheduler results.

    Parameters:
        tick_info:
            Dictionary returned by scheduler.schedule_tasks().
    """
    
    _latest["tick"]      = tick_result["tick"]
    _latest["free_ram"]  = tick_result["free_ram"]
    _latest["tier"]      = _tier_label(tick_result["free_ram"])
    _latest["ran"]       = tick_result["ran"]
    _latest["skipped"]   = tick_result["skipped"]
    _latest["emergency"] = tick_result["emergency"]

    # Unpack each sensor reading into named fields
    if "mq4" in readings and readings["mq4"]:
        raw, v, rs = readings["mq4"]
        _latest["sensors"]["mq4"] = {"raw": raw, "voltage": v, "rs_ro": rs}

    if "dht11" in readings and readings["dht11"]:
        t, h = readings["dht11"]
        _latest["sensors"]["dht11"] = {"temp": t, "humid": h}

    if "ir" in readings:
        _latest["sensors"]["ir"] = {"detected": readings["ir"]}

    if "sound" in readings:
        _latest["sensors"]["sound"] = {"raw": readings["sound"]}


def _tier_label(free_ram):
    if free_ram >= 60_000: return "ALL"
    if free_ram >= 30_000: return "SKIP_P4"
    if free_ram >= 10_000: return "SKIP_P3_P4"
    return "EMERGENCY"


# ─────────────────────────────────────────────────────────────────────────────
# HTTP request handling
# ─────────────────────────────────────────────────────────────────────────────

def poll():
    """
    Check for an HTTP client and respond if one is waiting.

    This function is non-blocking and should be called
    once during each scheduler cycle.
    """
    if _server_sock is None:
        return

    try:
        conn, addr = _server_sock.accept()
    except OSError:
        return   # no client waiting 

    try:
        conn.settimeout(2.0)

        request = conn.recv(256).decode("utf-8")
        path    = _parse_path(request)

        if path == "/data":
            body = json.dumps(_latest)

        elif path == "/health":
            body = json.dumps({
                "uptime_ms": time.ticks_diff(time.ticks_ms(), _start_time),
                "free_ram":  gc.mem_free(),
                "ip":        _ip,
            })

        else:
            body = json.dumps({"error": "not found"})

        response = (
            "HTTP/1.0 200 OK\r\n"
            "Content-Type: application/json\r\n"
            "Access-Control-Allow-Origin: *\r\n"   # allow dashboard on any origin
            "Content-Length: {}\r\n"
            "\r\n"
            "{}"
        ).format(len(body), body)

        conn.send(response.encode("utf-8"))

    except Exception as e:
        print("[server] Request error:", e)
    finally:
        conn.close()
        gc.collect()

# ─────────────────────────────────────────────────────────────────────────────
# HTTP path parser
# ─────────────────────────────────────────────────────────────────────────────

def _parse_path(raw_request):
    """
    Extract the requested path from an HTTP request.

    Returns:
        str: Requested URL path.
        "/" if the request cannot be parsed.
    """
    try:
        return raw_request.split(" ")[1]
    
    except Exception:
        return "/"