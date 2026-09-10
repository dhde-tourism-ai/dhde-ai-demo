#!/usr/bin/env python3
"""
Build real SEASON_DATA for the Fukui DHDE dashboard from code4fukui open data.

Source: https://github.com/code4fukui/fukui-kanko-survey  (FTAS, Fukui Tourism
Federation), one row per survey respondent, updated daily by GitHub Actions.

Emits dhde_data.json in the exact shape the dashboard's SEASON_DATA already uses,
so nothing downstream of getFrame() has to change.
"""
import json, glob, os, re, sys
from datetime import datetime, timezone
import pandas as pd
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
AREA_CSV = os.path.join(HERE, "area.csv")
MONTHLY_GLOB = os.path.join(HERE, "monthly", "*.csv")
RSV_SUM = os.path.join(HERE, "rsv_latest_rsv_sum.csv")
RSV_HOTEL = os.path.join(HERE, "rsv_latest_hotel.csv")
RSV_CURVE = os.path.join(HERE, "rsv_booking_curve.csv")
OUT = os.path.join(HERE, "dhde_data.json")

# The dashboard's 9 nodes -> FTAS area names (from area.csv).
NODE_AREA = {
    "tojinbo":   "東尋坊 エリア",
    "station":   "福井駅前 エリア",
    "katsuyama": "かつやま恐竜の森 エリア",
    "rainbow":   "レインボーライン エリア",
    "eiheiji":   "大本山 永平寺 エリア",
    "awara":     "あわら湯のまち エリア",
    "mikuni":    "三国湊 エリア",
    "maruoka":   "丸岡城 エリア",
    "ono":       "越前大野城・城下町 エリア",
}
AREA_NODE = {v: k for k, v in NODE_AREA.items()}
NODE_IDS = list(NODE_AREA)

SEASON_OF_MONTH = {3:"spring",4:"spring",5:"spring", 6:"summer",7:"summer",8:"summer",
                   9:"autumn",10:"autumn",11:"autumn", 12:"winter",1:"winter",2:"winter"}
SEASONS = ["spring","summer","autumn","winter"]

# Respondents pick an information source; these are the digital ones. Share of
# respondents using at least one is the honest stand-in for the old "RSI proxy".
DIGITAL_SRC = ["インターネット・アプリ","Twitter","Instagram","Facebook","ブログ","観光連盟やDMOのHP"]

MONEY_BAND = re.compile(r"([\d,]+)円以上\s*([\d,]+)円未満")


def money_to_yen(v):
    """Spend bands -> midpoint yen. '使わない' is a real zero, blank is unknown."""
    if not isinstance(v, str) or not v.strip():
        return np.nan
    s = v.strip()
    if s == "使わない":
        return 0.0
    m = MONEY_BAND.search(s)
    if m:
        lo = float(m.group(1).replace(",", "")); hi = float(m.group(2).replace(",", ""))
        return (lo + hi) / 2
    m = re.search(r"([\d,]+)円未満", s)
    if m:
        return float(m.group(1).replace(",", "")) / 2
    m = re.search(r"([\d,]+)円以上", s)
    if m:                       # open top band, take the floor rather than invent a ceiling
        return float(m.group(1).replace(",", ""))
    return np.nan


def load_area_aliases():
    """code4fukui renames areas over time; area.csv keeps the old name in 旧エリア名.
    Without this we silently drop years of Awara / Katsuyama / Eiheiji responses."""
    area = pd.read_csv(AREA_CSV, dtype=str, encoding="utf-8-sig")
    alias = {}
    for _, r in area.iterrows():
        cur, old = r.get("エリア名"), r.get("旧エリア名")
        if isinstance(cur, str) and isinstance(old, str) and old.strip():
            alias[old.strip()] = cur.strip()
    coords = {}
    for _, r in area.iterrows():
        nm = (r.get("エリア名") or "").strip()
        if nm in AREA_NODE:
            coords[AREA_NODE[nm]] = {
                "areaId": int(r["親番号"]), "areaName": nm,
                "lat": float(r["緯度"]), "lng": float(r["経度"]),
                "city": r["市町名"],
            }
    return alias, coords


