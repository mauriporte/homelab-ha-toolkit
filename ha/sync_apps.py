# Keep the apps grids of a servers dashboard (built by servers_dashboard.py, possibly edited by hand since) in sync with
# the containers Home Assistant's Portainer integration knows: every new container gets a button (icon from selfh.st,
# guessed from the container name; Docker icon if none fits) and a row in the usage table. Containers listed in a
# server's "extra_containers" or "hidden" are left out (databases, sidecars). Buttons are kept in alphabetical order.
# Nothing else on the dashboard changes.
# Usage: python sync_apps.py servers.json [--dashboard url_path] [--apply]      (without --apply: show what would change)
import copy, json, re, sys, urllib.request
from ha_ws import call

CFG = json.load(open(sys.argv[1], encoding="utf-8"))
URL_PATH = sys.argv[sys.argv.index("--dashboard") + 1] if "--dashboard" in sys.argv else CFG["dashboard"]["url_path"]
APPLY = "--apply" in sys.argv
ICONS = "https://cdn.jsdelivr.net/gh/selfhst/icons/png/{}.png"
PER_LINE = 12
NOISE = {"linuxserver", "lscr", "big", "bear", "app", "web", "server", "client", "the", "docker", "casaos", "1", "2"}
NAMES = {"qbittorrent": "qBittorrent", "gluetun": "Gluetun VPN", "jellyseerr": "Jellyseerr", "flaresolverr": "FlareSolverr",
         "uptimekuma": "Uptime Kuma", "uptime-kuma": "Uptime Kuma", "tvheadend": "tvheadend", "epg": "EPG", "ddns": "DDNS",
         "dnsmasq": "dnsmasq", "rclone": "rclone", "glances": "Glances", "ttyd": "ttyd", "myip": "MyIP"}
_icon_cache = {}


def icon_exists(slug):
    if slug not in _icon_cache:
        try:
            _icon_cache[slug] = urllib.request.urlopen(urllib.request.Request(ICONS.format(slug), method="HEAD"), timeout=10).status == 200
        except Exception:
            _icon_cache[slug] = False
    return _icon_cache[slug]


def guess(container):
    """(label, icon url) from a container name like 'linuxserver-qbittorrent-gluetun-1'."""
    words = [w for w in re.split(r"[-_.]", container.lower()) if w and w not in NOISE and not w.isdigit()]
    old = " (old)" if "old" in words else ""  # e.g. a kept copy next to the current container
    words = [w for w in words if w != "old"]
    for w in reversed(words):  # the most specific word is usually last (…-qbittorrent-gluetun)
        for slug in (w, w.replace("d", "", 1) if w.endswith("d") else None):
            if slug and icon_exists(slug):
                return NAMES.get(w, w.capitalize()) + old, ICONS.format(slug)
    label = NAMES.get(words[-1]) if len(words) == 1 else None
    return (label or " ".join(NAMES.get(w, w.capitalize()) for w in words) or container) + old, ICONS.format("docker")


def portainer_map():
    entries = {c["entry_id"]: c["title"] for c in call(type="config_entries/get")["result"] if c["domain"] == "portainer"}
    devices = {d["id"]: d["name"] for d in call(type="config/device_registry/list")["result"]}
    out = {}
    for e in call(type="config/entity_registry/list")["result"]:
        if e.get("config_entry_id") not in entries or e.get("disabled_by"):
            continue
        host = entries[e["config_entry_id"]].split("//")[-1].split(":")[0]
        kind = "switch" if e["entity_id"].startswith("switch.") else e.get("translation_key")
        if kind in ("switch", "cpu_usage_total", "memory_usage", "container_state"):
            out.setdefault(host, {}).setdefault(devices.get(e.get("device_id")), {})[kind] = e["entity_id"]
    return out


def find(cards, test):
    for c in cards:
        if test(c):
            return c
        hit = find(c.get("cards", []), test)
        if hit:
            return hit
    return None


def app_switch(card):
    return card["elements"][0].get("entity")


