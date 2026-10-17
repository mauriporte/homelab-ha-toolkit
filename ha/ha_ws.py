# Minimal Home Assistant WebSocket client: `from ha_ws import call; call(type="get_states")`.
# Environment: HA_URL (default http://homeassistant.local:8123) and HA_TOKEN (long-lived access token).
import json, os, subprocess
import websocket  # pip install websocket-client

URL = os.environ.get("HA_URL", "http://homeassistant.local:8123").rstrip("/")
TOKEN = os.environ.get("HA_TOKEN")
if not TOKEN and os.name == "nt":  # Windows: also read the user-level variable (shells started earlier may miss it)
    TOKEN = subprocess.run(["powershell", "-NoProfile", "-c", '[Environment]::GetEnvironmentVariable("HA_TOKEN","User")'],
                           capture_output=True, text=True).stdout.strip()
if not TOKEN:
    raise SystemExit("Set HA_TOKEN (Home Assistant long-lived access token)")

_ws = websocket.create_connection(URL.replace("http", "ws", 1) + "/api/websocket")
_ws.recv()
_ws.send(json.dumps({"type": "auth", "access_token": TOKEN}))
if json.loads(_ws.recv()).get("type") != "auth_ok":
    raise SystemExit("Home Assistant rejected the token")
_n = 0


def call(**msg):
    """Send one WebSocket command and return its result message."""
    global _n
    _n += 1
    msg["id"] = _n
    _ws.send(json.dumps(msg))
    while True:
        r = json.loads(_ws.recv())
        if r.get("id") == _n:
            return r
