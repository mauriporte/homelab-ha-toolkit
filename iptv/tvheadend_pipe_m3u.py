# Build the playlist tvheadend reads: Threadfin's channels, each wrapped in pipe:// ffmpeg (copy only, no transcode).
# Why: tvheadend's own IPTV HTTP client fails on Threadfin's ffmpeg-buffered (chunked) streams ("scan no data"),
# while ffmpeg reads them fine. Threadfin stream IDs are stable across restarts, so the file stays valid until the
# channel list changes (then run this again).
# Usage: THREADFIN=host:34400 python tvheadend_pipe_m3u.py out.m3u
#   then copy out.m3u into tvheadend's config dir and set the IPTV automatic network URL to file:///config/out.m3u
import os, re, sys, requests

TF = os.environ.get("THREADFIN", "localhost:34400")
FFMPEG = os.environ.get("TVH_FFMPEG", "/usr/bin/ffmpeg")  # path inside the tvheadend container
out = sys.argv[1] if len(sys.argv) > 1 else "threadfin-pipe.m3u"

src = requests.get(f"http://{TF}/m3u/threadfin.m3u", timeout=60).text
lines, n = [], 0
for line in src.splitlines():
    if line.startswith("http"):
        url = re.sub(r"^http://[^/]+", f"http://{TF}", line.strip())  # Threadfin may write its Docker IP
        # short probing: ffmpeg otherwise analyses ~5 s of input before writing anything (measured: 0.8–1.3 s faster start)
        line = f"pipe://{FFMPEG} -loglevel fatal -analyzeduration 1000000 -probesize 500000 -fflags +nobuffer -i {url} -c copy -f mpegts pipe:1"
        n += 1
    lines.append(line)
assert n, "no channels in Threadfin's playlist"
open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
print(n, "channels ->", out)
