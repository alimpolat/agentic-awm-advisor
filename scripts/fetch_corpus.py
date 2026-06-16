"""Best-effort fetch of the public macro/a Nordic private bank RAG corpus.

PDFs are gitignored (large binaries); only this script + data/corpus/SOURCES.html are
committed, so the corpus is reproducible and source-traceable. Government PDF URLs are
version-specific and may move — the script downloads what it can and logs the rest, so a
404 never blocks the build. build_index.py (Chunk 2) indexes whatever PDFs are present
plus the committed Bergström HTML corpus.

Run from repo root:  uv run python scripts/fetch_corpus.py
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

CORPUS = [
    # filename, url, publisher, use
    ("bis_quarterly_2026_q1.pdf", "https://www.bis.org/publ/qtrpdf/r_qt2603.pdf",
     "BIS", "Cross-border capital flows; Gulf real-estate context"),
    ("bis_quarterly_2025_q4.pdf", "https://www.bis.org/publ/qtrpdf/r_qt2512.pdf",
     "BIS", "Prior-quarter macro/credit backdrop"),
    ("imf_weo_2026_04.pdf", "https://www.imf.org/-/media/Files/Publications/WEO/2026/April/English/text.ashx",
     "IMF", "Global growth/inflation outlook; rates regime"),
    ("ecb_economic_bulletin_2026.pdf", "https://www.ecb.europa.eu/pub/pdf/ecbu/eb202602.en.pdf",
     "ECB", "Euro-area monetary policy; EU fixed-income duration"),
    ("nordea_annual_report_2024.pdf", "https://www.nordea.com/en/doc/nordea-annual-report-2024.pdf",
     "a Nordic private bank", "House view; AWM product context"),
]

HEADERS = {"User-Agent": "Mozilla/5.0 (agentic-awm-advisor corpus fetch)", "Accept": "application/pdf,*/*"}
OUT = Path(__file__).resolve().parents[1] / "data" / "corpus"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    log = []
    with httpx.Client(timeout=30, follow_redirects=True, headers=HEADERS) as c:
        for fname, url, pub, use in CORPUS:
            dest = OUT / fname
            rec = {"file": fname, "url": url, "publisher": pub, "use": use}
            if dest.exists() and dest.stat().st_size > 10_000:
                rec["status"] = "cached"
                rec["bytes"] = dest.stat().st_size
                print(f"CACHED {fname}")
                log.append(rec)
                continue
            try:
                r = c.get(url)
                ct = r.headers.get("content-type", "")
                if r.status_code == 200 and ("pdf" in ct or r.content[:4] == b"%PDF"):
                    dest.write_bytes(r.content)
                    rec["status"] = "ok"
                    rec["bytes"] = len(r.content)
                    print(f"OK     {fname}  ({len(r.content)//1024} KB)")
                else:
                    rec["status"] = f"skip_{r.status_code}_{ct[:24]}"
                    print(f"SKIP   {fname}  HTTP {r.status_code} {ct[:30]}")
            except Exception as e:  # noqa: BLE001
                rec["status"] = f"error_{type(e).__name__}"
                print(f"ERROR  {fname}  {type(e).__name__}: {e}")
            log.append(rec)

    (OUT.parent / "corpus_fetch_log.json").write_text(json.dumps({"at": time.time(), "log": log}, indent=2))
    ok = sum(1 for r in log if r["status"] in ("ok", "cached"))
    print(f"\nFetched/cached {ok}/{len(CORPUS)} public docs. "
          f"Bergström HTML corpus ({len(list(OUT.glob('bergstrom*.html')))} files) is committed and always present.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
