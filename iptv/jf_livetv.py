# Jellyfin Live TV after a rebuild (run on the Jellyfin host):
#   python3 jf_livetv.py refresh   -> run Jellyfin's "Refresh Guide" task, wait for it, print channel/guide counts
#   python3 jf_livetv.py fav       -> re-mark favourites by name: FAV_SNAPSHOT (one name per line) + FAV_EXTRA json {"music": [...], "mtv": [...]}
# The API token is read from a temporary copy of jellyfin.db (deleted right after) and never printed.
import json, os, shutil, sqlite3, sys, tempfile, time, urllib.parse, urllib.request

JF, USER = os.environ.get("JF_URL", "http://localhost:8096"), os.environ["JF_USER_ID"]
DB = os.environ["JF_DB"]  # path to jellyfin.db (read from a temporary copy)
SNAP = os.environ.get("FAV_SNAPSHOT", "livetv-favourites.txt")   # never written here
EXTRA = os.environ.get("FAV_EXTRA", "fav_extra.json")


def token():
    d = tempfile.mkdtemp()
    try:
        for suf in ("", "-wal", "-shm"):
            if os.path.exists(DB + suf):
                shutil.copy2(DB + suf, os.path.join(d, "j.db" + suf))
        con = sqlite3.connect(os.path.join(d, "j.db"))
        t = con.execute("select AccessToken from ApiKeys order by DateCreated desc limit 1").fetchone()[0]
        con.close()
        return t
    finally:
        shutil.rmtree(d, ignore_errors=True)


TOK = token()


def api(method, path, **q):
    url = JF + path + ("?" + urllib.parse.urlencode(q) if q else "")
    req = urllib.request.Request(url, method=method, headers={"Authorization": f'MediaBrowser Token="{TOK}"'})
    with urllib.request.urlopen(req, timeout=120) as r:
        body = r.read()
        return json.loads(body) if body else None


def channels():
    return api("GET", "/LiveTv/Channels", userId=USER, limit=5000)["Items"]


if sys.argv[1] == "refresh":
    task = next(t for t in api("GET", "/ScheduledTasks") if t.get("Key") == "RefreshGuide")
    api("POST", f"/ScheduledTasks/Running/{task['Id']}")
    t0 = time.time()
    time.sleep(10)
    while time.time() - t0 < 3600:
        st = next(t for t in api("GET", "/ScheduledTasks") if t["Id"] == task["Id"])
        if st.get("State") == "Idle":
            break
        time.sleep(15)
    last = st.get("LastExecutionResult") or {}
    ch = channels()
    with_guide = sum(1 for c in ch if c.get("CurrentProgram"))
    with_image = sum(1 for c in ch if (c.get("ImageTags") or {}).get("Primary"))
    print(f"guide refresh: {last.get('Status')} in {int(time.time() - t0)} s | channels {len(ch)} | "
          f"with a programme now {with_guide} | with a logo {with_image}")

elif sys.argv[1] == "fav":
    snap = [l.strip() for l in open(SNAP, encoding="utf-8") if l.strip()]
    extra = json.load(open(EXTRA, encoding="utf-8"))
    norm = lambda n: n.strip().replace('"', "'")  # Threadfin/tvheadend turn apostrophes into double quotes
    by_name = {}
    for c in channels():
        by_name.setdefault(norm(c["Name"]), c["Id"])
    snap = [norm(n) for n in snap]
    extra = {k: [norm(n) for n in v] for k, v in extra.items()}
    want = list(dict.fromkeys(snap + extra["music"] + extra["mtv"]))
    missing = [n for n in snap if n not in by_name]
    for n in want:
        if n in by_name:
            api("POST", f"/UserFavoriteItems/{by_name[n]}", userId=USER)
    total = api("GET", "/LiveTv/Channels", userId=USER, isFavorite="true", limit=0)["TotalRecordCount"]
    print(json.dumps({"favourites_now": total,
                      "snapshot_found": len(snap) - len(missing), "snapshot_missing": missing,
                      "music_added": sum(1 for n in extra["music"] if n in by_name and n not in snap),
                      "mtv_added": [n for n in extra["mtv"] if n in by_name and n not in snap],
                      "mtv_not_in_jellyfin": [n for n in extra["mtv"] if n not in by_name]}, ensure_ascii=False, indent=1))
