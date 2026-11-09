# Play every tvheadend channel the way Jellyfin does (its own ffmpeg, same probe settings) and pass it only
# when BOTH video and audio arrive. Two at a time at most , one try each, resumable (av_check.jsonl).
# Usage: set -a; . ./tvh.env; set +a; python3 av_check.py [uuid ...]
import json, os, re, subprocess, sys, threading, time
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "slow_check.py")).read().split("def main")[0])  # tvh(), op, H
JF_CONTAINER = os.environ.get("JF_CONTAINER", "jellyfin")
TVH_HOST = os.environ.get("TVH_HOST_FOR_JELLYFIN", "")  # host:port Jellyfin's container uses to reach tvheadend

OUT = os.environ.get("AV_OUT", "av_check.jsonl")
START_LIMIT, PLAY = 60, 10  # seconds to start (tvheadend's max_timeout), seconds of playback that must carry video + audio
lock = threading.Lock()


def ticket_url(uuid):
    with op.open(f"{H}/playlist/ticket/channel/{uuid}", timeout=20) as r:
        url = [l for l in r.read().decode().splitlines() if l.startswith("http")][0]
    url = url.replace("&profile=pass", "")
    return url.replace("localhost:9981", TVH_HOST) if TVH_HOST else url


def parse(err):
    """(video KiB, audio KiB, stream kinds) from ffmpeg's stderr."""
    m = re.search(r"video:(\d+)\w*B audio:(\d+)\w*B", err)
    kinds = sorted(set(re.findall(r"Stream #0:\d+.*?: (Video|Audio)", err)))
    return (int(m.group(1)), int(m.group(2)), kinds) if m else (0, 0, kinds)


def check(c):
    t0 = time.time()
    lim = str(START_LIMIT + PLAY + 5)  # timeout runs inside the container: killing only the docker client left ffmpeg running
    cmd = ["timeout", "-k", "10", str(START_LIMIT + PLAY + 15), "docker", "exec", JF_CONTAINER, "timeout", "-k", "5", lim, "/usr/lib/jellyfin-ffmpeg/ffmpeg",
           "-hide_banner", "-nostats", "-analyzeduration", "2000000", "-probesize", "1G", "-f", "mpegts",
           "-i", ticket_url(c["uuid"]), "-t", str(PLAY), "-map", "0:v?", "-map", "0:a?", "-f", "null", "-"]  # decode: a picture must really arrive (copy fails on late SPS)
    err = subprocess.run(cmd, capture_output=True, text=True).stderr
    tail = [l for l in err.splitlines() if "ticket=" not in l][-3:]
    v, a, kinds = parse(err)
    ok = v > 0 and a > 0
    return {"uuid": c["uuid"], "number": c.get("number"), "name": c["name"], "ok": ok, "video_kib": v, "audio_kib": a,
            "streams": kinds, "secs": round(time.time() - t0, 1),
            "err": None if ok else tail, "why": None if ok else ("no video" if a and not v else "no audio" if v and not a else "nothing played")}


def worker(todo):
    while True:
        with lock:
            if not todo:
                return
            c = todo.pop(0)
        while sum(1 for i in tvh("/status/inputs").get("entries", []) if i.get("subs")) >= 2:  # both tuners in use
            time.sleep(5)
        r = check(c)
        with lock:
            open(OUT, "a", encoding="utf-8").write(json.dumps(r, ensure_ascii=False) + "\n")
            if not r["ok"]:
                print(f"FAIL {r['number']} {r['name']}: {r['why']}", flush=True)


assert parse("Stream #0:0[0x100]: Video: h264\nStream #0:1: Audio: aac\nvideo:120KiB audio:15KiB subtitle") == (120, 15, ["Audio", "Video"])
assert parse("Stream #0:0[0x100]: Audio: aac\nvideo:0KiB audio:15KiB")[:2] == (0, 15)

if __name__ == "__main__":
    done = {json.loads(l)["uuid"] for l in open(OUT, encoding="utf-8")} if os.path.exists(OUT) else set()
    ch = sorted((c for c in tvh("/channel/grid", limit=5000)["entries"] if c.get("enabled")), key=lambda c: c.get("number") or 0)
    if sys.argv[1:]:
        ch, done = [c for c in ch if c["uuid"] in sys.argv[1:]], set()
    todo = [c for c in ch if c["uuid"] not in done]
    n0 = len(todo)
    ts = [threading.Thread(target=worker, args=(todo,)) for _ in range(2)]
    [t.start() for t in ts]
    shown = 0
    while any(t.is_alive() for t in ts):
        time.sleep(30)
        with lock:
            if (n0 - len(todo)) // 100 > shown:
                shown = (n0 - len(todo)) // 100
                print(f"progress {shown * 100}/{n0}", flush=True)
    [t.join() for t in ts]
    rs = [json.loads(l) for l in open(OUT, encoding="utf-8")]
    print(f"done: {len(rs)} checked | ok {sum(r['ok'] for r in rs)} | failed {sum(not r['ok'] for r in rs)}", flush=True)
