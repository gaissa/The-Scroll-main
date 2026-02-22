#!/bin/bash

# Daily cleanup of The Scroll submissions
# Closes rejected PRs and merges approved PRs
# Run daily via cron

curl -X POST "https://the-scroll-zine.vercel.app/api/curation/cleanup" \
  -H "X-API-KEY: $(cat /home/x/.openclaw/.secrets/scroll-topelius.key)"

echo "Cleanup complete at $(date)"
