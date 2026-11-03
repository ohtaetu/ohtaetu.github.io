"""Refresh data/citations.json with citation counts for the papers on the homepage.

Sources: the Google Scholar profile page, OpenAlex, Semantic Scholar and Crossref.
Each paper gets the highest count across sources. A source that fails keeps its
previous value, so a blocked request never lowers a number. The file is only
rewritten when a count changes.

  python scripts/update_citations.py
"""
import datetime as dt
import html
import json
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "citations.json"
SCHOLAR = "https://scholar.google.com/citations?user=Uu5cUOUAAAAJ&hl=en"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

PAPERS = [
    ("10.1109/tvlsi.2026.3741555", "QS-ATP: Quasi-static active-transistor PDN modeling and partition optimization"),
    ("10.1109/access.2026.3682854", "Progressive compression of ResNet: An 8.33x reduction with 90.5% accuracy retention"),
    ("10.54644/jte.2025.1756", "Optimizing binary neural network for resource-constrained edge devices in IoT applications"),
    ("10.11591/ijece.v15i6.pp5173-5182", "Improving time-domain winner-take-all circuit for neuromorphic computing systems"),
]


def get(url, data=None, headers=None):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8")


def norm(title):
    return re.sub(r"[^a-z0-9]", "", title.lower().replace("×", "x"))


def scholar():
    page = get(SCHOLAR, headers={"Accept-Language": "en"})
    rows = re.findall(r'<tr class="gsc_a_tr">(.*?)</tr>', page, re.S)
    if not rows:
        raise RuntimeError("no publication rows (blocked or layout changed)")
    found = {}
    for row in rows:
        title = html.unescape(re.search(r'class="gsc_a_at">(.*?)</a>', row, re.S).group(1))
        cell = re.search(r'class="gsc_a_ac[^"]*">(\d*)</a>', row)
        count = int(cell.group(1)) if cell and cell.group(1) else 0
        key = norm(title)
        for doi, ours in PAPERS:
            if key.startswith(norm(ours)) or norm(ours).startswith(key):
                found[doi] = count
    return found


def openalex():
    dois = "|".join(d for d, _ in PAPERS)
    j = json.loads(get(f"https://api.openalex.org/works?filter=doi:{dois}&select=doi,cited_by_count&per-page=50"))
    return {w["doi"].replace("https://doi.org/", "").lower(): w["cited_by_count"] for w in j["results"]}


def semanticscholar():
    body = json.dumps({"ids": [f"DOI:{d}" for d, _ in PAPERS]}).encode()
    j = json.loads(get("https://api.semanticscholar.org/graph/v1/paper/batch?fields=citationCount", body,
                       {"Content-Type": "application/json"}))
    return {d: p["citationCount"] for (d, _), p in zip(PAPERS, j) if p}


def crossref():
    out = {}
    for d, _ in PAPERS:
        j = json.loads(get(f"https://api.crossref.org/works/{d}"))
        out[d] = j["message"].get("is-referenced-by-count", 0)
    return out


def main():
    old = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {"papers": {}}
    papers = {d: {"sources": dict(old["papers"].get(d, {}).get("sources", {}))} for d, _ in PAPERS}

    for name, fetch in [("scholar", scholar), ("openalex", openalex), ("semanticscholar", semanticscholar),
                        ("crossref", crossref)]:
        try:
            result = fetch()
        except Exception as e:  # keep the previous value for this source
            print(f"{name}: skipped ({e})")
            continue
        for d, count in result.items():
            if d in papers:
                papers[d]["sources"][name] = count
        print(f"{name}: " + ", ".join(f"{d}={c}" for d, c in result.items()))

    for p in papers.values():
        p["count"] = max(p["sources"].values(), default=0)
    counts = sorted((p["count"] for p in papers.values()), reverse=True)
    totals = {"citations": sum(counts), "h_index": sum(1 for i, c in enumerate(counts) if c >= i + 1),
              "papers": len(PAPERS)}

    if papers == old.get("papers") and totals == old.get("totals"):
        print("no change")
        return
    OUT.parent.mkdir(exist_ok=True)
    data = {"updated": dt.date.today().isoformat(), "totals": totals, "papers": papers}
    OUT.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}: {totals}")


if __name__ == "__main__":
    main()