states = {s["entity_id"]: s for s in call(type="get_states")["result"]}
PMAP = portainer_map()
dash = call(type="lovelace/config", url_path=URL_PATH)["result"]
changed = False
for srv in CFG["servers"]:
    view = next((v for v in dash["views"] if v.get("path") == srv["path"]), None)
    if not view:
        continue
    cards = [c for s in view["sections"] for c in s.get("cards", [])]
    stack = find(cards, lambda c: c.get("type") == "vertical-stack" and c.get("cards")
                 and all(x.get("type") == "horizontal-stack" for x in c["cards"])
                 and find(c["cards"], lambda y: y.get("type") == "picture-elements"))
    table = find(cards, lambda c: c.get("type") == "markdown" and "{% set rows =" in c.get("content", ""))
    if not stack:
        print(srv["path"], ": no apps grid found, skipped"); continue
    pe = [c for line in stack["cards"] for c in line["cards"] if c.get("type") == "picture-elements"]
    shown = {app_switch(c) for c in pe}
    hidden = set(srv.get("extra_containers") or []) | set(srv.get("hidden") or [])
    host = PMAP.get(srv["portainer_host"], {})
    exists = lambda m: states.get(m["switch"], {}).get("state") not in (None, "unavailable", "unknown")  # gone containers stay "unavailable"
    new = [(name, m) for name, m in sorted(host.items())
           if m.get("switch") and m["switch"] not in shown and name not in hidden and exists(m)]
    pairs = [pe[i:i + 2] for i in range(0, len(pe), 2)]
    names = {}  # switch -> label shown on the button (new ones get theirs below)
    name_of = lambda pair: (names.get(app_switch(pair[0])) or states.get(app_switch(pair[0]), {}).get("attributes", {})
                            .get("friendly_name", app_switch(pair[0]))).casefold()
    if not new and [name_of(p) for p in pairs] == sorted(name_of(p) for p in pairs):
        print(srv["path"], ": up to date"); continue
    rows = None
    if table:
        m = re.search(r"\{% set rows = (\[.*?\]) %\}", table["content"], re.S)
        rows = json.loads(m.group(1)) if m else None
    for name, m in new:
        label, icon = guess(name)
        print(f"{srv['path']}: + {name} → «{label}» {icon.rsplit('/', 1)[-1]}")
        sw = m["switch"]
        if APPLY and states.get(sw, {}).get("attributes", {}).get("friendly_name") != label:
            call(type="config/entity_registry/update", entity_id=sw, name=label)
        pair = copy.deepcopy(pairs[0])  # same look as the existing buttons
        txt = json.dumps(pair).replace(app_switch(pairs[0][0]), sw).replace(pairs[0][0]["elements"][0]["image"], icon)
        pair = json.loads(txt)
        for c in pair:  # stop confirmation names the new app
            conf = c["elements"][0].get("tap_action", {}).get("confirmation")
            if conf:
                conf["text"] = re.sub(r"(¿?\S+ ).*?(\?)$", lambda x: x.group(1) + label + x.group(2), conf["text"])
        pairs.append(pair)
        names[sw] = label
        if rows is not None and m.get("memory_usage"):
            rows.append({"n": label, "s": m.get("container_state", ""), "c": m.get("cpu_usage_total", ""), "m": m["memory_usage"]})
    pairs.sort(key=name_of)  # buttons in alphabetical order
    if not new:
        print(srv["path"], ": sorted alphabetically")
    # transparent filler keeps every button the same width on a short last line (hidden with the apps group)
    group_vis = [v for v in pe[0].get("visibility", []) if v.get("entity", "").startswith("input_boolean.")]
    blank = {"type": "markdown", "content": " ", "visibility": group_vis,
             "card_mod": {"style": "ha-card { background: none !important; border: none !important; box-shadow: none !important; }"}}
    lines = []
    for i in range(0, len(pairs), PER_LINE):
        chunk = pairs[i:i + PER_LINE]
        lines.append({"type": "horizontal-stack",
                      "cards": [c for p in chunk for c in p] + [copy.deepcopy(blank) for _ in range(PER_LINE - len(chunk))]})
    stack["cards"] = lines
    if rows is not None:
        table["content"] = re.sub(r"\{% set rows = \[.*?\] %\}", "{% set rows = " + json.dumps(rows, ensure_ascii=False) + " %}",
                                  table["content"], count=1, flags=re.S)
    changed = True

if changed and APPLY:
    print("saved:", call(type="lovelace/config/save", url_path=URL_PATH, config=dash)["success"])
elif changed:
    print("dry run: add --apply to save")
