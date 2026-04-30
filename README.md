# Sonic Atlas

Sonic Atlas is a high-fidelity HTML prototype for a music knowledge system centered on guitar phrase libraries, chord progression study, arrangement practice, DJ foundations, and MuseScore-based notation workflows.

## Included

- `index.html`: the main prototype
- `sonic-atlas-desktop-v4.png`: desktop preview
- `sonic-atlas-mobile-v4.png`: mobile preview
- `data/radar-sources.json`: radar source watchlist
- `data/lick-radar.json`: generated lick radar feed
- `scripts/update-radar.mjs`: local radar updater for YouTube handle feeds and RSS

## Focus

- phrase archive for guitar licks and motifs
- chord lexicon for harmony and mood mapping
- daily coach for guitar, Logic, DJ, and MuseScore practice priorities
- score workflow bridging notation, MusicXML, MIDI, and Logic
- lick radar for pulling public lesson/video sources into the practice flow

## Radar Update

Run the local updater with:

```bash
NODE_PATH=/Users/jimlin/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules \
/Users/jimlin/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node \
scripts/update-radar.mjs
```

Notes:

- `youtube_handle` sources are supported by resolving the public channel page and then reading the official YouTube RSS feed.
- `rss` sources are supported directly.
- Instagram is scaffolded as a source slot, but not automatically scraped in this version because public access is brittle and often requires API/auth decisions.
