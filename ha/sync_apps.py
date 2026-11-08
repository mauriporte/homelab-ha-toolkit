# Keep the apps grids of a servers dashboard (built by servers_dashboard.py, possibly edited by hand since) in sync with
# the containers Home Assistant's Portainer integration knows: every new container gets a button (icon from selfh.st,
# guessed from the container name; Docker icon if none fits) and a row in the usage table. Containers listed in a
# server's "extra_containers" or "hidden" are left out (databases, sidecars). Buttons are kept in alphabetical order,
# and buttons/rows of deleted containers are removed (only while that server's Portainer answers for its other containers).
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
# icons for buttons drawn with a state-icon (Material Design names, always available in HA); everything else: mdi:docker
MDI = {"jellyfin": "mdi:jellyfish", "plex": "mdi:plex", "qbittorrent": "mdi:download", "transmission": "mdi:download",
       "sonarr": "mdi:television-classic", "radarr": "mdi:movie-open", "lidarr": "mdi:music", "prowlarr": "mdi:magnify",
       "jackett": "mdi:magnify", "jellyseerr": "mdi:movie-search", "overseerr": "mdi:movie-search", "immich": "mdi:image-multiple",
       "portainer": "mdi:anchor", "syncthing": "mdi:sync", "tailscale": "mdi:vpn", "tailscaled": "mdi:vpn", "gluetun": "mdi:shield-lock",
       "cloudflared": "mdi:cloud", "glances": "mdi:gauge", "uptimekuma": "mdi:heart-pulse", "kuma": "mdi:heart-pulse",
       "ollama": "mdi:brain", "homeassistant": "mdi:home-assistant", "nginx": "mdi:web", "dnsmasq": "mdi:dns",
       "flaresolverr": "mdi:fire", "stremio": "mdi:play-circle", "invidious": "mdi:youtube", "threadfin": "mdi:television",
       "tvheadend": "mdi:antenna", "postgres": "mdi:database", "redis": "mdi:database", "mariadb": "mdi:database"}
_icon_cache = {}


def icon_exists(slug):
    if slug not in _icon_cache:
        try:
            _icon_cache[slug] = urllib.request.urlopen(urllib.request.Request(ICONS.format(slug), method="HEAD"), timeout=10).status == 200
        except Exception:
            _icon_cache[slug] = False
    return _icon_cache[slug]


def mdi_for(container):
    words = [w for w in re.split(r"[-_.]", container.lower()) if w]
    return next((MDI[w] for w in reversed(words) if w in MDI), "mdi:docker")


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
    devices = {d["id"]: d for d in call(type="config/device_registry/list")["result"]}
    out = {}  # (Portainer host, environment) -> {container: {kind: entity}}; one Portainer can serve several hosts
    for e in call(type="config/entity_registry/list")["result"]:
        if e.get("config_entry_id") not in entries or e.get("disabled_by"):
            continue
        host = entries[e["config_entry_id"]].split("//")[-1].split(":")[0]
        kind = "switch" if e["entity_id"].startswith("switch.") else e.get("translation_key")
        if kind in ("switch", "cpu_usage_total", "memory_usage", "container_state"):
            dev = devices.get(e.get("device_id")) or {}
            env = (devices.get(dev.get("via_device_id")) or {}).get("name") or "local"
            out.setdefault((host, env), {}).setdefault(dev.get("name"), {})[kind] = e["entity_id"]
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
    """The container switch a button shows: the first element with an entity (None = a broken button)."""
    return next((e.get("entity") for e in card.get("elements", []) if e.get("entity")), None)


