#!/usr/bin/env python3
"""Build data/regional_economics.json for the DHDE Fukui map.

Python 3.9+, standard library plus ``requests``. Every number is a "metric":

    {"value": number | null, "status": "real" | "modelled" | "illustrative" | "pending", "source": str}

Rules this script follows:
  * Figures taken from a public source are "real" and cite the source.
  * Figures computed from real inputs with a stated formula are "modelled".
  * Anything we cannot source is value null, status "pending". Never guess.

Usage:
    python economics/build_regional_economics.py                     # write data/regional_economics.json
    python economics/build_regional_economics.py --inline index.html  # also refresh the inline fallback
    python economics/build_regional_economics.py --offline           # skip the JTA download, use the snapshot
    python economics/build_regional_economics.py --check-source      # confirm the prefecture PDF is unchanged

See economics/README.md for formulas, sources and caveats.
"""
import argparse
import csv
import datetime as _dt
import hashlib
import io
import json
import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_PATH = os.path.join(REPO_ROOT, "data", "regional_economics.json")
AS_OF_YEAR = 2025

# ---------------------------------------------------------------------------
# Source 1: Fukui Prefecture 観光客入込数（推計）2025 edition (PDF)
# ---------------------------------------------------------------------------
PREF_PAGE = "https://www.pref.fukui.lg.jp/doc/kankou/fukuiken-kankoukyakusu.html"
PREF_PDF_2025 = "https://www.pref.fukui.lg.jp/doc/kankou/fukuiken-kankoukyakusu_d/fil/024.pdf"
# SHA-256 of the PDF as downloaded and extracted on 27 Sep 2026 (17 pages).
PREF_PDF_2025_SHA256 = "1c02fe7fb6cba152070493e3bb89bd8f94b7839aa3078fc6324cf79a9c57d249"
PDF_TITLE = "Fukui Pref. 観光客入込数（推計）令和7年 (released 12 Jun 2026)"


def src_pdf(printed_page, what):
    """Citation for the 2025 prefecture PDF. printed_page = number printed on the page."""
    return "%s, p.%s: %s. %s" % (PDF_TITLE, printed_page, what, PREF_PDF_2025)


# Values extracted with pypdf on 27 Sep 2026. The PDF reports thousands (千人).
PREFECTURE = {
    "visitors_2025": 21_443_000,              # p.1 実人数 合計 (unique visitors)
    "visitors_2024": 20_691_000,              # p.1
    "overnight_visitors_2025": 2_385_000,     # p.1 宿泊, 構成比 11.1%
    "spend_total_yen_2025": 198_700_000_000,  # p.8 観光消費額 1,987 億円
    "spend_day_tripper": 5_546,               # p.7 合計 日帰り
    "spend_overnight": 30_221,                # p.7 合計 宿泊
}

# Per-site 延べ人数 (gross visits: a visitor to three sites counts three times),
# p.12-13 table 主要観光地入込状況. (2025, 2024, printed page, site line)
SITE_COUNTS = {
    "tojinbo": (651_000, 778_000, 13, "東尋坊 延べ人数 (location-data estimate since 2020, see p.3 note 2)"),
    "katsuyama": (1_562_000, 1_546_000, 12, "恐竜博物館・かつやま恐竜の森 延べ人数 (incl. outdoor museum)"),
    "rainbow": (443_000, 472_000, 13, "レインボーライン (美浜町・若狭町) 延べ人数"),
    "eiheiji": (518_000, 544_000, 13, "大本山永平寺 延べ人数"),
    "awara": (658_000, 680_000, 12, "あわら温泉 延べ人数"),
}
# Not priority nodes any more (lead, 27 Sep 2026). Extracted before the change and
# kept here for reference only; the JSON reports them as pending.
#   mikuni  三国湊町散策   396,000 (2024: 420,000) p.13
#   maruoka 丸岡城         340,000 (2024: 203,000) p.13
#   ono     大野まちなか観光 598,000 (2024: 613,000) p.12
# 入込数 per municipality (延べ人数, p.9), kept for comparison with the JTA figures.
IRIKOMI_MUNI_2025 = {
    "福井市": 4_014_000, "勝山市": 3_021_000, "あわら市": 2_062_000, "坂井市": 4_294_000,
    "永平寺町": 950_000, "大野市": 1_937_000, "美浜町": 1_296_000, "若狭町": 2_048_000,
}