def load_panel(alias):
    """Read every monthly file, keep only what we need, return a tidy respondent table."""
    keep = ["回答エリア","回答日時","NPS","満足度","不便さ","エリア総消費額","県内消費額",
            "今後の来訪意向","都道府県","宿泊数（全体）"] + DIGITAL_SRC
    frames, missing_cols = [], set()
    for path in sorted(glob.glob(MONTHLY_GLOB)):
        df = pd.read_csv(path, dtype=str, low_memory=False)
        for c in keep:
            if c not in df.columns:
                missing_cols.add((os.path.basename(path), c)); df[c] = np.nan
        frames.append(df[keep])
    raw = pd.concat(frames, ignore_index=True)
    if missing_cols:
        print(f"  note: {len(missing_cols)} missing column(s) filled as NaN", file=sys.stderr)

    raw["area"] = raw["回答エリア"].astype(str).str.strip().replace(alias)
    raw["ts"] = pd.to_datetime(raw["回答日時"], errors="coerce")
    raw = raw.dropna(subset=["ts"])
    raw["ym"] = raw["ts"].dt.to_period("M")
    raw["season"] = raw["ts"].dt.month.map(SEASON_OF_MONTH)

    raw["nps"] = pd.to_numeric(raw["NPS"], errors="coerce")
    raw["inconvenient"] = (raw["不便さ"] == "感じた").astype(float)
    raw["overnight"] = (~raw["宿泊数（全体）"].isin(["日帰り"])) & raw["宿泊数（全体）"].notna()
    raw["overnight"] = raw["overnight"].astype(float)
    raw["from_ishikawa"] = (raw["都道府県"] == "石川県").astype(float)
    raw["revisit_soon"] = (raw["今後の来訪意向"] == "また行きたい（1年以内）").astype(float)
    raw["spend_area"] = raw["エリア総消費額"].map(money_to_yen)
    raw["spend_pref"] = raw["県内消費額"].map(money_to_yen)
    for c in DIGITAL_SRC:
        raw[c] = pd.to_numeric(raw[c], errors="coerce").fillna(0)
    raw["digital"] = (raw[DIGITAL_SRC].sum(axis=1) > 0).astype(float)

    total_rows, kept = len(raw), raw[raw["area"].isin(AREA_NODE)].copy()
    kept["node"] = kept["area"].map(AREA_NODE)
    return raw, kept, total_rows


def aggregate(kept, by):
    g = kept.groupby(by)
    out = g.agg(
        n=("nps", "size"),
        nps=("nps", "mean"),
        inconvenient=("inconvenient", "mean"),
        digital=("digital", "mean"),
        overnight=("overnight", "mean"),
        ishikawa=("from_ishikawa", "mean"),
        revisit=("revisit_soon", "mean"),
        spend_area=("spend_area", "mean"),
        spend_pref=("spend_pref", "mean"),
    ).reset_index()
    return out


def load_reservations():
    """code4fukui/fukui-kanko-reservation: nightly booking data for the 10 Awara
    Onsen hotels, from the Fukui Tourism Federation. n_room / total rooms is a
    REAL occupancy rate, and the booking curve is a real forward-demand signal
    (rooms already on the books N days before arrival)."""
    hotels = pd.read_csv(RSV_HOTEL, encoding="utf-8-sig")
    total_rooms = int(hotels["nrooms"].sum())

    rsv = pd.read_csv(RSV_SUM, encoding="utf-8-sig", parse_dates=["date_visit"])
    rsv["season"] = rsv["date_visit"].dt.month.map(SEASON_OF_MONTH)
    rsv["occ"] = rsv["n_room"] / total_rooms * 100
    today = pd.Timestamp.now().normalize()
    past = rsv[rsv["date_visit"] <= today]
    future = rsv[rsv["date_visit"] > today]

    occ = past.groupby("season")["occ"].mean().round(1).to_dict()
    people = past.groupby("season")["n_people"].mean().round(0).to_dict()
    fee = past.groupby("season")["amount_fee"].mean().round(0).to_dict()

    curve = pd.read_csv(RSV_CURVE, encoding="utf-8-sig", parse_dates=["target_date"])
    curve["season"] = curve["target_date"].dt.month.map(SEASON_OF_MONTH)
    lead = {}
    for s in SEASONS:
        sub = curve[curve["season"] == s]
        if sub.empty:
            continue
        lead[s] = {d: round(float(sub[f"ago_{d}days"].mean()), 1)
                   for d in (0, 7, 14, 30, 60, 90) if f"ago_{d}days" in sub.columns}

    return {
        "scope": "Awara Onsen, 10 hotels",
        "totalRooms": total_rooms,
        "dateRange": [str(past["date_visit"].min().date()), str(past["date_visit"].max().date())],
        "occupancyPct": {s: occ.get(s, 0.0) for s in SEASONS},
        "guestsPerNight": {s: int(people.get(s, 0)) for s in SEASONS},
        "revenuePerNightYen": {s: int(fee.get(s, 0)) for s in SEASONS},
        "avgFeePerStayYen": int(round(past["amount_fee"].sum() / max(1, past["n_stay"].sum()))),
        "bookingCurveRooms": lead,
        "forwardBookedNights": int(len(future)),
        "forwardBookedThrough": str(future["date_visit"].max().date()) if len(future) else None,
    }


