# Configure Threadfin through its websocket API (/data/), the same commands its web UI sends.
# Order matters: guides first, then the playlist + filters, so channels whose tvg-id exists in a guide are
# activated and mapped by Threadfin itself; channels left without a guide get Threadfin's dummy guide.
import json, os, sys, time, websocket

TF = os.environ.get("THREADFIN", "localhost:34400")         # host:port of Threadfin
GUIDES = os.environ.get("EPG_URLS", "http://localhost:3002/guide.xml,http://localhost:3003/extra.xml").split(",")

URL = f"ws://{TF}/data/"
GROUPS = [("España", "100"), ("Argentina", "300"), ("Reino Unido", "500"), ("EE. UU.", "600"),
          ("Otros · Noticias", "1000"), ("Otros · Deportes", "1100"), ("Otros · Cine", "1200"),
          ("Otros · Series", "1300"), ("Otros · Entretenimiento", "1400"), ("Otros · Documentales", "1500"),
          ("Otros · Infantil", "1600"), ("Otros · Música", "1700"), ("Otros · Estilo de vida", "1800"),
          ("Otros · General", "1900")]


def cmd(payload, wait=600):
    ws = websocket.create_connection(URL, timeout=wait)
    ws.send(json.dumps(payload)); r = json.loads(ws.recv()); ws.close()
    if not r.get("status", True) or r.get("error"):
        raise SystemExit(f"{payload['cmd']} failed: {r.get('error')}")
    return r


step = sys.argv[1] if len(sys.argv) > 1 else "all"

if step in ("all", "settings"):
    cmd({"cmd": "saveSettings", "settings": {"epgSource": "XEPG", "tuner": 4, "buffer": "-", "files.update": True,
                                             "update": ["0530", "1730"], "xepg.replace.missing.images": True}})
    print("settings saved")

if step in ("all", "xmltv"):
    have = {v.get("file.source") for v in cmd({"cmd": "getServerConfig"})["settings"]["files"]["xmltv"].values()}
    for name, src in zip(("iptv-org (grabber)", "extras (GitHub + epgshare01)"), GUIDES):
        if src not in have:
            cmd({"cmd": "saveFilesXMLTV", "files": {"xmltv": {"-": {"name": name, "description": "", "file.source": src}}}})
            print("guide added:", name)

if step in ("all", "m3u"):
    have = {v.get("file.source") for v in cmd({"cmd": "getServerConfig"})["settings"]["files"]["m3u"].values()}
    src = "/home/threadfin/conf/playlist.m3u"
    if src not in have:
        cmd({"cmd": "saveFilesM3U", "files": {"m3u": {"-": {"name": "playlist", "description": "filtered iptv-org list",
                                                            "file.source": src, "tuner": 4}}}})
        print("playlist added")

if step in ("all", "filters"):
    have = {v.get("filter") for v in (cmd({"cmd": "getServerConfig"})["settings"].get("filter") or {}).values()}
    for g, start in GROUPS:
        if g in have:
            continue
        cmd({"cmd": "saveFilter", "filter": {"-1": {"active": True, "caseSensitive": False, "liveEvent": False,
                                                     "description": "", "exclude": "", "include": "", "filter": g,
                                                     "name": g, "type": "group-title", "startingNumber": start,
                                                     "x-category": ""}}})
        print("filter:", g, "from", start)

if step in ("all", "dummy"):
    xepg = cmd({"cmd": "getServerConfig"})["xepg"]
    chans = xepg.get("epgMapping") or xepg
    changed = 0
    for cid, ch in chans.items():
        if isinstance(ch, dict) and not ch.get("x-active"):
            ch["x-active"] = True; ch["x-xmltv-file"] = "Threadfin Dummy"; ch["x-mapping"] = "60_Minutes"; changed += 1
    if changed:
        cmd({"cmd": "saveEpgMapping", "epgMapping": chans})
    print("channels activated with the dummy guide:", changed)

if step in ("all", "status"):
    ci = cmd({"cmd": "getServerConfig"})["clientInfo"]
    print({k: ci.get(k) for k in ("epgSource", "streams", "m3u-url", "xepg-url", "errors", "totalPlaylist")})
