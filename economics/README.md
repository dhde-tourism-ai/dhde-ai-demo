# Regional economics layer

`build_regional_economics.py` writes `data/regional_economics.json`. The
**Economics** toggle on the Fukui map (top right, off by default) draws it.
The React product reads the same file, so keep the shape stable.

## Rebuild

```bash
python economics/build_regional_economics.py --inline index.html   # JSON + inline offline copy in index.html
python economics/build_regional_economics.py --offline             # use the JTA snapshot, no download
python economics/build_regional_economics.py --check-source        # has the prefecture PDF changed?
```

Python 3.9+, standard library plus `requests`. The map fetches
`data/regional_economics.json`. When fetch is not available (for example
when the page is opened from `file://`), it uses the inline copy
(`window.REGIONAL_ECONOMICS_DATA`). Always run with `--inline` so the two
stay the same.

## Statuses

Every number is `{"value", "status", "source"}`.

| status | pill on the map | meaning |
|---|---|---|
| `real` | Real (green) | taken directly from a published source |
| `modelled` | Calculated (blue) | computed from real inputs with a formula below |
| `illustrative` | Illustrative (amber, dashed) | example value for layout only (none used today) |
| `pending` | Data pending (grey) | not available yet: `value` is `null` and the map shows `[pending]` |

No number is guessed. If it cannot be sourced, it is `pending`.

## Sources

1. **Fukui Prefecture, 観光客入込数（推計）2025** (released 12 Jun 2026),
   <https://www.pref.fukui.lg.jp/doc/kankou/fukuiken-kankoukyakusu_d/fil/024.pdf>
   (index: <https://www.pref.fukui.lg.jp/doc/kankou/fukuiken-kankoukyakusu.html>).
   Extracted with pypdf on 27 Sep 2026 and hard-coded in the script with the page number.
   `--check-source` compares the PDF's SHA-256 with the extracted copy.
   - p.1: 21,443k unique visitors (実人数); 2,385k overnight, so overnight share 11.1%
   - p.7: spend per visitor, day-tripper ¥5,546, overnight ¥30,221
   - p.8: total tourist spend ¥198.7bn (1,987億円)
   - p.9: per-municipality counts (kept as `visitors_irikomi_2025` for comparison)
   - p.12-13: per-site counts, used for node `visitors`:
     Tojinbo 651k, Katsuyama dinosaur museum area 1,562k, Rainbow Line 443k,
     Eiheiji 518k, Awara Onsen 658k (2024 values in `visitors_2024`).
2. **JTA digital tourism statistics (観光来訪者数)** via
   [code4fukui/japan-kanko-stat](https://github.com/code4fukui/japan-kanko-stat) `data/all.csv`.
   The same source is used in dhde-preprocessing-model PR #7. Region `visitors` is the sum of
   the latest 12 months in the file (currently 2025-09 to 2026-08), downloaded at build time.
   A snapshot is kept in the script for `--offline`. Calendar 2025 is in `visitors_calendar_2025`.
   Kanazawa City, Toyama City and the three prefectures are in `comparison_regions` (JSON only).
3. Supplied by the team brief and not re-checked in this build: foreign visitor spend
   ¥43,000 (BoJ Kanazawa, 17 Apr 2026); Kanazawa overnight share ~39% (Gabriella's pilot,
   benchmark); hotel occupancy Fukui 46.5% and Ishikawa 58.2% (JTA 2025).
4. Node annotations (parking and capacity) come from dhde-preprocessing-model
   `docs/site_capacity.md` (PR #6).

## Formulas

```
blended spend       = overnight_share x ¥30,221 + (1 - overnight_share) x ¥5,546
                    = 0.111 x 30,221 + 0.889 x 5,546  = ¥8,285 per visitor
revenue_yen         = visitors x blended spend                                  (modelled)
overnight_gap       = visitors x (0.39 - 0.111) x (¥30,221 - ¥5,546)            (modelled)
                      "if the Kanazawa overnight share were reached"
weather, idle_rooms = null                                                      (pending)
```

The prefecture's `revenue_yen` is the published ¥198.7bn (real). It is not
the formula result, which gives ¥177.7bn, because the prefecture uses
separate unit prices for residents and non-residents.

## Caveats (read before quoting)

- **Node counts are gross visits (延べ人数).** A visitor to three sites is
  counted three times, so node revenues overlap and must not be summed.
- **Region and node visitors use different definitions.** Regions use the
  JTA count and nodes use the prefecture's 入込数. For example, Awara City
  (JTA, 552k) is lower than Awara Onsen alone (入込, 658k).
- **The JTA series for Fukui jumps from March 2026.** Monthly counts rise
  2 to 6 times (Mihama: 3k in Feb 2026, 60k in Mar 2026). Tokyo and Kyoto
  do not show this jump. This is why the latest-12-month totals are well
  above calendar 2025 (Fukui City 2.33M against 1.27M). Check whether the
  source changed its method before quoting these figures.
- **One overnight share for every place.** The prefecture-wide 11.1% share
  and spend per visitor are applied to every place, which understates
  onsen towns and overstates day-trip sites.
- **Benchmark only.** The Kanazawa 39% share is a what-if taken from
  another city. It is not a target or a forecast.

## Still pending

| item | needs |
|---|---|
| Fukui Station node visitors | station gate or camera counts (the PDF only has Fukui City as a whole) |
| `opportunity_lost_yen.weather` | daily camera forecast residuals per node |
| `opportunity_lost_yen.idle_rooms` | room stock and daily occupancy per municipality |
| all `flows` | KDDI location data or survey v2 |
| Mikuni, Maruoka, Ono (nodes) and Ono City (region) | not priority nodes (see `docs/data_gaps.md` in dhde-preprocessing-model PR #6). The 2025 PDF values are kept as comments in the script |

## Contract additions

These keys go beyond the agreed contract. They are all additions, so a
reader that ignores them still works:

- nodes: `aliases`, `priority`, `visitors_2024`, `annotation`
- regions: `visitors_calendar_2025`, `visitors_irikomi_2025`
- flows: `from_coord` and `to_coord` for endpoints that are not nodes
- top level: `comparison_regions`, `external_points`, `visitor_window`
- assumptions: `hotel_occupancy_fukui`, `hotel_occupancy_ishikawa`

Node ids follow `index.html` (`station`, `rainbow`, `awara`). The
dhde-preprocessing-model keys (`fukui_station`, `rainbow_line`,
`awara_onsen`) are listed in `aliases`.
