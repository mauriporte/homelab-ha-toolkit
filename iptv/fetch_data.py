# Download the inputs build.py needs into <workdir>:
#   <workdir>/iptv_data/*.json   iptv-org API (channels, feeds, streams, guides, …)
#   <workdir>/iptv_epg/es_<CODE>.xml.gz   epgshare01 country guides used to recover guides by channel name
# Usage: python fetch_data.py <workdir> [EPGSHARE_CODES, default "ES1,AR1,UK1,US1"]
import os, sys, urllib.request

W = sys.argv[1]
codes = (sys.argv[2] if len(sys.argv) > 2 else "ES1,AR1,UK1,US1").split(",")
os.makedirs(f"{W}/iptv_data", exist_ok=True)
os.makedirs(f"{W}/iptv_epg", exist_ok=True)
get = lambda url, path: urllib.request.urlretrieve(url, path) and print("ok", path)
for name in ("channels", "feeds", "streams", "guides", "categories", "countries", "languages", "blocklist", "logos"):
    get(f"https://iptv-org.github.io/api/{name}.json", f"{W}/iptv_data/{name}.json")
for c in codes:
    try:
        get(f"https://epgshare01.online/epgshare01/epg_ripper_{c}.xml.gz", f"{W}/iptv_epg/es_{c}.xml.gz")
    except Exception as e:  # epgshare01 is flaky; build.py simply skips missing files
        print("failed", c, e)
