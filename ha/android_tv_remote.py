# Add a collapsible remote-control section for an Android / Google TV to a sections dashboard:
# status tile, D-pad, volume, play/pause, power and one-tap app buttons (by package name).
# Uses the official Android TV Remote integration (remote.<tv>, media_player.<tv>) — no ADB needed.
# Usage: python android_tv_remote.py tv_remote.json     (see tv_remote.example.json). Idempotent.
import json, sys
from ha_ws import call

C = json.load(open(sys.argv[1] if len(sys.argv) > 1 else "tv_remote.json", encoding="utf-8"))
NAME, REMOTE, PLAYER = C["name"], C["remote"], C.get("media_player")
FLAG = f"input_boolean.{C.get('flag_id', 'remote_show_' + NAME.lower().replace(' ', '_'))}"
L = {"power": "On/Off", "up": "▲", "down": "▼", "left": "◀", "right": "▶", "ok": "OK", "back": "Back", "home": "Home",
     "mute": "Mute", "vol_down": "Vol −", "vol_up": "Vol +", "play": "Play/Pause"} | C.get("labels", {})

if FLAG not in {s["entity_id"] for s in call(type="get_states")["result"]}:
    call(type="input_boolean/create", name=FLAG.split(".")[1].replace("_", " "), icon="mdi:television", initial=True)


def key(name, icon, cmd):
    return {"type": "button", "name": name, "icon": icon, "show_state": False, "icon_height": "32px",
            "tap_action": {"action": "perform-action", "perform_action": "remote.send_command",
                           "target": {"entity_id": REMOTE}, "data": {"command": cmd}},
            "hold_action": {"action": "none"}}


def app(name, icon, package):
    return {"type": "button", "name": name, "icon": icon, "show_state": False, "icon_height": "32px",
            "tap_action": {"action": "perform-action", "perform_action": "remote.turn_on",
                           "target": {"entity_id": REMOTE}, "data": {"activity": package}},
            "hold_action": {"action": "none"}}


shown = [{"condition": "state", "entity": FLAG, "state": "on"}]
chev = lambda icon, st: {"type": "entity", "entity": FLAG, "show_state": False, "show_icon": True, "icon": icon,
                         "color": "primary", "tap_action": {"action": "toggle"},
                         "visibility": [{"condition": "state", "entity": FLAG, "state": st}]}
cards = [{"type": "heading", "heading": NAME, "icon": "mdi:television",
          "tap_action": {"action": "perform-action", "perform_action": "input_boolean.toggle", "target": {"entity_id": FLAG}},
          "badges": [chev("mdi:chevron-up", "on"), chev("mdi:chevron-down", "off")]}]
if PLAYER:
    cards.append({"type": "tile", "entity": PLAYER, "name": NAME, "state_content": ["state", "app_name"],
                  "grid_options": {"columns": "full"}, "visibility": shown})
cards.append({"type": "grid", "columns": 3, "square": False, "visibility": shown, "cards": [
    key(L["power"], "mdi:power", "POWER"), key(L["up"], "mdi:chevron-up", "DPAD_UP"), key(L["mute"], "mdi:volume-mute", "VOLUME_MUTE"),
    key(L["left"], "mdi:chevron-left", "DPAD_LEFT"), key(L["ok"], "mdi:circle-medium", "DPAD_CENTER"), key(L["right"], "mdi:chevron-right", "DPAD_RIGHT"),
    key(L["back"], "mdi:arrow-left", "BACK"), key(L["down"], "mdi:chevron-down", "DPAD_DOWN"), key(L["home"], "mdi:home", "HOME"),
    key(L["vol_down"], "mdi:volume-minus", "VOLUME_DOWN"), key(L["play"], "mdi:play-pause", "MEDIA_PLAY_PAUSE"), key(L["vol_up"], "mdi:volume-plus", "VOLUME_UP")]})
if C.get("apps"):
    cards.append({"type": "grid", "columns": 3, "square": False, "visibility": shown,
                  "cards": [app(n, i, p) for n, i, p in C["apps"]]})

cfg = call(type="lovelace/config", url_path=C["dashboard"])["result"]
sections = cfg["views"][C.get("view", 0)].setdefault("sections", [])
sections[:] = [s for s in sections if not (s.get("cards") and s["cards"][0].get("heading") == NAME)]
sections.append({"type": "grid", "cards": cards})
print("saved:", call(type="lovelace/config/save", url_path=C["dashboard"], config=cfg)["success"])
