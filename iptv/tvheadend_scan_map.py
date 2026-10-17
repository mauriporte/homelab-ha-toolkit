# Wait for a tvheadend network scan to finish, then map every working service to a channel and report.
# Usage: TVH_URL=http://host:9981 TVH_USER=admin TVH_PASS=... python tvheadend_scan_map.py [--start]
#   --start  queues a full scan of the (first) network before waiting
import json, os, sys, time, collections, requests
from requests.auth import HTTPDigestAuth

B = os.environ.get("TVH_URL", "http://localhost:9981").rstrip("/") + "/api"
A = HTTPDigestAuth(os.environ["TVH_USER"], os.environ["TVH_PASS"])
post = lambda p, **d: requests.post(B + p, data=d, auth=A, timeout=120).json()

net = post("/mpegts/network/grid")["entries"][0]
if "--start" in sys.argv:
    post("/mpegts/network/scan", uuid=net["uuid"])
t0 = time.time()
while True:
    q = post("/mpegts/network/grid")["entries"][0].get("scanq_length", 0)
    if not q:
        break
    print(time.strftime("%H:%M"), "queue", q, flush=True)
    time.sleep(60)
mx = post("/mpegts/mux/grid", limit=5000)["entries"]
res = collections.Counter(m.get("scan_result") for m in mx)  # 1 = OK, 2 = FAIL
svc = [s["uuid"] for s in post("/mpegts/service/grid", limit=5000)["entries"]]
post("/service/mapper/save", node=json.dumps({"services": svc, "encrypted": False, "merge_same_name": False,
     "check_availability": False, "type_tags": False, "provider_tags": False, "network_tags": False}))
time.sleep(20)
ch = post("/channel/grid", limit=5000)
named = sum(1 for c in ch["entries"] if not c["name"].startswith("{"))
print(f"done in {int((time.time() - t0) / 60)} min | muxes OK {res.get(1, 0)} FAIL {res.get(2, 0)} | "
      f"services {len(svc)} | channels {ch['total']} (named {named})")
