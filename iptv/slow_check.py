# Nightly watchlist check for slow-start Live TV channels: keep them, but remove any that ever fails to start.
# Run it from a systemd timer with TVH_USER/TVH_PASS in an EnvironmentFile (root-only); never put the login in the repo.
# One channel at a time through tvheadend, one try each (no retries), up to 60 s to start (tvheadend's own max_timeout).
# A failed channel is deleted from tvheadend's channel list (its service stays, re-map to restore) and from Jellyfin,
# and marked "# removed <date>" in the watchlist. Stops at 05:30 and resumes from the next channel the following night.
# Safety: if 5 tests in a row fail, nothing from that run is removed (a line or server problem, not the channels).
import datetime, json, os, sys, time, urllib.parse, urllib.request

D = os.environ.get("IPTV_DIR", ".")
LIST = os.environ.get("WATCHLIST", os.path.join(D, "livetv-slow-watchlist.txt"))  # lines: name<TAB>channel uuid
POS, LOG = os.path.join(D, "slow_check.pos"), os.path.join(D, "slow_check.log")
H = os.environ.get("TVH_URL", "http://localhost:9981").rstrip("/")
LIMIT, STOP_AT, STREAK = 60, (5, 30), 5

pm = urllib.request.HTTPPasswordMgrWithDefaultRealm()
pm.add_password(None, H, os.environ["TVH_USER"], os.environ["TVH_PASS"])
op = urllib.request.build_opener(urllib.request.HTTPDigestAuthHandler(pm))


def log(msg):
    open(LOG, "a", encoding="utf-8").write(time.strftime("%Y-%m-%d %H:%M ") + msg + "\n")


def tvh(path, **data):
    body = urllib.parse.urlencode(data).encode()
    with op.open(H + "/api" + path, body, timeout=120) as r:
        return json.loads(r.read() or b"{}")


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
    except Exception:
        return None


def remove(failed):
    exec(open(os.path.join(D, "jf_livetv.py")).read().split("if sys.argv[1] ==")[0], globals())  # Jellyfin api()/channels()
    tvh("/idnode/delete", uuid=json.dumps([u for u, _ in failed]))
    left = {c["name"] for c in tvh("/channel/grid", limit=5000)["entries"]}
    norm = lambda n: n.strip().replace('"', "'")
    gone = {norm(n) for _, n in failed if n not in left}  # never touch a Jellyfin name another tvheadend channel still uses
    for c in channels():
        if norm(c["Name"]) in gone:
            api("DELETE", "/Items/" + c["Id"])
    day = datetime.date.today().isoformat()
    uu = {u for u, _ in failed}
    lines = open(LIST, encoding="utf-8").read().splitlines()
    out = [f"# removed {day} (did not start in {LIMIT} s): {l}" if l and not l.startswith("#") and l.split("\t")[-1] in uu else l
           for l in lines]
    open(LIST, "w", encoding="utf-8").write("\n".join(out) + "\n")
    log("REMOVED " + ", ".join(n for _, n in failed))


def main():
    todo = [l.split("\t") for l in open(LIST, encoding="utf-8").read().splitlines() if l and not l.startswith("#")]
    live = {c["uuid"] for c in tvh("/channel/grid", limit=5000)["entries"]}
    todo = [(u, n) for n, u in todo if u in live]
    start = int(open(POS).read()) % len(todo) if os.path.exists(POS) and todo else 0
    tested, failed, streak = 0, [], 0
    for i in range(len(todo)):
        if (datetime.datetime.now().hour, datetime.datetime.now().minute) >= STOP_AT and "--now" not in sys.argv:
            break
        if sum(1 for i in tvh("/status/inputs").get("entries", []) if i.get("subs")) >= 2:  # both tuners in use by someone watching
            log("both tuners busy, stopping for tonight")
            break
        u, n = todo[(start + i) % len(todo)]
        t = play(u)
        tested += 1
        open(POS, "w").write(str((start + i + 1) % len(todo)))
        if t is None:
            failed.append((u, n))
            streak += 1
            if streak >= STREAK:
                log(f"{STREAK} failures in a row ({', '.join(x for _, x in failed[-STREAK:])}): line or server problem, removing nothing")
                return
        else:
            streak = 0
        time.sleep(3)
    log(f"tested {tested} of {len(todo)} | failed {len(failed)}")
    if failed:
        remove(failed)


assert first_ts([b"\x00" * 10, b"\x47abc"], 0, 60, now=lambda: 2.0) == 2.0
assert first_ts([b"\x00"], 0, 60, now=lambda: 61.0) is None

if __name__ == "__main__":
    main()