def set_icon(pair, image, mdi):
    """Point a copied button at the new app's icon, whichever way the button draws it."""
    for c in pair:
        for e in c["elements"]:
            if e.get("type") == "state-icon":
                e["icon"] = mdi
            elif e.get("type") == "image" or "image" in e:
                e["image"] = image


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
    table = find(cards, lambda c: c.get("type") == "custom:app-usage-card" and isinstance(c.get("rows"), list))         or find(cards, lambda c: c.get("type") == "markdown" and "{% set rows =" in c.get("content", ""))
    if not stack:
        print(srv["path"], ": no apps grid found, skipped"); continue
    pe = [c for line in stack["cards"] for c in line["cards"] if c.get("type") == "picture-elements"]
    broken = [c for c in pe if not app_switch(c)]  # e.g. a button whose app element was deleted by hand
    for c in broken[::2]:
        print(f"{srv['path']}: - broken button (no switch)")
    pe = [c for c in pe if app_switch(c)]
    shown = {app_switch(c) for c in pe}
    hidden = set(srv.get("extra_containers") or []) | set(srv.get("hidden") or [])
    host = PMAP.get((srv["portainer_host"], srv.get("portainer_endpoint", "local")), {})
    exists = lambda m: states.get(m["switch"], {}).get("state") not in (None, "unavailable", "unknown")  # gone containers stay "unavailable"
    new = [(name, m) for name, m in sorted(host.items())
           if m.get("switch") and m["switch"] not in shown and name not in hidden and exists(m)
           and not name.endswith("-pre-casaos")]  # stopped copies kept for rollback after a CasaOS conversion
    pairs = [pe[i:i + 2] for i in range(0, len(pe), 2)]
    # deleted containers: their switch is gone from Portainer, or unavailable while the server answers for the others
    # (a server that is down makes every container unavailable: then nothing is removed)
    up = any(exists(m) for m in host.values() if m.get("switch"))
    live = {m["switch"] for m in host.values() if m.get("switch")}
    gone = {app_switch(p[0]) for p in pairs if up and (app_switch(p[0]) not in live
            or states.get(app_switch(p[0]), {}).get("state") in (None, "unavailable", "unknown"))}
    for sw in sorted(gone):
        print(f"{srv['path']}: - {states.get(sw, {}).get('attributes', {}).get('friendly_name', sw)} (container deleted)")
    pairs = [p for p in pairs if app_switch(p[0]) not in gone]
    names = {}  # switch -> label shown on the button (new ones get theirs below)
    name_of = lambda pair: (names.get(app_switch(pair[0])) or states.get(app_switch(pair[0]), {}).get("attributes", {})
                            .get("friendly_name", app_switch(pair[0]))).casefold()
    rows = None
    if table and table.get("type") == "custom:app-usage-card":
        rows = list(table["rows"])
    elif table:
        m = re.search(r"\{% set rows = (\[.*?\]) %\}", table["content"], re.S)
        rows = json.loads(m.group(1)) if m else None
    old_rows = copy.deepcopy(rows)
    if rows is not None and up:  # rows of deleted containers (their memory sensor is gone or unavailable)
        rows = [r for r in rows if states.get(r.get("m"), {}).get("state") not in (None, "unavailable", "unknown")]
    if rows is not None:  # kept buttons with no usage row (e.g. a container added by hand)
        by_switch = {m["switch"]: m for m in host.values() if m.get("switch")}
        for p in pairs:
            m = by_switch.get(app_switch(p[0]), {})
            if m.get("memory_usage") and m["memory_usage"] not in {r.get("m") for r in rows}:
                rows.append({"n": states.get(m["switch"], {}).get("attributes", {}).get("friendly_name", m["switch"]),
                             "s": m.get("container_state", ""), "c": m.get("cpu_usage_total", ""), "m": m["memory_usage"]})
    for r in old_rows or []:
        if r not in (rows or []):
            print(f"{srv['path']}: - usage row {r.get('n')}")
    for r in rows or []:
        if r not in (old_rows or []):
            print(f"{srv['path']}: + usage row {r.get('n')}")
    if (not new and not gone and not broken and rows == old_rows
            and [name_of(p) for p in pairs] == sorted(name_of(p) for p in pairs)):
        print(srv["path"], ": up to date"); continue
    for name, m in new:
        label, icon = guess(name)
        print(f"{srv['path']}: + {name} → «{label}» {icon.rsplit('/', 1)[-1]}")
        sw = m["switch"]
        if APPLY and CFG.get("rename_switches") and states.get(sw, {}).get("attributes", {}).get("friendly_name") != label:
            # name the container's device and clear the switch's own name: HA shows "<device> <entity name>", so naming
            # the switch itself gives "Immich Immich"
            dev = (call(type="config/entity_registry/get", entity_id=sw).get("result") or {}).get("device_id")
            if dev:
                call(type="config/device_registry/update", device_id=dev, name_by_user=label)
            call(type="config/entity_registry/update", entity_id=sw, name="")
        pair = json.loads(json.dumps(pairs[0]).replace(f'"{app_switch(pairs[0][0])}"', f'"{sw}"'))  # same look as the others
        set_icon(pair, icon, mdi_for(name))
        menu = srv.get("app_menu")  # server name in the casaos_apps integration: ⋯ settings popup on CasaOS apps
        has_menu = bool(menu) and call(type="casaos_apps/app", server=menu, container=name).get("success")
        for c in pair:  # the copied button's ⋯ belongs to the other app
            c["elements"] = [e for e in c["elements"] if e.get("type") != "custom:casaos-app-menu"]
            if has_menu:
                c["elements"].append({"type": "custom:casaos-app-menu", "server": menu, "container": name, "style": {"top": "10%", "left": "88%"}})
        for c in pair:  # stop confirmation names the new app (icon and label both ask)
            for e in c["elements"]:
                conf = e.get("tap_action", {}).get("confirmation")
                if conf:
                    conf["text"] = re.sub(r"(¿?\S+ ).*?(\?)$", lambda x: x.group(1) + label + x.group(2), conf["text"])
        pairs.append(pair)
        names[sw] = label
        if rows is not None and m.get("memory_usage"):
            rows.append({"n": label, "s": m.get("container_state", ""), "c": m.get("cpu_usage_total", ""), "m": m["memory_usage"]})
    pairs.sort(key=name_of)  # buttons in alphabetical order
    if not new and not gone and not broken:
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
    if rows is not None and table.get("type") == "custom:app-usage-card":
        table["rows"] = rows
    elif rows is not None:
        table["content"] = re.sub(r"\{% set rows = \[.*?\] %\}", "{% set rows = " + json.dumps(rows, ensure_ascii=False) + " %}",
                                  table["content"], count=1, flags=re.S)
    changed = True

if changed and APPLY:
    print("saved:", call(type="lovelace/config/save", url_path=URL_PATH, config=dash)["success"])
elif changed:
    print("dry run: add --apply to save")
