# EPG "extras" for Threadfin: guides that the iptv-org grabber cannot fetch from this line.
# - i.mjh.nz guides, downloaded straight from GitHub (i.mjh.nz itself is blocked on the ISP; GitHub is not)
# - epgshare01 country guides, for channels recovered by name
# Keeps only the channels in sources.json, renames them to the playlist's tvg-id (so Threadfin maps them by itself)
# and writes /out/extra.xml. Runs at start and then every INTERVAL_HOURS (default 12).
import copy, gzip, io, json, os, sys, time, urllib.request
import socket
import xml.etree.ElementTree as ET

# The container has no working IPv6 route: sites with AAAA records (epgshare01) hung until timeout. IPv4 only.
_gai = socket.getaddrinfo
socket.getaddrinfo = lambda *a, **k: [r for r in _gai(*a, **k) if r[0] == socket.AF_INET] or _gai(*a, **k)

SRC = json.load(open("/app/sources.json", encoding="utf-8"))  # {url: {xml_channel_id: [tvg_id, ...]}}
OUT = "/out/extra.xml"
EVERY = float(os.environ.get("INTERVAL_HOURS", "12")) * 3600


CACHE = "/out/cache"


def fetch(url):
    """Download a guide; on success keep a copy, on failure fall back to the last good copy (epgshare01 is flaky)."""
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, url.replace("://", "_").replace("/", "_"))
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (epg-extra)"})
    try:
        data = urllib.request.urlopen(req, timeout=45).read()
        with open(path + ".tmp", "wb") as f:
            f.write(data)
        os.replace(path + ".tmp", path)
    except Exception as e:
        if not os.path.exists(path):
            raise
        print(time.strftime("%F %T"), "using cached copy for", url, "-", e, flush=True)
        data = open(path, "rb").read()
    # a stream, so huge guides are parsed incrementally instead of held whole in memory
    return gzip.GzipFile(fileobj=io.BytesIO(data)) if data[:2] == b"\x1f\x8b" else io.BytesIO(data)


def build():
    tv = ET.Element("tv", {"generator-info-name": "epg-extra"})
    channels, programmes, done = [], [], set()
    for url, idmap in SRC.items():
        n = 0
        try:
            # streamed parse: keep only wanted elements, clear everything else as soon as it is read
            for _, el in ET.iterparse(fetch(url), events=("end",)):
                if el.tag == "channel":
                    for new in idmap.get(el.get("id"), []):  # one source channel may feed several playlist channels
                        if new not in done:
                            c = copy.deepcopy(el); c.set("id", new); channels.append(c); done.add(new); n += 1
                    el.clear()
                elif el.tag == "programme":
                    for new in idmap.get(el.get("channel"), []):
                        p = copy.deepcopy(el); p.set("channel", new); programmes.append(p)
                    el.clear()
        except Exception as e:  # one broken source must not empty the whole guide
            print(time.strftime("%F %T"), "FAILED", url, e, flush=True)
            continue
        print(time.strftime("%F %T"), f"{url.rsplit('/', 2)[-2:]} channels {n}", flush=True)
    tv.extend(channels); tv.extend(programmes)
    tmp = OUT + ".tmp"
    ET.ElementTree(tv).write(tmp, encoding="utf-8", xml_declaration=True)
    os.replace(tmp, OUT)  # Threadfin never reads a half-written file
    print(time.strftime("%F %T"), f"wrote {OUT}: {len(channels)} channels, {len(programmes)} programmes", flush=True)


while True:
    try:
        build()
    except Exception as e:
        print(time.strftime("%F %T"), "build failed:", e, file=sys.stderr, flush=True)
    time.sleep(EVERY)
