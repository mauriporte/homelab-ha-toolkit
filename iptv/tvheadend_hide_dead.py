# Play every enabled tvheadend channel one at a time, retry the ones that don't start once, then disable
# (not delete) the channels that never start, so clients such as Jellyfin stop listing them.
# Usage: TVH_URL=http://host:9981 TVH_USER=admin TVH_PASS=... python tvheadend_hide_dead.py [--dry-run] [--limit 35]
# Resumable: results go to tvh_start.jsonl; the disabled channels are listed in tvh_hidden.json
# (re-enable one with /api/idnode/save node=[{"uuid": ..., "enabled": true}]).
import json, os, sys, time, urllib.parse, urllib.request

H = os.environ.get("TVH_URL", "http://localhost:9981").rstrip("/")
pm = urllib.request.HTTPPasswordMgrWithDefaultRealm()
pm.add_password(None, H, os.environ["TVH_USER"], os.environ["TVH_PASS"])
op = urllib.request.build_opener(urllib.request.HTTPDigestAuthHandler(pm))  # stdlib only: runs on a bare ZimaOS python
LIMIT = float(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 35
post = lambda p, **d: json.loads(op.open(H + "/api" + p, urllib.parse.urlencode(d).encode(), timeout=120).read() or b"{}")


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
        with op.open(f"{H}/stream/channel/{uuid}", timeout=LIMIT) as r:
            return first_ts(iter(lambda: r.read(4096), b""), t0, LIMIT)
    except OSError:  # URLError, HTTPError and socket timeouts are all OSError
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
