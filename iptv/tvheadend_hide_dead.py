# Play every enabled tvheadend channel one at a time, retry the ones that don't start once, then disable
# (not delete) the channels that never start, so clients such as Jellyfin stop listing them.
# Usage: TVH_URL=http://host:9981 TVH_USER=admin TVH_PASS=... python tvheadend_hide_dead.py [--dry-run] [--limit 35]
# Resumable: results go to tvh_start.jsonl; the disabled channels are listed in tvh_hidden.json
# (re-enable one with /api/idnode/save node=[{"uuid": ..., "enabled": true}]).
import json, os, sys, time, requests
from requests.auth import HTTPDigestAuth

H = os.environ.get("TVH_URL", "http://localhost:9981").rstrip("/")
A = HTTPDigestAuth(os.environ["TVH_USER"], os.environ["TVH_PASS"])
LIMIT = float(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 35
post = lambda p, **d: requests.post(H + "/api" + p, data=d, auth=A, timeout=120).json()


def first_ts(chunks, t0, limit, now=time.time):
    """Seconds until a chunk starts with MPEG-TS data (sync byte 0x47), or None after `limit` seconds."""
    for chunk in chunks:
        if b"\x47" in chunk[:200]:
            return round(now() - t0, 1)
        if now() - t0 > limit:
            return None
    return None


def play(uuid):
    t0 = time.time()
    try:
        with requests.get(f"{H}/stream/channel/{uuid}", auth=A, stream=True, timeout=(5, LIMIT)) as r:
            return first_ts(r.iter_content(4096), t0, LIMIT)
    except requests.RequestException:
        return None


def main():
    out, done = "tvh_start.jsonl", {}
    if os.path.exists(out):
        for line in open(out, encoding="utf-8"):
            r = json.loads(line)
            done[(r["uuid"], r["try"])] = r["t"]
    ch = [c for c in post("/channel/grid", limit=5000)["entries"] if c.get("enabled")]
    for attempt in (1, 2):  # a second try matters: most first-try failures are temporary
        todo = [c for c in ch if (c["uuid"], attempt) not in done and (attempt == 1 or done.get((c["uuid"], 1)) is None)]
        for i, c in enumerate(todo):
            done[(c["uuid"], attempt)] = t = play(c["uuid"])
            open(out, "a", encoding="utf-8").write(json.dumps({"uuid": c["uuid"], "name": c["name"], "try": attempt, "t": t}) + "\n")
            if i % 50 == 0:
                print(f"try {attempt}: {i}/{len(todo)}", flush=True)
    dead = [c for c in ch if done.get((c["uuid"], 1)) is None and done.get((c["uuid"], 2)) is None]
    json.dump([{"uuid": c["uuid"], "name": c["name"]} for c in dead], open("tvh_hidden.json", "w", encoding="utf-8"), indent=1)
    if dead and "--dry-run" not in sys.argv:
        post("/idnode/save", node=json.dumps([{"uuid": c["uuid"], "enabled": False} for c in dead]))
    print(f"tested {len(ch)} | never started {len(dead)} | {'not changed (dry run)' if '--dry-run' in sys.argv else 'disabled'}")


assert first_ts([b"\x00" * 10, b"\x47abc"], 0, 35, now=lambda: 2.0) == 2.0
assert first_ts([b"\x00"], 0, 35, now=lambda: 40.0) is None

if __name__ == "__main__":
    main()
