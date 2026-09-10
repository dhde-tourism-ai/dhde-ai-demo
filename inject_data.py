#!/usr/bin/env python3
"""Replace the DHDE_DATA block inside index.html with the current dhde_data.json.

Run after build_data.py. Keeps index.html self-contained (no runtime fetch of its
own data) while making the refresh a command rather than a copy-paste.
"""
import json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
HTML = os.path.join(HERE, "index.html")
DATA = os.path.join(HERE, "dhde_data.json")

html = open(HTML, encoding="utf-8").read()
payload = json.load(open(DATA, encoding="utf-8"))

# Anchor on the assignment and the ';' that closes it. The JSON is emitted with no
# spaces after separators, so a ';\n' terminator is unambiguous.
pat = re.compile(r"(  var DHDE_DATA = )\{.*?\}(;\n)", re.S)
if len(pat.findall(html)) != 1:
    sys.exit(f"FATAL: found {len(pat.findall(html))} DHDE_DATA blocks, expected exactly 1")

new_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
html2 = pat.sub(lambda m: m.group(1) + new_json + m.group(2), html, count=1)

# Refresh the human-readable provenance comment above the block so it cannot drift
# out of step with the data it describes.
meta = payload["meta"]
html2 = re.sub(
    r"(//                 Actions\. )[\d,]+( respondents, )[\d,]+( of them at these 9 nodes,\n  //                 )\d+\.\.\d+",
    lambda m: (m.group(1) + f"{meta['respondentsTotal']:,}" + m.group(2)
               + f"{meta['respondentsAtNodes']:,}" + m.group(3)
               + f"{meta['monthsCovered'][0]}..{meta['monthsCovered'][-1]}"),
    html2, count=1)

if html2 == html:
    print("index.html already up to date")
else:
    open(HTML, "w", encoding="utf-8").write(html2)
    print(f"index.html updated: {len(html):,} -> {len(html2):,} bytes")

print(f"  generated : {meta['generatedAt']}")
print(f"  months    : {meta['monthsCovered'][0]} .. {meta['monthsCovered'][-1]}")
print(f"  responses : {meta['respondentsAtNodes']:,} at nodes")
print(f"  model R2  : {meta['model']['r2InSample']} in-sample / {meta['model']['r2Holdout']} hold-out")
print("\nThe UI reads model stats, econ shares and the measured headline tiles straight\n"
      "from DHDE_DATA at runtime, so this is the only file that needs updating.")
