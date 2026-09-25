#!/usr/bin/env python3
"""Search the local YuE2 demo catalog; download only with --refresh."""
import argparse
import hashlib
from datetime import datetime, timezone
import json
from pathlib import Path
import urllib.request

from common import write

URL = "https://map-yue2.github.io/data/cases.js"
CATALOG = Path(__file__).resolve().parents[1] / "references/demo-catalog.json"


def parse(text):
    prefix = "window.YUE2_DATA ="
    if not text.lstrip().startswith(prefix):
        raise ValueError("Demo data format changed; inspect the site manually")
    text = text.lstrip()[len(prefix):].lstrip()
    data, end = json.JSONDecoder().raw_decode(text)
    if text[end:].strip() not in ("", ";") or not isinstance(data.get("cases"), list):
        raise ValueError("Unexpected demo data; do not evaluate its JavaScript")
    return data["cases"]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--query", help="Space-separated genre/mood/instrument terms")
    p.add_argument("--output", type=Path)
    p.add_argument("--data-file", type=Path, help="Use a previously fetched cases.js offline")
    p.add_argument("--refresh", action="store_true", help="Download all examples into the local catalog")
    p.add_argument("--limit", type=int, default=8)
    a = p.parse_args()
    if bool(a.query) != bool(a.output):
        p.error("Use --query and --output together")
    if not a.query and not a.refresh:
        p.error("Provide --query and --output, or --refresh")
    if a.refresh and a.data_file:
        p.error("--refresh cannot be combined with --data-file")
    if a.output and a.output.exists():
        p.error("Choose a fresh output file")
    if a.limit < 1:
        p.error("--limit must be positive")
    if a.refresh:
        with urllib.request.urlopen(URL, timeout=45) as response:
            raw = response.read(20 * 1024 * 1024 + 1)
        if len(raw) > 20 * 1024 * 1024:
            raise ValueError("Unexpectedly large demo data")
        cases = parse(raw.decode("utf-8"))
        catalog = {"source": URL, "retrieved_at": datetime.now(timezone.utc).isoformat(),
                   "source_sha256": hashlib.sha256(raw).hexdigest(), "cases": cases}
        write(CATALOG, catalog)
        print(f"Saved all {len(cases)} demo examples to {CATALOG}")
    if not a.query:
        return
    if a.data_file:
        cases = parse(a.data_file.read_text(encoding="utf-8"))
        provenance = {"data_file": str(a.data_file)}
    else:
        if not CATALOG.exists():
            p.error("Local catalog is missing; run with --refresh once")
        catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
        cases = catalog["cases"]
        provenance = {"retrieved_at": catalog["retrieved_at"],
                      "source_sha256": catalog["source_sha256"], "catalog": str(CATALOG)}
    terms = a.query.lower().split()
    ranked = []
    for c in cases:
        haystack = " ".join(str(c.get(k, "")) for k in ("genre", "title", "tags")).lower()
        score = sum(term in haystack for term in terms)
        if score:
            ranked.append((score, {k: c.get(k) for k in
                                  ("id", "title", "genre", "tags", "mode", "audio", "scoreAudio", "abcUrl")}))
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    write(a.output, {"source": URL, "site": "https://map-yue2.github.io/",
                     **provenance, "selected_at": datetime.now(timezone.utc).isoformat(), "query": a.query,
                     "matches": [c for _, c in ranked[:a.limit]],
                     "note": "Reference styles only. Do not copy lyrics or vocal instructions into BGM prompts."})
    print(f"Saved {min(len(ranked), a.limit)} matching demo prompts to {a.output}")


if __name__ == "__main__":
    main()
