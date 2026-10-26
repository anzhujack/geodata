#!/bin/sh
# Usage: sh update-geodata.sh OWNER/REPO /etc/dae
# Download a single immutable release, verify, then install. Reload manually.
set -eu
REPO=${1:?Usage: sh update-geodata.sh OWNER/REPO /absolute/data/directory}
DEST=${2:?Specify your actual dae/honk data directory}
case "$REPO" in *[!a-zA-Z0-9_./-]*|/*|*..*) echo 'Invalid repository' >&2; exit 1;; esac
case "$REPO" in */*) ;; *) echo 'Repository must be OWNER/REPO' >&2; exit 1;; esac
case "$DEST" in /*) ;; *) echo 'Use an absolute destination' >&2; exit 1;; esac
[ -d "$DEST" ] || { echo "Directory does not exist: $DEST" >&2; exit 1; }
command -v curl >/dev/null
command -v sha256sum >/dev/null
TMP=$(mktemp -d "$DEST/.geodata-update.XXXXXX")
trap 'rm -rf "$TMP"' EXIT HUP INT TERM
# Resolve latest once. Subsequent assets all use the same immutable tag.
LATEST=$(curl -fLsS --retry 3 --connect-timeout 20 --max-time 120 -o /dev/null -w '%{url_effective}' "https://github.com/$REPO/releases/latest")
PREFIX="https://github.com/$REPO/releases/tag/"
case "$LATEST" in "$PREFIX"*) TAG=${LATEST#"$PREFIX"};; *) echo "Unexpected release URL: $LATEST" >&2; exit 1;; esac
case "$TAG" in build-*[!a-zA-Z0-9_-]*|'') echo 'Invalid release tag' >&2; exit 1;; build-*) ;; *) echo 'Expected build-* release tag' >&2; exit 1;; esac
for FILE in geosite.dat geoip.dat manifest.json sha256sums.txt; do
  curl -fLsS --retry 3 --connect-timeout 20 --max-time 300 "https://github.com/$REPO/releases/download/$TAG/$FILE" -o "$TMP/$FILE"
done
# Only permit the three expected checksummed filenames; never arbitrary paths.
awk 'NF != 2 || length($1) != 64 || $1 ~ /[^0-9a-f]/ || ($2 != "geosite.dat" && $2 != "geoip.dat" && $2 != "manifest.json") {exit 1} END {if (NR != 3) exit 1}' "$TMP/sha256sums.txt"
(cd "$TMP" && sha256sum -c sha256sums.txt)
[ -s "$TMP/geosite.dat" ] && [ -s "$TMP/geoip.dat" ]
for FILE in geosite.dat geoip.dat; do
  if [ -f "$DEST/$FILE" ]; then cp -p "$DEST/$FILE" "$TMP/$FILE.previous"; fi
done
# Each rename is atomic, but the pair is not: avoid concurrent reloads during install.
restore() {
  for FILE in geosite.dat geoip.dat; do
    if [ -f "$TMP/$FILE.previous" ]; then cp -p "$TMP/$FILE.previous" "$DEST/$FILE"; else rm -f "$DEST/$FILE"; fi
  done
}
for FILE in geosite.dat geoip.dat; do
  chmod 644 "$TMP/$FILE"
  if ! mv -f "$TMP/$FILE" "$DEST/$FILE"; then restore; exit 1; fi
done
for FILE in geosite.dat geoip.dat; do
  if [ -f "$TMP/$FILE.previous" ]; then cp -p "$TMP/$FILE.previous" "$DEST/$FILE.previous"; fi
done
cp "$TMP/manifest.json" "$DEST/geodata-manifest.json"
printf 'Installed %s into %s. Reload your dae/honk service to activate.\n' "$TAG" "$DEST"
