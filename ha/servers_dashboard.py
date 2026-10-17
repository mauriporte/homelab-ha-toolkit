# Build a Home Assistant dashboard that mimics the ZimaOS / CasaOS home screen: one view per server with
# CPU / RAM / temperature gauges, disks, a network graph, an apps grid (container icons in colour when running,
# grey when stopped, tap to start/stop with a confirmation before stopping) and a per-app CPU/RAM table.
# Data: any sensors for the host (Glances or System Monitor integrations) + the Portainer integration for containers.
# Usage: python servers_dashboard.py servers.json       (see servers.example.json)
import json, sys
from ha_ws import call

CFG = json.load(open(sys.argv[1] if len(sys.argv) > 1 else "servers.json", encoding="utf-8"))
DASH = CFG.get("dashboard", {})
URL_PATH = DASH.get("url_path", "dashboard-servers")
TXT = {"summary": "Resumen", "storage": "Almacenamiento", "network": "Red", "apps": "Apps", "usage": "Uso por app",
       "net_title": "Red (últimas 3 h)", "down": "Descarga", "up": "Subida", "uptime": "Encendido desde", "load": "Carga",
       "stop": "¿Detener {}?", "state": "Estado"} | CFG.get("labels", {})
BLANK = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="

states = {s["entity_id"]: s for s in call(type="get_states")["result"]}
unit = lambda e: states.get(e, {}).get("attributes", {}).get("unit_of_measurement")


def pick(entity):
    """`ram` may list several sensors (System Monitor/Glances expose MiB and %): use the one in %."""
    if isinstance(entity, list):
        return next((e for e in entity if unit(e) == "%"), entity[0])
    return entity


def portainer_map():
    """host|container -> {switch, cpu_usage_total, memory_usage, container_state} from the Portainer integration."""
    entries = {c["entry_id"]: c["title"] for c in call(type="config_entries/get")["result"] if c["domain"] == "portainer"}
    devices = {d["id"]: d["name"] for d in call(type="config/device_registry/list")["result"]}
    out = {}
    for e in call(type="config/entity_registry/list")["result"]:
        if e.get("config_entry_id") not in entries or e.get("disabled_by"):
            continue
        host = entries[e["config_entry_id"]].split("//")[-1].split(":")[0]
        kind = "switch" if e["entity_id"].startswith("switch.") else e.get("translation_key")
        if kind in ("switch", "cpu_usage_total", "memory_usage", "container_state"):
            out.setdefault(f"{host}|{devices.get(e.get('device_id'))}", {})[kind] = e["entity_id"]
    return out


PMAP = portainer_map()


def gauge(entity, name, kind="pct", rows=4):
    sev = {"pct": {"green": 0, "yellow": 60, "red": 85}, "temp": {"green": 0, "yellow": 65, "red": 80},
           "disk": {"green": 0, "yellow": 80, "red": 90}}[kind]
    return {"type": "gauge", "entity": entity, "name": name, "needle": kind != "disk", "min": 0, "max": 100,
            "severity": sev, "grid_options": {"columns": 4, "rows": rows}}


def app_cards(srv):
    cards = []
    for container, label, icon in srv.get("apps", []):
        sw = PMAP.get(f"{srv['portainer_host']}|{container}", {}).get("switch")
        if not sw:
            print("skip (no Portainer switch):", srv["portainer_host"], container)
            continue
        if CFG.get("rename_switches", True) and states.get(sw, {}).get("attributes", {}).get("friendly_name") != label:
            call(type="config/entity_registry/update", entity_id=sw, name=label)  # the button shows the switch name

        # picture-elements on a transparent square: same button size, smaller icon, name underneath
        def card(tap, cond):
            return {"type": "picture-elements", "image": BLANK, "grid_options": {"columns": 3}, "visibility": [cond],
                    "elements": [
                        {"type": "image", "entity": sw, "image": icon, "tap_action": tap, "hold_action": {"action": "more-info"},
                         "state_filter": {"off": "grayscale(100%) opacity(45%)"},
                         "style": {"top": "40%", "left": "50%", "width": "50%"}},
                        {"type": "state-label", "entity": sw, "attribute": "friendly_name", "tap_action": tap,
                         "hold_action": {"action": "more-info"},
                         "style": {"top": "85%", "left": "50%", "width": "92%", "font-size": "10px", "padding": "0",
                                   "text-align": "center", "white-space": "nowrap", "overflow": "hidden",
                                   "text-overflow": "ellipsis", "color": "var(--primary-text-color)"}}]}

        cards += [card({"action": "toggle", "confirmation": {"text": TXT["stop"].format(label)}},
                       {"condition": "state", "entity": sw, "state": "on"}),
                  card({"action": "toggle"}, {"condition": "state", "entity": sw, "state_not": "on"})]
    return cards