# ---------------------------------------------------------------------------
# Source 2: JTA digital tourism statistics via code4fukui/japan-kanko-stat
# (monthly 観光来訪者数 per city, same method across Japan since 2021-01).
# Same source the data team added in dhde-preprocessing-model PR #7.
# ---------------------------------------------------------------------------
JTA_REPO = "https://github.com/code4fukui/japan-kanko-stat"
JTA_CSV = "https://raw.githubusercontent.com/code4fukui/japan-kanko-stat/main/data/all.csv"
JTA_ORIGIN = "https://www.nihon-kankou.or.jp/home/jigyou/research/d-toukei/"
# Snapshot used with --offline or when the download fails (repo commit e95314d, fetched 27 Sep 2026).
JTA_SNAPSHOT = {
    "window": ("202509", "202608"),
    "l12m": {
        "18201": [128183, 108582, 135163, 75877, 65437, 57569, 289680, 250898, 346668, 260125, 264076, 344178],
        "18206": [141802, 138534, 156101, 80441, 90829, 124739, 163655, 100488, 166399, 102908, 150280, 230262],
        "18208": [33655, 35104, 38718, 23594, 14421, 21172, 51816, 50617, 77852, 62397, 59465, 82827],
        "18210": [128893, 128146, 151115, 88665, 64618, 72006, 162449, 153635, 257053, 148641, 186990, 325661],
        "18322": [65228, 76387, 108414, 38719, 26970, 30207, 56431, 61012, 91899, 59725, 54996, 81873],
        "18205": [25672, 27904, 28713, 7804, 23833, 36633, 108166, 128369, 171073, 98541, 124322, 169381],
        "18442": [11081, 12468, 17563, 8452, 3562, 2977, 60315, 64880, 128620, 68545, 87507, 130511],
        "18501": [58052, 52714, 73911, 26504, 15283, 22864, 66357, 58533, 112311, 63808, 88708, 117892],
        "17201": [511616, 663689, 781393, 510101, 349809, 450984, 622014, 550709, 753198, 538749, 584592, 712474],
        "16201": [528171, 561250, 583054, 445500, 395295, 426301, 554697, 540944, 643141, 462933, 559246, 689329],
        "18": [767728, 766211, 945872, 493184, 429845, 507510, 1154628, 1093221, 1624966, 1076641, 1302443, 1808033],
        "17": [1147559, 1322700, 1481608, 967707, 770883, 887367, 1512774, 1427210, 1986127, 1419534, 1565806, 1961290],
        "16": [1193706, 1293181, 1320404, 966796, 829553, 889216, 1196277, 1412619, 1868328, 1147924, 1363491, 1784048],
    },
    "cy2025": {
        "18201": 1269198, "18206": 1588657, "18208": 367276, "18210": 1553724, "18322": 706312,
        "18205": 330668, "18442": 138830, "18501": 589082, "17201": 6259882, "16201": 6036671,
        "18": 8757899, "17": 13486876, "16": 14086141,
    },
}
JTA_CAVEAT = ("Caveat: Fukui municipalities jump 2-6x from 2026-03 onward (e.g. Mihama 3k in Feb, 60k in Mar), "
              "a step not seen in Tokyo or Kyoto; check whether the source changed method before quoting.")

# Other context figures supplied by the team brief (not re-verified in this build).
BOJ_KANAZAWA = ("Bank of Japan Kanazawa Branch, 17 Apr 2026: average spend per foreign visitor "
                "(supplied by the team brief, not re-verified in this build)")
KANAZAWA_PILOT = ("Kanazawa City overnight share ~39%, from Gabriella's pilot. Benchmark only: a different "
                  "city with a different visitor mix")
JTA_HOTEL = "Japan Tourism Agency 宿泊旅行統計調査 2025 (supplied by the team brief, not re-verified in this build)"
CAPACITY_DOC = ("dhde-preprocessing-model docs/site_capacity.md (PR #6, branch add-remaining-six-nodes)")
NOT_PRIORITY = "Not a priority node (see docs/data_gaps.md in dhde-preprocessing-model PR #6)."

