#!/usr/bin/env bash
# pull_captions.sh — yt-dlp wrapper for T-006's YouTube captions ingest.
#
# Usage: scripts/pull_captions.sh <channel_url> <outdir>
#
# Pulls English auto/manual captions + metadata (no video) for every video on
# a channel into <outdir>, writing one <stem>.info.json + one or more
# <stem>.<lang>.vtt per video (yt-dlp's default output template embeds the
# title and id: "<title> [<id>].info.json"). onrecord.ingest.youtube's
# parse_video_dir() consumes that directory offline — this script never
# touches that code path.
#
# - Resumable: --download-archive records pulled video ids in
#   <outdir>/.download-archive.txt, so re-running against the same <outdir>
#   skips ids already pulled instead of re-fetching them.
# - Polite: --sleep-requests 1.5 throttles request rate between videos.
# - --ignore-errors keeps one bad video in an otherwise-good channel from
#   aborting the whole batch.
# - corpus/registry.yaml's youtube_channels entries are best-guess
#   (verified: false — see .tdd-swarm/LESSONS.md). A channel handle that
#   fails to resolve is *data*, not a crash: this script does not use
#   `set -e`, so a yt-dlp failure is caught, logged as a WARNING on stderr
#   naming the channel url, and surfaced via a clean non-zero exit code —
#   never a raw stack trace — so a caller looping over multiple channels can
#   record the failure and continue to the next one.

set -uo pipefail

usage() {
    echo "Usage: $(basename "$0") <channel_url> <outdir>" >&2
}

if [ "$#" -ne 2 ]; then
    usage
    exit 1
fi

channel_url="$1"
outdir="$2"

if ! command -v yt-dlp >/dev/null 2>&1; then
    echo "pull_captions.sh: WARNING: yt-dlp not found on PATH — skipping ${channel_url}" >&2
    exit 1
fi

mkdir -p "$outdir"
archive_file="${outdir}/.download-archive.txt"

yt-dlp \
    --skip-download \
    --write-auto-subs \
    --write-subs \
    --sub-langs 'en.*' \
    --write-info-json \
    --download-archive "$archive_file" \
    --sleep-requests 1.5 \
    --ignore-errors \
    --output "%(title)s [%(id)s].%(ext)s" \
    --paths "$outdir" \
    "$channel_url"
status=$?

if [ "$status" -ne 0 ]; then
    echo "pull_captions.sh: WARNING: yt-dlp exited ${status} for ${channel_url} (channel handle resolution failure or partial-batch error) — logged, not fatal" >&2
fi

exit "$status"
