# Build the playlist tvheadend reads: Threadfin's channels, each wrapped in pipe:// ffmpeg (copy only, no transcode).
# Why: tvheadend's own IPTV HTTP client fails on Threadfin's ffmpeg-buffered (chunked) streams ("scan no data"),
# while ffmpeg reads them fine. Threadfin stream IDs are stable across restarts, so the file stays valid until the
# channel list changes (then run this again).
# Usage: [THREADFIN=host:34400] python tvheadend_pipe_m3u.py out.m3u
#   then copy out.m3u into tvheadend's config dir and set the IPTV automatic network URL to file:///config/out.m3u
# THREADFIN defaults to this machine's LAN address: the tvheadend container can't reach Threadfin on "localhost".
# Channels named in slow_probe.txt (next to out.m3u, or SLOW_PROBE=path; one name per line, # comments) get a longer
# probe (5 s / 5 MB): without it tvheadend registers some of them with audio only.
import os, re, socket, sys, urllib.request


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.0.2.1", 9))  # no packet is sent; this only picks the outgoing interface
        return s.getsockname()[0]
    finally:
        s.close()


TF = os.environ.get("THREADFIN") or f"{lan_ip()}:34400"
FFMPEG = os.environ.get("TVH_FFMPEG", "/usr/bin/ffmpeg")  # path inside the tvheadend container
out = sys.argv[1] if len(sys.argv) > 1 else "threadfin-pipe.m3u"
SLOW = os.environ.get("SLOW_PROBE") or os.path.join(os.path.dirname(os.path.abspath(out)), "slow_probe.txt")
slow = {l.strip() for l in open(SLOW, encoding="utf-8") if l.strip() and not l.startswith("#")} if os.path.exists(SLOW) else set()

src = urllib.request.urlopen(f"http://{TF}/m3u/threadfin.m3u", timeout=60).read().decode("utf-8")
lines, n, raised, name = [], 0, set(), ""
for line in src.splitlines():
    if line.startswith("#EXTINF"):
        name = line.rsplit(",", 1)[-1].strip()
    elif line.startswith("http"):
        url = re.sub(r"^http://[^/]+", f"http://{TF}", line.strip())  # Threadfin may write its Docker IP
        # short probing: ffmpeg otherwise analyses ~5 s of input before writing anything (measured: 0.8–1.3 s faster start)
        probe = "-analyzeduration 5000000 -probesize 5000000" if name in slow else "-analyzeduration 2000000 -probesize 1000000"
        line = f"pipe://{FFMPEG} -loglevel fatal {probe} -fflags +nobuffer -i {url} -c copy -f mpegts pipe:1"
        n += 1
        raised |= {name} & slow
    lines.append(line)
assert n, "no channels in Threadfin's playlist"
open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
print(n, "channels ->", out, f"| longer probe: {len(raised)} of {len(slow)} listed",
      "| not in Threadfin:", sorted(slow - raised) or "none")