# ---------------------------------------------------------------------------
# Geography. Ids, names and coordinates match var NODES in index.html.
# `aliases` = node_key used by dhde-preprocessing-model, where it differs.
# ---------------------------------------------------------------------------
NODES = [
    {"id": "tojinbo", "name": "Tojinbo", "name_ja": "東尋坊", "lat": 36.2345, "lon": 136.1257, "region": "sakai",
     "priority": True, "annotation": "No official parking: city lot closed since Jul 2023 for redevelopment. Source: " + CAPACITY_DOC},
    {"id": "station", "aliases": ["fukui_station"], "name": "Fukui Station", "name_ja": "福井駅", "lat": 36.0606, "lon": 136.2216,
     "region": "fukui", "priority": True, "annotation": "200-space west-exit lot; 12 downtown lots, 2,065 spaces. Source: " + CAPACITY_DOC},
    {"id": "katsuyama", "name": "Katsuyama (Dinosaur Museum)", "name_ja": "勝山（恐竜博物館）", "lat": 36.1146, "lon": 136.6876,
     "region": "katsuyama", "priority": True, "annotation": "~1,400 parking spaces at the museum; timed-entry tickets. Source: " + CAPACITY_DOC},
    {"id": "rainbow", "aliases": ["rainbow_line"], "name": "Rainbow Line", "name_ja": "レインボーライン", "lat": 35.5859, "lon": 135.8825,
     "region": "mihama_wakasa", "priority": True, "annotation": "200 spaces across lots 1 and 2; lift ~450/hour each way. Source: " + CAPACITY_DOC},
    {"id": "awara", "aliases": ["awara_onsen"], "name": "Awara Onsen", "name_ja": "あわら温泉", "lat": 36.2069, "lon": 136.2255,
     "region": "awara", "priority": True, "annotation": "165-space lot at Yunomachi Station; total ryokan rooms not published. Source: " + CAPACITY_DOC},
    {"id": "eiheiji", "name": "Eiheiji Temple", "name_ja": "永平寺", "lat": 36.0554, "lon": 136.3505, "region": "eiheiji",
     "priority": True, "annotation": "3 town lots, counts not published. Source: " + CAPACITY_DOC},
    {"id": "mikuni", "name": "Mikuni Port", "name_ja": "三国湊", "lat": 36.2211, "lon": 136.1494, "region": "sakai", "priority": False},
    {"id": "maruoka", "name": "Maruoka Castle", "name_ja": "丸岡城", "lat": 36.1502, "lon": 136.2764, "region": "sakai", "priority": False},
    {"id": "ono", "name": "Ono Castle Town", "name_ja": "大野城下町", "lat": 35.9784, "lon": 136.4874, "region": "ono", "priority": False},
]

REGIONS = [
    {"id": "sakai", "name": "Sakai City", "name_ja": "坂井市", "codes": ["18210"], "munis": ["坂井市"], "priority": True},
    {"id": "fukui", "name": "Fukui City", "name_ja": "福井市", "codes": ["18201"], "munis": ["福井市"], "priority": True},
    {"id": "katsuyama", "name": "Katsuyama City", "name_ja": "勝山市", "codes": ["18206"], "munis": ["勝山市"], "priority": True},
    {"id": "mihama_wakasa", "name": "Mihama & Wakasa Towns", "name_ja": "美浜町・若狭町", "codes": ["18442", "18501"],
     "munis": ["美浜町", "若狭町"], "priority": True},
    {"id": "awara", "name": "Awara City", "name_ja": "あわら市", "codes": ["18208"], "munis": ["あわら市"], "priority": True},
    {"id": "eiheiji", "name": "Eiheiji Town", "name_ja": "永平寺町", "codes": ["18322"], "munis": ["永平寺町"], "priority": True},
    {"id": "ono", "name": "Ono City", "name_ja": "大野市", "codes": ["18205"], "munis": ["大野市"], "priority": False},
]

# Out-of-scope comparison areas (JSON only, not drawn on the map).
COMPARISON = [
    {"id": "kanazawa_city", "name": "Kanazawa City", "name_ja": "金沢市", "code": "17201"},
    {"id": "toyama_city", "name": "Toyama City", "name_ja": "富山市", "code": "16201"},
    {"id": "fukui_pref", "name": "Fukui Prefecture", "name_ja": "福井県", "code": "18"},
    {"id": "ishikawa_pref", "name": "Ishikawa Prefecture", "name_ja": "石川県", "code": "17"},
    {"id": "toyama_pref", "name": "Toyama Prefecture", "name_ja": "富山県", "code": "16"},
]