def main():
    print("Loading area master...", file=sys.stderr)
    alias, coords = load_area_aliases()
    missing = [n for n in NODE_IDS if n not in coords]
    if missing:
        sys.exit(f"FATAL: no area.csv match for {missing}")

    print("Loading monthly survey files...", file=sys.stderr)
    raw, kept, total_rows = load_panel(alias)
    print(f"  {total_rows:,} respondents total, {len(kept):,} at the 9 nodes", file=sys.stderr)

    print("Loading Awara reservation data...", file=sys.stderr)
    rsv = load_reservations()
    print(f"  {rsv['totalRooms']} rooms across {rsv['scope']}, "
          f"{rsv['forwardBookedNights']} nights forward-booked", file=sys.stderr)

    # ---- monthly panel (used to fit the forecast) ----
    monthly = aggregate(kept, ["node", "ym"])
    monthly["month"] = monthly["ym"].dt.month
    monthly["season"] = monthly["month"].map(SEASON_OF_MONTH)
    monthly["ym_str"] = monthly["ym"].astype(str)

    # ---- seasonal aggregate (what the dashboard consumes) ----
    seasonal = aggregate(kept, ["node", "season"])

    # Visit volume -> the dashboard's 0-100 "actual" index. Indexed against the
    # busiest node-season so relative differences survive; it is a response-volume
    # index, NOT a visitor headcount, and the UI must say so.
    seas_counts = seasonal.set_index(["node", "season"])["n"]
    max_count = float(seas_counts.max())
    seasonal["actual"] = (seasonal["n"] / max_count * 100).round(1)

    # sentiment: mean NPS (0-10) -> 0-100
    seasonal["sentiment"] = (seasonal["nps"] * 10).round(1)
    # digital intent: share using an online information source
    seasonal["rsi"] = (seasonal["digital"] * 100).round(1)
    # friction: share who reported inconvenience (real congestion signal)
    seasonal["friction"] = (seasonal["inconvenient"] * 100).round(1)

    # ---- forecast model (this replaces the invented `predicted` column) ----
    m = monthly[monthly["n"] >= 3].copy()          # ignore months too thin to mean anything
    m = m.sort_values(["node", "ym"])
    m["actual_idx"] = m["n"] / max_count * 100
    m["prev"] = m.groupby("node")["actual_idx"].shift(1)
    m["nps_f"] = m["nps"].fillna(m["nps"].mean())
    m = m.dropna(subset=["prev"])

    # Seasonality as two harmonic terms rather than 11 month dummies: the signal is
    # genuinely annual and this spends 2 degrees of freedom instead of 11.
    m["sin1"] = np.sin(2 * np.pi * m["month"] / 12)
    m["cos1"] = np.cos(2 * np.pi * m["month"] / 12)

    feats = ["prev", "digital", "overnight", "nps_f", "revisit", "sin1", "cos1"]
    X = pd.get_dummies(m[feats + ["node"]], columns=["node"], drop_first=True).astype(float)
    X.insert(0, "const", 1.0)
    y = m["actual_idx"].to_numpy(float)

    cut = m["ym"] <= pd.Period("2025-08", "M")
    Xtr, ytr = X[cut.to_numpy()].to_numpy(), y[cut.to_numpy()]
    Xte, yte = X[~cut.to_numpy()].to_numpy(), y[~cut.to_numpy()]

    beta, *_ = np.linalg.lstsq(Xtr, ytr, rcond=None)
    fit_all = X.to_numpy() @ beta

    def r2(a, p):
        ss = ((a - p) ** 2).sum(); st = ((a - a.mean()) ** 2).sum()
        return 1 - ss / st if st else float("nan")

    r2_in = r2(ytr, Xtr @ beta)
    r2_out = r2(yte, Xte @ beta) if len(yte) > 2 else float("nan")
    mae_idx = float(np.abs(yte - Xte @ beta).mean()) if len(yte) else float("nan")
    mae_resp = float(np.abs((yte - Xte @ beta) * max_count / 100).mean()) if len(yte) else float("nan")

    # The model is fitted on MONTHLY volume; the dashboard shows SEASONAL volume.
    # Convert the fitted values back to counts, sum them per node-season, and express
    # the result as a ratio against the actual counts over the same months. Applying
    # that ratio to the published seasonal actual keeps both series on one scale.
    m["pred_n"] = np.clip(fit_all, 0, None) * max_count / 100
    ratio = (m.groupby(["node", "season"])["pred_n"].sum()
             / m.groupby(["node", "season"])["n"].sum()).replace([np.inf, -np.inf], np.nan)

    # ---- assemble SEASON_DATA ----
    season_data, coverage = {}, {}
    for s in SEASONS:
        nodes = {}
        for nid in NODE_IDS:
            row = seasonal[(seasonal.node == nid) & (seasonal.season == s)]
            if row.empty:
                nodes[nid] = {"actual": 0.0, "predicted": 0.0, "rsi": 0.0, "sentiment": 0.0,
                              "friction": 0.0, "spendYen": 0, "n": 0}
                continue
            r = row.iloc[0]
            rt = ratio.get((nid, s), np.nan)
            p = float(r["actual"]) * (float(rt) if pd.notna(rt) else 1.0)
            nodes[nid] = {
                "actual": float(r["actual"]),
                "predicted": round(float(max(0.0, min(100.0, p))), 1),
                "rsi": float(r["rsi"]),
                "sentiment": float(r["sentiment"]),
                "friction": float(r["friction"]),
                "spendYen": int(round(float(r["spend_area"]))) if pd.notna(r["spend_area"]) else 0,
                "n": int(r["n"]),
            }
            coverage[f"{nid}/{s}"] = int(r["n"])
        sl = kept[kept.season == s]
        season_data[s] = {
            # Real Awara Onsen occupancy from booked rooms / total rooms.
            "hotelOcc": rsv["occupancyPct"][s],
            "overnightShare": round(float(sl["overnight"].mean() * 100), 1),
            "ishikawaShare": round(float(sl["from_ishikawa"].mean() * 100), 2),
            "nodes": nodes,
        }

    # ---- real economic weights (replaces the invented exposure x scale split) ----
    econ = {}
    tot = 0.0
    for nid in NODE_IDS:
        sub = kept[kept.node == nid]
        w = float(sub["spend_area"].mean() or 0) * len(sub)
        econ[nid] = w; tot += w
    econ_share = {k: round(v / tot, 5) for k, v in econ.items()} if tot else {}

    payload = {
        "meta": {
            "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source": "code4fukui/fukui-kanko-survey (FTAS, Fukui Prefecture Tourism Federation)",
            "sourceUrl": "https://github.com/code4fukui/fukui-kanko-survey",
            # The survey repo publishes NO LICENSE file and its README states no terms,
            # so do not assert one. The reservation repo is MIT. Confirm reuse terms with
            # the Fukui Tourism Federation before publishing this anywhere public.
            "license": "not declared by the source repo; attribution given, terms unconfirmed",
            "attribution": "福井県観光連盟 (Fukui Tourism Federation) / FTAS, via Code for Fukui",
            "monthsCovered": sorted(monthly["ym_str"].unique().tolist()),
            "respondentsTotal": int(total_rows),
            "respondentsAtNodes": int(len(kept)),
            "indexBase": {"maxNodeSeasonResponses": int(max_count),
                          "note": "actual/predicted are a 0-100 survey-response volume index, not visitor headcount"},
            "model": {
                "spec": "OLS: actual_idx ~ prev + digital + overnight + mean_NPS + revisit_intent + node FE",
                "trainThrough": "2025-08", "nTrain": int(cut.sum()), "nTest": int((~cut).sum()),
                "r2InSample": round(float(r2_in), 3), "r2Holdout": round(float(r2_out), 3),
                "maeIndexPoints": round(mae_idx, 2), "maeResponses": round(mae_resp, 1),
            },
            "econShare": econ_share,
            "coverage": coverage,
        },
        "nodes": coords,
        "seasons": season_data,
        "reservations": rsv,
    }

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)

    print(f"\nWrote {OUT}", file=sys.stderr)
    print(f"  months        : {payload['meta']['monthsCovered'][0]} .. {payload['meta']['monthsCovered'][-1]}", file=sys.stderr)
    print(f"  respondents   : {total_rows:,} total / {len(kept):,} at nodes", file=sys.stderr)
    print(f"  model R2      : {r2_in:.3f} in-sample, {r2_out:.3f} chronological hold-out", file=sys.stderr)
    print(f"  model MAE     : {mae_idx:.2f} index pts ({mae_resp:.1f} responses/month)", file=sys.stderr)
    return payload


if __name__ == "__main__":
    p = main()
    print("\n--- seasonal actual index ---", file=sys.stderr)
    for s in SEASONS:
        row = " ".join(f"{k}:{v['actual']:>5.1f}" for k, v in p["seasons"][s]["nodes"].items())
        print(f"{s:<7} {row}", file=sys.stderr)
