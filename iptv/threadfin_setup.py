# Configure Threadfin through its websocket API (/data/), the same commands its web UI sends.
# Order matters: guides first, then the playlist + filters, so channels whose tvg-id exists in a guide are
# activated and mapped by Threadfin itself; channels left without a guide get Threadfin's dummy guide.
import base64, io, json, os, socket, sys, time

TF = os.environ.get("THREADFIN", "localhost:34400")         # host:port of Threadfin
GUIDES = os.environ.get("EPG_URLS", "http://localhost:3002/guide.xml,http://localhost:3003/extra.xml").split(",")

GROUPS = [("España", "100"), ("Argentina", "300"), ("Reino Unido", "500"), ("EE. UU.", "600"),
          ("Otros · Noticias", "1000"), ("Otros · Deportes", "1100"), ("Otros · Cine", "1200"),
          ("Otros · Series", "1300"), ("Otros · Entretenimiento", "1400"), ("Otros · Documentales", "1500"),
          ("Otros · Infantil", "1600"), ("Otros · Música", "1700"), ("Otros · Estilo de vida", "1800"),
          ("Otros · General", "1900")]


def frame(data, mask=None):
    """One masked client text frame (RFC 6455)."""
    mask = mask or os.urandom(4)
    n = len(data)
    head = bytes([0x81, 0x80 | n]) if n < 126 else bytes([0x81, 0xFE]) + n.to_bytes(2, "big") if n < 65536 \
        else bytes([0x81, 0xFF]) + n.to_bytes(8, "big")
    return head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data))


def read_msg(f):
    """Read one whole data message (joins continuation frames, skips ping/pong)."""
    out = b""
    while True:
        h = f.read(2)
        if len(h) < 2:
            raise SystemExit("websocket closed by Threadfin")
        fin, op, n = h[0] & 0x80, h[0] & 0x0F, h[1] & 0x7F
        if n >= 126:
            n = int.from_bytes(f.read(2 if n == 126 else 8), "big")
        mask = f.read(4) if h[1] & 0x80 else None
        data = f.read(n)
        if mask:
            data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        if op == 8:
            raise SystemExit("websocket closed by Threadfin")
        if op in (9, 10):  # shortcut: pings are not answered, fine for one request per connection
            continue
        out += data
        if fin:
            return out


def cmd(payload, wait=600):
    # stdlib websocket (no `websocket` module needed): one connection per command
    host, port = TF.rsplit(":", 1)
    s = socket.create_connection((host, int(port)), timeout=wait)
    try:
        key = base64.b64encode(os.urandom(16)).decode()
        s.sendall((f"GET /data/ HTTP/1.1\r\nHost: {TF}\r\nOrigin: http://{TF}\r\nUpgrade: websocket\r\n"
                   f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        f = s.makefile("rb")
        status = f.readline()
        if b" 101 " not in status:
            raise SystemExit(f"websocket refused: {status.decode(errors='replace').strip()}")
        while f.readline() not in (b"\r\n", b""):
            pass
        s.sendall(frame(json.dumps(payload).encode()))
        r = json.loads(read_msg(f))
    finally:
        s.close()
    if not r.get("status", True) or r.get("error"):
        raise SystemExit(f"{payload['cmd']} failed: {r.get('error')}")
    return r


assert read_msg(io.BytesIO(frame(b"hi"))) == b"hi"
assert read_msg(io.BytesIO(frame(b"x" * 70000))) == b"x" * 70000  # 64-bit length path

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
