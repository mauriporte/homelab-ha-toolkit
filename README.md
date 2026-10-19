# homelab-ha-toolkit

Small, practical scripts from a self-hosted homelab around **Home Assistant**: dashboards generated from
config, and an IPTV pipeline that turns the public [iptv-org](https://github.com/iptv-org/iptv) list into a
clean, guide-complete channel list for **Threadfin → Jellyfin** and **tvheadend → Kodi**.

All scripts talk to services over their APIs; nothing here is tied to a specific host. Configuration comes
from JSON files (`*.example.json` → copy and edit) or environment variables.

## `ha/` — Home Assistant dashboards

Requirements: `pip install websocket-client`, plus `HA_URL` (e.g. `http://homeassistant.local:8123`) and
`HA_TOKEN` (a long-lived access token) in the environment.

| Script | What it builds |
| --- | --- |
| `servers_dashboard.py servers.json` | A **ZimaOS/CasaOS-style "Servers" dashboard**, one view per server: a title row (optional "Open web" button via `web_url`); one row with **Summary** (uptime over load, CPU/RAM/temperature gauges), **Storage** (a gauge per disk) and a 3-hour **Network** graph, all the same height; then the **apps grid** (75 %: container icons in colour when running, grey when stopped; tap to start/stop, with a confirmation before stopping) beside a per-app CPU/RAM **table** (25 %, grows to fit, sorted by memory). Every group is collapsible. Equal heights need **card-mod** (HACS → Frontend); without it the layout still works, only heights differ. Host metrics from the **Glances** or **System Monitor** integrations, containers from the **Portainer** integration. |
| `android_tv_remote.py tv_remote.json` | A collapsible **Android/Google TV remote** section: status tile, D-pad, volume, play/pause, power and one-tap app launchers (by package name), using the official Android TV Remote integration. |
| `ha_ws.py` | The tiny WebSocket client both scripts use: `from ha_ws import call; call(type="get_states")`. |

Notes for the servers dashboard:
- The apps grid labels each button with the Portainer switch's name; with `"rename_switches": true` the
  script renames each container switch to your app label (only the display name).
- On a Raspberry Pi, per-container RAM reads 0 unless the kernel has the memory cgroup enabled
  (`cgroup_enable=memory` in the boot cmdline).
- Glances reports temperatures in your HA unit system; switch them to °C per entity if needed.

## `iptv/` — iptv-org → Threadfin → Jellyfin / tvheadend → Kodi

The selection rules live in `build.py` (edit them to taste). As shipped: Spanish and English channels;
no local US stations (only national networks and streaming news); max 1080p; one stream per channel; no
religious, teleshopping, tarot or local-news channels; geo-blocked streams dropped; Spain and Argentina kept
even without a guide, everything else only if a guide exists (iptv-org guides, or recovered by channel name
from the epgshare01 country guides).

| Step | Script |
| --- | --- |
| 1. Download inputs | `python fetch_data.py <workdir> [ES1,AR1,UK1,US1]` — iptv-org API JSON + epgshare01 country guides |
| 2. Select channels | `python build.py <workdir>` → `iptv_final.json` |
| 3. Probe streams | `python probe.py <workdir> <mode>` — deep check (playlists, segments, AES keys, gzip), resumable |
| 4. Write the playlist | `python write_m3u.py <workdir>` → `iptv_out/playlist.m3u` (group per country / category, tvg-ids for the guide) |
| 5. Plan the guide sources | `python epg_plan.py <workdir> ids.json` — one guide source per channel, writes `epg-extra/sources.json` |
| 6. Extra guides service | `epg-extra/extra.py` — builds one XMLTV from i.mjh.nz (via GitHub) and epgshare01 for the channels the iptv-org grabber cannot fetch, with ids renamed to the playlist's tvg-ids; caches downloads, IPv4-only, refreshes every `INTERVAL_HOURS` |
| 7. Configure Threadfin | `THREADFIN=host:34400 EPG_URLS=http://host:3002/guide.xml,http://host:3003/extra.xml python threadfin_setup.py` — guides first, then playlist and per-group filters, so channels map to their guide automatically |
| 8. Start-time check | `THREADFIN=host:34400 python start_time.py` — time to first 64 KB of video per channel (retry once), to drop slow channels |
| 9. tvheadend input | `THREADFIN=host:34400 python tvheadend_pipe_m3u.py threadfin-pipe.m3u` — wraps each channel in `pipe://ffmpeg -c copy`, because tvheadend's own HTTP client fails on Threadfin's ffmpeg-buffered streams; point the IPTV automatic network at `file:///config/threadfin-pipe.m3u` |
| 10. Scan and map | `TVH_URL=http://host:9981 TVH_USER=… TVH_PASS=… python tvheadend_scan_map.py --start` |

Running `epg-extra` as a container (example):

```bash
docker run -d --name epg-extra --restart unless-stopped --network host \
  -v $PWD/epg-extra:/app -v /srv/epg-extra:/out -w /out -e INTERVAL_HOURS=12 \
  python:3.12-alpine sh -c "python -m http.server 3003 --directory /out & python /app/extra.py"
```

Lessons learned (they cost time):
- Set Threadfin's `httpThreadfinDomain`; otherwise it writes its Docker-internal IP into the playlist.
- Threadfin reads the buffer type **per playlist** (`files.m3u.<id>.buffer`); the global setting alone leaves it half-on.
- Threadfin can crash (`concurrent map read and map write`) when many streams start at once — keep
  tvheadend's `max_streams` at 2 while scanning, and measure start times one channel at a time.
- The ffmpeg pipe for tvheadend uses short probing (`-analyzeduration 2000000 -probesize 1000000 -fflags +nobuffer`):
  by default ffmpeg analyses ~5 s of input before writing anything. Going lower (1 s / 500 KB) was faster still, but
  some channels intermittently started with **audio only** because the video stream had not been seen yet.
- **Keep the pipe playlist file and tvheadend's muxes in sync.** Editing mux URLs through the API does not touch the
  file; on the next restart tvheadend compares them, deletes every mux and service, and recreates them. Channels
  survive but lose their services, names and numbers (Kodi plays nothing until a full rescan). If it happens, the
  channels still keep their XMLTV link, whose id is Threadfin's channel number, which is also each new mux's
  `channel_number`: re-attach channels to services by that number while the rescan runs.
- After the start-time filter, check every channel for a real **video and audio** stream (ffprobe through
  tvheadend, a few tries each): some streams open fast but carry only one of the two.
- Measure again later: start times vary with the time of day, and a second pass brought back ~20% of the "slow" ones.
- In tvheadend access entries, `change_profiles` with an empty profile list denies every subscription.

## License

MIT