# Flow endpoints that are not nodes (display only).
EXTERNAL_POINTS = {
    "kanazawa": {"name": "Kanazawa", "name_ja": "金沢", "lat": 36.5780, "lon": 136.6485},  # as index.html KANAZAWA
    "tsuruga": {"name": "Tsuruga Station", "name_ja": "敦賀駅", "lat": 35.6451, "lon": 136.0754},
}

FLOWS = [
    ("kanazawa", "awara", "Kanazawa to Awara Onsen (Hokuriku Shinkansen corridor)"),
    ("kanazawa", "tojinbo", "Kanazawa to Tojinbo"),
    ("station", "eiheiji", "Fukui Station to Eiheiji"),
    ("station", "tojinbo", "Fukui Station to Tojinbo"),
    ("tsuruga", "rainbow", "Tsuruga to Rainbow Line"),
]

BENCHMARK_OVERNIGHT = 0.39


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def metric(value, status, source):
    assert status in ("real", "modelled", "illustrative", "pending"), status
    if value is None:
        status = "pending"
    return {"value": value, "status": status, "source": source}


def pending(reason):
    return metric(None, "pending", reason)


def blended_spend(a):
    s = a["overnight_share"]["value"]
    return s * a["spend_overnight"]["value"] + (1 - s) * a["spend_day_tripper"]["value"]


def revenue_metric(visitors, a, count_note):
    if visitors["value"] is None:
        return pending(visitors["source"])
    return metric(round(visitors["value"] * blended_spend(a)), "modelled",
                  "visitors x (0.111 x ¥30,221 + 0.889 x ¥5,546) = visitors x ¥%s per visitor. Uses the prefecture-wide "
                  "overnight share and spend per visitor for this place. %s"
                  % (format(round(blended_spend(a)), ","), count_note))


def opportunity_metrics(visitors, a):
    if visitors["value"] is None:
        gap = pending(visitors["source"])
    else:
        s = a["overnight_share"]["value"]
        b = a["benchmark_overnight_share_kanazawa"]["value"]
        diff = a["spend_overnight"]["value"] - a["spend_day_tripper"]["value"]
        gap = metric(round(visitors["value"] * (b - s) * diff), "modelled",
                     "If the Kanazawa overnight share were reached: visitors x (0.39 - 0.111) x (¥30,221 - ¥5,546). "
                     "What-if against another city's benchmark, not a forecast.")
    return {
        "overnight_gap": gap,
        "weather": pending("Needs daily camera forecast residuals (predicted minus actual arrivals) per node."),
        "idle_rooms": pending("Needs room stock and daily occupancy per municipality."),
    }


def load_jta(offline):
    """Return (window_start, window_end, {code: [12 monthly values]}, {code: cy2025}, provenance)."""
    codes = set(c for r in REGIONS for c in r["codes"]) | set(c["code"] for c in COMPARISON)
    if not offline:
        try:
            import requests
            resp = requests.get(JTA_CSV, timeout=60)
            resp.raise_for_status()
            series = {}
            for row in csv.DictReader(io.StringIO(resp.content.decode("utf-8-sig"))):
                if row["lgcode"] in codes and row["month"].isdigit() and len(row["month"]) == 6:
                    series.setdefault(row["lgcode"], {})[row["month"]] = int(float(row["n"]))
            # Latest 12 months present for every code we need.
            common = sorted(set.intersection(*(set(series[c]) for c in codes)))
            window = common[-12:]
            if len(window) == 12:
                l12m = {c: [series[c][m] for m in window] for c in codes}
                cy = {}
                for c in codes:
                    months = ["2025%02d" % i for i in range(1, 13)]
                    cy[c] = sum(series[c][m] for m in months) if all(m in series[c] for m in months) else None
                return window[0], window[-1], l12m, cy, "downloaded %s" % _dt.date.today().isoformat()
            print("JTA data incomplete; using snapshot", file=sys.stderr)
        except Exception as exc:  # network or parse failure
            print("JTA download failed (%s); using snapshot" % exc, file=sys.stderr)
    s = JTA_SNAPSHOT
    return s["window"][0], s["window"][1], s["l12m"], s["cy2025"], "snapshot of 27 Sep 2026 (repo commit e95314d)"


def fmt_month(yyyymm):
    return "%s-%s" % (yyyymm[:4], yyyymm[4:])


