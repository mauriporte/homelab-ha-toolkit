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


ROWS = 4                       # height of the top row in grid rows (4 × 56 px + 3 gaps = 248 px)
ROW_PX = ROWS * 56 + (ROWS - 1) * 8
APPS_PER_LINE = 12             # 3-column app buttons in the 36-column (75 %) apps area


def height(px):
    """card-mod style that fixes a card's height (needs card-mod from HACS; without it cards keep their own size)."""
    return {"style": f"ha-card {{ height: {px}px !important; justify-content: center; }}"}


def group(path, key, heading, icon, cols):
    """Collapsible group: heading (tap or chevron toggles an input_boolean, created on first run) + visibility rule."""
    flag = f"input_boolean.servers_{path}_{key}"
    if flag not in states:
        call(type="input_boolean/create", name=f"Servers {path} {key}", icon="mdi:chevron-down", initial=True)
    chev = lambda ic, st: {"type": "entity", "entity": flag, "show_state": False, "show_icon": True, "icon": ic,
                           "color": "primary", "tap_action": {"action": "toggle"},
                           "visibility": [{"condition": "state", "entity": flag, "state": st}]}
    head = {"type": "heading", "heading": heading, "icon": icon, "grid_options": {"columns": cols},
            "tap_action": {"action": "perform-action", "perform_action": "input_boolean.toggle", "target": {"entity_id": flag}},
            "badges": [chev("mdi:chevron-up", "on"), chev("mdi:chevron-down", "off")]}
    return head, [{"condition": "state", "entity": flag, "state": "on"}]


def blank(vis):
    return {"type": "markdown", "content": " ", "visibility": vis,
            "card_mod": {"style": "ha-card { background: none !important; border: none !important; box-shadow: none !important; }"}}


def server_view(srv):
    p = srv["path"]
    plain = lambda c: {k: v for k, v in c.items() if k != "grid_options"}
    # top row, one full-width section: Summary (4 slots) | Storage (1 slot per disk) | Network (the rest)
    disks = [gauge(e, n, "disk") for e, n in srv.get("disks", [])]
    if srv.get("disk_temp"):
        disks.append(gauge(srv["disk_temp"], "Temp. disco", "temp"))
    slot = min(6, 36 // (4 + len(disks)))      # keep at least a quarter of the row for the network graph
    sum_cols, disk_cols = 4 * slot, slot * len(disks)
    net_cols = 48 - sum_cols - disk_cols
    h_sum, v_sum = group(p, "summary", TXT["summary"], "mdi:gauge", sum_cols)
    h_disk, v_disk = group(p, "storage", TXT["storage"], "mdi:harddisk", disk_cols)
    h_net, v_net = group(p, "network", TXT["network"], "mdi:lan", net_cols)
    gauges = [gauge(srv["cpu"], "CPU"), gauge(pick(srv["ram"]), "RAM")] + ([gauge(srv["temp"], "Temp.", "temp")] if srv.get("temp") else [])
    tiles = [{"type": "tile", "entity": srv[k], "name": TXT[k], "vertical": True, "card_mod": height((ROW_PX - 8) // 2)}
             for k in ("uptime", "load") if srv.get(k)]
    summary = {"type": "horizontal-stack", "visibility": v_sum, "grid_options": {"columns": sum_cols, "rows": ROWS},
               "cards": ([{"type": "vertical-stack", "cards": tiles}] if tiles else []) + [dict(plain(g), card_mod=height(ROW_PX)) for g in gauges]}
    rx, tx = srv["net"]
    net = {"type": "history-graph", "title": TXT["net_title"], "hours_to_show": 3, "visibility": v_net,
           "entities": [{"entity": rx, "name": TXT["down"]}, {"entity": tx, "name": TXT["up"]}],
           "grid_options": {"columns": net_cols, "rows": ROWS}}   # directly in the grid: a history-graph only resizes here
    top = {"type": "grid", "column_span": 4, "cards": [h_sum, h_disk, h_net, summary,
           *[dict(d, visibility=v_disk, grid_options={"columns": slot, "rows": ROWS}) for d in disks], net]}

    # apps (75 %) | usage table (25 %, no fixed rows so it grows instead of scrolling)
    h_apps, v_apps = group(p, "apps", TXT["apps"], "mdi:apps", 36)
    h_use, v_use = group(p, "usage", TXT["usage"], "mdi:table", 12)
    pairs = app_cards(srv)
    pairs = [pairs[i:i + 2] for i in range(0, len(pairs), 2)]   # each app = running/stopped pair, one visible
    lines = []
    for i in range(0, len(pairs), APPS_PER_LINE):
        chunk = pairs[i:i + APPS_PER_LINE]
        cards = [dict(plain(c), visibility=c["visibility"] + v_apps) for pair in chunk for c in pair]
        lines.append({"type": "horizontal-stack", "cards": cards + [blank(v_apps) for _ in range(APPS_PER_LINE - len(chunk))]})
    table = dict(usage_table(srv), visibility=v_use, grid_options={"columns": 12},
                 card_mod={"style": {"ha-markdown$": "td, th { white-space: nowrap; padding: 4px 6px !important; } table { width: 100%; }"}})
    apps = {"type": "grid", "column_span": 4,
            "cards": [h_apps, h_use, {"type": "vertical-stack", "cards": lines, "grid_options": {"columns": 36}}, table]}

    title = {"type": "heading", "heading": srv["title"], "icon": srv.get("icon", "mdi:server"), "grid_options": {"columns": "full"}}
    if srv.get("web_url"):
        title["badges"] = [{"type": "button", "text": TXT.get("open_web", "Open web"), "icon": "mdi:open-in-new",
                            "tap_action": {"action": "url", "url_path": srv["web_url"]}}]
    view = {"title": srv["title"], "path": p, "icon": srv.get("icon", "mdi:server"), "type": "sections", "max_columns": 4,
            "sections": [{"type": "grid", "column_span": 4, "cards": [title]}, top, apps]}
    if DASH.get("theme"):
        view["theme"] = DASH["theme"]
    return view


config = {"views": [server_view(s) for s in CFG["servers"]]}
if URL_PATH not in [d["url_path"] for d in call(type="lovelace/dashboards/list")["result"]]:
    call(type="lovelace/dashboards/create", url_path=URL_PATH, title=DASH.get("title", "Servers"),
         icon=DASH.get("icon", "mdi:server"), show_in_sidebar=True, require_admin=False, mode="storage")
print("saved:", call(type="lovelace/config/save", url_path=URL_PATH, config=config)["success"])