def usage_table(srv):
    labels = {c: l for c, l, _ in srv.get("apps", [])}
    rows = []
    for c in [a[0] for a in srv.get("apps", [])] + srv.get("extra_containers", []):
        m = PMAP.get(f"{srv['portainer_host']}|{c}", {})
        if m.get("memory_usage"):
            rows.append({"n": labels.get(c, c), "s": m.get("container_state", ""), "c": m.get("cpu_usage_total", ""),
                         "m": m["memory_usage"]})
    tpl = ("{% set rows = " + json.dumps(rows) + " %}\n"
           "{% set ns = namespace(l=[]) %}{% for r in rows %}"
           "{% set ns.l = ns.l + [{'n': r.n, 's': states(r.s), 'c': states(r.c) | float(0), 'm': states(r.m) | float(0)}] %}"
           "{% endfor %}\n"
           f"| App | {TXT['state']} | CPU | RAM |\n|:--|:--|--:|--:|\n"
           "{% for r in ns.l | sort(attribute='m', reverse=true) %}"
           "| {{ r.n }} | {{ '🟢' if r.s == 'running' else '⚪ ' ~ r.s }} | {{ '%.1f' | format(r.c) }} % | "
           "{{ '%.0f' | format(r.m) }} MB |\n{% endfor %}")
    return {"type": "markdown", "content": tpl, "grid_options": {"columns": "full"}}


def collapsible(path, key, heading, icon, cards, **section):
    """Section whose heading collapses it (input_boolean per section, created on first run)."""
    flag = f"input_boolean.servers_{path}_{key}"
    if flag not in states:
        call(type="input_boolean/create", name=f"Servers {path} {key}", icon="mdi:chevron-down", initial=True)
    shown = {"condition": "state", "entity": flag, "state": "on"}
    chev = lambda ic, st: {"type": "entity", "entity": flag, "show_state": False, "show_icon": True, "icon": ic,
                           "color": "primary", "tap_action": {"action": "toggle"},
                           "visibility": [{"condition": "state", "entity": flag, "state": st}]}
    head = {"type": "heading", "heading": heading, "icon": icon,
            "tap_action": {"action": "perform-action", "perform_action": "input_boolean.toggle", "target": {"entity_id": flag}},
            "badges": [chev("mdi:chevron-up", "on"), chev("mdi:chevron-down", "off")]}
    return dict({"type": "grid", "cards": [head] + [dict(c, visibility=c.get("visibility", []) + [shown]) for c in cards]},
                **section)


def server_view(srv):
    p = srv["path"]
    summary = [gauge(srv["cpu"], "CPU"), gauge(pick(srv["ram"]), "RAM")]
    if srv.get("temp"):
        summary.append(gauge(srv["temp"], "Temp.", "temp"))
    summary += [{"type": "tile", "entity": srv[k], "name": TXT[k], "grid_options": {"columns": 6}}
                for k in ("uptime", "load") if srv.get(k)]
    disks = [gauge(e, n, "disk", rows=5) for e, n in srv.get("disks", [])]  # 5 rows = network graph height
    if srv.get("disk_temp"):
        disks.append(gauge(srv["disk_temp"], "Temp. disco", "temp", rows=5))
    rx, tx = srv["net"]
    net = {"type": "history-graph", "title": TXT["net_title"], "hours_to_show": 3,
           "entities": [{"entity": rx, "name": TXT["down"]}, {"entity": tx, "name": TXT["up"]}],
           "grid_options": {"columns": "full", "rows": 5}}
    view = {"title": srv["title"], "path": p, "icon": srv.get("icon", "mdi:server"), "type": "sections", "max_columns": 4,
            "sections": [
                collapsible(p, "summary", TXT["summary"], "mdi:gauge", summary),
                collapsible(p, "storage", TXT["storage"], "mdi:harddisk", disks),
                collapsible(p, "network", TXT["network"], "mdi:lan", [net]),
                collapsible(p, "apps", TXT["apps"], "mdi:apps", app_cards(srv), column_span=4),
                collapsible(p, "usage", TXT["usage"], "mdi:table", [usage_table(srv)], column_span=4)]}
    if DASH.get("theme"):
        view["theme"] = DASH["theme"]
    return view


config = {"views": [server_view(s) for s in CFG["servers"]]}
if URL_PATH not in [d["url_path"] for d in call(type="lovelace/dashboards/list")["result"]]:
    call(type="lovelace/dashboards/create", url_path=URL_PATH, title=DASH.get("title", "Servers"),
         icon=DASH.get("icon", "mdi:server"), show_in_sidebar=True, require_admin=False, mode="storage")
print("saved:", call(type="lovelace/config/save", url_path=URL_PATH, config=config)["success"])
