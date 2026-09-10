# Fukui / Hokuriku DHDE prototype

A single-file dashboard showing seasonal tourism demand across nine Fukui nodes,
wired to Fukui Prefecture open data rather than hardcoded numbers.

Distributed Human Data Engine · University of Fukui, Headquarters for Regional
Revitalization · Japan Science and Technology Agency Sakura Science Program.

## How to Run
1. Clone the repo
2. Run:
   
    python3 -m http.server 8080     # then open http://localhost:8080



## Layout

    index.html          the dashboard, self-contained (Leaflet is inlined)
    dhde_data.json      aggregated data, inlined into index.html as DHDE_DATA
    build_data.py       regenerates dhde_data.json from the raw CSVs
    inject_data.py      writes dhde_data.json into index.html
    fetch_sources.sh    downloads those raw CSVs from code4fukui
    verify.js           offline test: renders with every live source blocked
    verify_live.js      live test: fixtures in the real JMA / code4fukui formats

`dhde_data.json` is committed on purpose. It is 12 KB and it is what lets
`index.html` render instantly and work offline.

The raw CSVs are **not** committed: ~95 MB, owned by Code for Fukui, updated
daily. `fetch_sources.sh` pulls them.

## Refreshing the data

    ./fetch_sources.sh
    python3 build_data.py           # needs pandas + numpy
    python3 inject_data.py          # writes it into index.html
    npm install && npm run verify && npm run verify:live

The model fit stats, the per-node economic split and the measured headline tiles
are all read from `DHDE_DATA` at runtime, so a rebuild updates them on its own.
There is no hand-written figure left in the UI that a rebuild can invalidate.

Both must pass with zero page errors. `verify.js` deliberately runs with the
network unavailable, so it is also the offline-demo test.

## Where each number comes from

| Panel | Source |
|---|---|
| Node coordinates | `area.csv` (FTAS area master) |
| Visit volume (`actual`) | count of FTAS responses per node per season |
| Sentiment | mean `NPS` per node |
| Congestion tier | `不便さ` — share reporting they felt inconvenienced |
| Digital intent | share using online information sources |
| Per-node economic split | `エリア総消費額` — reported visitor spend |
| Hotel occupancy | booked rooms ÷ 576, 10 Awara Onsen hotels |
| Live response counter | `all-cnt.csv`, refreshed every 30 min |
| Live weather | JMA AMeDAS, nearest reporting station per node, every 10 min |
| `predicted` | OLS fitted in `build_data.py`, stats printed on build |

## What is still not measured

- **The index is response volume, not footfall.** FTAS collects a few dozen
  responses a day prefecture-wide. `actual` and `predicted` are a 0-100 index of
  sampled survey volume, a demand proxy. It is not a visitor headcount, and the
  UI must never present it as one.
- **Per-season weather is regional normals.** JMA gives live current conditions;
  there is no seasonal history source wired up, so scrubbing the timeline uses
  normals. Flagged in the JMA card and the caveat box.
- **¥11.96B and 865,917 are quoted**, from Khanzada & Takemoto (2026,
  arXiv:2603.21639). Only the per-node split of them is derived from this data.
- **Reroute corridors and scenario buttons are illustrative what-ifs.**

## Attribution and licence

Data: 福井県観光連盟 (Fukui Tourism Federation) via FTAS, published by
[Code for Fukui](https://github.com/code4fukui).

- [`fukui-kanko-survey`](https://github.com/code4fukui/fukui-kanko-survey) —
  **no LICENSE file and no stated terms.** Confirm reuse terms with the Fukui
  Tourism Federation before publishing this repo or the Pages site publicly.
- [`fukui-kanko-reservation`](https://github.com/code4fukui/fukui-kanko-reservation) — MIT.
- [JMA](https://www.jma.go.jp/) — see JMA's terms for its open data.
- Leaflet 1.9.4 (BSD-2-Clause), inlined in `index.html`.
- Basemap tiles © Esri. Routing by the public OSRM demo server, which is
  best-effort and not for production load.