def build(offline=False):
    p = PREFECTURE
    overnight_share = round(p["overnight_visitors_2025"] / p["visitors_2025"], 3)  # 0.111
    assumptions = {
        "spend_day_tripper": metric(p["spend_day_tripper"], "real", src_pdf(7, "1人当たりの観光消費額単価, 合計 日帰り")),
        "spend_overnight": metric(p["spend_overnight"], "real", src_pdf(7, "1人当たりの観光消費額単価, 合計 宿泊")),
        "spend_foreign": metric(43_000, "real", BOJ_KANAZAWA),
        "overnight_share": metric(overnight_share, "real", src_pdf(1, "宿泊 2,385千人 / 合計 21,443千人, 構成比 11.1%")),
        "benchmark_overnight_share_kanazawa": metric(BENCHMARK_OVERNIGHT, "modelled", KANAZAWA_PILOT),
        # Extra context (same metric shape). Not used in any formula yet.
        "hotel_occupancy_fukui": metric(0.465, "real", JTA_HOTEL + ": Fukui Prefecture 46.5%"),
        "hotel_occupancy_ishikawa": metric(0.582, "real", JTA_HOTEL + ": Ishikawa Prefecture 58.2%"),
    }

    w0, w1, l12m, cy, prov = load_jta(offline)
    window_txt = "%s to %s" % (fmt_month(w0), fmt_month(w1))

    def jta_src(what, extra=""):
        return ("JTA digital tourism statistics (観光来訪者数), %s, sum of the latest 12 months %s, via %s (%s). %s%s"
                % (what, window_txt, JTA_REPO, prov, JTA_CAVEAT, extra))

    pref_visitors = metric(p["visitors_2025"], "real", src_pdf(1, "観光客入込数（実人数）合計 21,443千人"))
    prefecture = {
        "visitors": pref_visitors,
        "visitors_2024": metric(p["visitors_2024"], "real", src_pdf(1, "令和6年 合計 20,691千人")),
        "revenue_yen": metric(p["spend_total_yen_2025"], "real", src_pdf(8, "観光消費額 1,987億円")),
        "opportunity_lost_yen": opportunity_metrics(pref_visitors, assumptions),
    }

    jta_note = ("Visitor count is the JTA 観光来訪者数 (a different definition from the prefecture's 入込数, "
                "whose spend-per-visitor figures are applied here).")
    regions = []
    for r in REGIONS:
        node_ids = [n["id"] for n in NODES if n["region"] == r["id"]]
        pts = [(n["lat"], n["lon"]) for n in NODES if n["region"] == r["id"]]
        centroid = [round(sum(x[0] for x in pts) / len(pts), 4), round(sum(x[1] for x in pts) / len(pts), 4)]
        label = " + ".join("%s (lgcode %s)" % (m, c) for m, c in zip(r["munis"], r["codes"]))
        if r["priority"]:
            visitors = metric(sum(sum(l12m[c]) for c in r["codes"]), "real", jta_src(label))
            cy_vals = [cy.get(c) for c in r["codes"]]
            visitors_cy = (metric(sum(cy_vals), "real", "JTA digital tourism statistics, %s, calendar 2025 (Jan-Dec), via %s (%s)."
                                  % (label, JTA_REPO, prov)) if None not in cy_vals else pending("Calendar 2025 incomplete."))
            irikomi = metric(sum(IRIKOMI_MUNI_2025[m] for m in r["munis"]), "real",
                             src_pdf(9, " + ".join(r["munis"]) + " 延べ人数 2025 (gross visits)"))
        else:
            visitors = pending(NOT_PRIORITY)
            visitors_cy = pending(NOT_PRIORITY)
            irikomi = pending(NOT_PRIORITY)
        regions.append({
            "id": r["id"], "name": r["name"], "name_ja": r["name_ja"], "level": "municipality",
            "nodes": node_ids, "centroid": centroid,
            "visitors": visitors,
            "visitors_calendar_2025": visitors_cy,
            "visitors_irikomi_2025": irikomi,
            "revenue_yen": revenue_metric(visitors, assumptions, jta_note),
            "opportunity_lost_yen": opportunity_metrics(visitors, assumptions),
        })

    site_note = ("Visitor count is 入込数 延べ人数 (gross visits), so node revenues overlap and must not be summed.")
    nodes = []
    for n in NODES:
        node = {k: v for k, v in n.items() if k != "annotation"}
        if n["id"] in SITE_COUNTS:
            v25, v24, page, site = SITE_COUNTS[n["id"]]
            visitors = metric(v25, "real", src_pdf(page, site))
            visitors24 = metric(v24, "real", src_pdf(page, site + ", 令和6年"))
        elif n["priority"]:
            visitors = pending("No station-area line in the prefecture site table (Fukui City only as a whole); "
                               "needs station gate or camera counts.")
            visitors24 = pending(visitors["source"])
        else:
            visitors = pending(NOT_PRIORITY)
            visitors24 = pending(NOT_PRIORITY)
        node.update(visitors=visitors, visitors_2024=visitors24,
                    revenue_yen=revenue_metric(visitors, assumptions, site_note),
                    opportunity_lost_yen=opportunity_metrics(visitors, assumptions))
        if n.get("annotation"):
            node["annotation"] = n["annotation"]
        nodes.append(node)

    comparison = []
    for c in COMPARISON:
        comparison.append({"id": c["id"], "name": c["name"], "name_ja": c["name_ja"], "level": "comparison",
                           "visitors": metric(sum(l12m[c["code"]]), "real", jta_src("%s (lgcode %s)" % (c["name_ja"], c["code"]))),
                           "visitors_calendar_2025": metric(cy[c["code"]], "real",
                                                            "JTA digital tourism statistics, calendar 2025, via %s (%s)." % (JTA_REPO, prov))})

    known = set(n["id"] for n in NODES)
    flows = []
    for a, b, label in FLOWS:
        f = {"from": a, "to": b,
             "visitors": pending("Visitor movement between places is not measured yet (needs KDDI location data or survey v2)."),
             "status": "pending", "note": label + ": not yet measured."}
        for key, pid in (("from_coord", a), ("to_coord", b)):
            if pid not in known:
                f[key] = [EXTERNAL_POINTS[pid]["lat"], EXTERNAL_POINTS[pid]["lon"]]
        flows.append(f)

    return {
        "generated_at": _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat(),
        "as_of_year": AS_OF_YEAR,
        "currency": "JPY",
        "assumptions": assumptions,
        "prefecture": prefecture,
        "regions": regions,
        "nodes": nodes,
        "flows": flows,
        "comparison_regions": comparison,
        "external_points": EXTERNAL_POINTS,
        "visitor_window": {"regions": window_txt, "nodes": "calendar 2025"},
    }


