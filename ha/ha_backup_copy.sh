#!/bin/sh
# Copy Home Assistant's local backups to another disk or machine and keep the newest few.
# For HA in a plain container (no Supervisor, so no network storage for backups): run this daily on any host that can
# read HA's backup folder (a local path or a mounted share), e.g. from cron or a systemd timer after HA's own backup.
#
#   SRC=/mnt/ha-config/backups DST=/mnt/spare/"HA Backup" KEEP=7 sh ha_backup_copy.sh
#
# Skips files still being written (changed in the last 10 minutes) and files already copied with the same size;
# copies to a .part name first, so a half-written copy never looks complete. Log: $DST/copy.log
SRC="${SRC:?set SRC to HA's backups folder}"
DST="${DST:?set DST to the folder to copy into}"
KEEP="${KEEP:-7}"
mkdir -p "$DST"
log() { echo "$(date "+%F %T") $*" >> "$DST/copy.log"; }
[ -d "$SRC" ] || { log "source not reachable: $SRC"; exit 1; }
n=0
for f in "$SRC"/*.tar; do
  [ -e "$f" ] || continue
  b=$(basename "$f")
  [ -n "$(find "$f" -mmin +10)" ] || continue
  [ -e "$DST/$b" ] && [ "$(stat -c %s "$f")" = "$(stat -c %s "$DST/$b")" ] && continue
  cp "$f" "$DST/$b.part" && mv "$DST/$b.part" "$DST/$b" && n=$((n+1)) && log "copied $b"
done
ls -1t "$DST"/*.tar 2>/dev/null | tail -n +$((KEEP+1)) | while read -r old; do rm -f "$old"; log "removed old $(basename "$old")"; done
log "done: $n new, $(ls -1 "$DST"/*.tar 2>/dev/null | wc -l) kept"