INLINE_START = "/* REGIONAL_ECONOMICS_INLINE_START */"
INLINE_END = "/* REGIONAL_ECONOMICS_INLINE_END */"


def write_inline(html_path, data):
    with open(html_path, encoding="utf-8", newline="") as fh:  # keep the file's own line endings
        html = fh.read()
    if INLINE_START not in html or INLINE_END not in html:
        sys.exit("Inline markers not found in %s" % html_path)
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    block = "%s\nwindow.REGIONAL_ECONOMICS_DATA = %s;\n%s" % (INLINE_START, payload, INLINE_END)
    html = re.sub(re.escape(INLINE_START) + r".*?" + re.escape(INLINE_END), lambda m: block, html, count=1, flags=re.S)
    with open(html_path, "w", encoding="utf-8", newline="") as fh:
        fh.write(html)
    print("Inline fallback refreshed in %s" % html_path)


def check_source():
    import requests
    r = requests.get(PREF_PDF_2025, timeout=60, headers={"User-Agent": "Mozilla/5.0 (DHDE build script)"})
    r.raise_for_status()
    digest = hashlib.sha256(r.content).hexdigest()
    print("Fetched %s (%d bytes), sha256 %s" % (PREF_PDF_2025, len(r.content), digest))
    if digest == PREF_PDF_2025_SHA256:
        print("OK: source PDF unchanged since the figures were extracted.")
        return 0
    print("WARNING: source PDF has changed. Re-extract the figures (see README) before trusting them.")
    return 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=OUT_PATH)
    ap.add_argument("--inline", metavar="HTML", help="also refresh the inline fallback JSON in this HTML file")
    ap.add_argument("--offline", action="store_true", help="use the JTA snapshot instead of downloading")
    ap.add_argument("--check-source", action="store_true", help="download the prefecture PDF and compare its hash")
    args = ap.parse_args()
    if args.check_source:
        sys.exit(check_source())
    data = build(offline=args.offline)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    print("Wrote %s" % args.out)
    if args.inline:
        write_inline(args.inline, data)


if __name__ == "__main__":
    main()
