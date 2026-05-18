# Kuwait Legal Knowledge Base

## What this project is
Arabic legal corpus assembled from three Kuwaiti regulators — Central Bank of Kuwait (CBK), Capital Markets Authority (CMA), Ministry of Justice (MOJ) — to fine-tune an Arabic embedding model for legal RAG / semantic search via triplet generation.

## Current state (as of 2026-05-17)
- `output/corpus.jsonl` — **227 docs, ~2.84M words, all extracted via Tesseract OCR**
- Audit: 148 PASS, 78 WARN, 10 FAIL (FAILs are false positives on long repetitive codes)
- All RTL-reversal issues resolved (was the dominant quality problem)

### Record schema
```
{id, source, name, year, doc_type, language, jurisdiction, text, word_count, method, url, ...}
```

## Source layout
| Folder | Source | Count |
|---|---|---|
| `output/pdfs/` | MOJ (Ministry of Justice) | 79 |
| `output/pdfs_cbk/` | Central Bank of Kuwait | 130 |
| `output/pdfs_cma/` | Capital Markets Authority | 47 |

Failure logs are kept per source: `output/cbk_failed.json`, `output/cma_failed.json`, `output/failed.json` (MOJ), `output/cbk_fix_failed.json`, `output/ocr_failed.json`.

## Pipeline

1. **Scrapers** download PDFs:
   - `cbk_scraper.py` / `cbk_scraper_v2.py` / `cbk_scraper_v3.py` — CBK (v2 and v3 are retry passes for dead URLs)
   - `cma_scraper.py` — CMA via e.gov.kw mirror
   - `kuwait_legal_scraper.py` — MOJ from moj.gov.kw
2. **Extraction**: scrapers call `pdfplumber` / `PyMuPDF`, but **those produce RTL-reversed Arabic** — see "Important gotchas" below.
3. **Re-extraction via Tesseract** (`ocr_recovery.py`):
   - `--select severe` — original mode; only docs with low Arabic ratio or high garbling
   - `--select non_ocr` — re-OCR every doc whose `method != 'ocr_tesseract'` (added 2026-05-17)
   - Default Tesseract config: `--oem 1 --psm 3`, `lang='ara'`, DPI 300
4. **Quality checks**:
   - `corpus_audit.py` — strict 6-signal scorecard (arabic_ratio, garbled_ratio, rtl_score, repetition_score, lexical_diversity, samples). Writes `output/corpus_audit_report.json`.
   - `corpus_health.py` — training-readiness verdict (Healthy / Partial / Severe)
5. **Spot-check**:
   - `random_sample.py` — 8 random docs in an RTL-safe HTML viewer (`corpus_rtl_sample.html`)
   - `inspect_short_docs.py` — render specific IDs in full (used for triaging short docs)
6. **Cleanup**:
   - `rid_duplicate.py` — pattern for removing specific doc IDs

## Important gotchas

- **pdfplumber and PyMuPDF return visually-ordered Arabic.** The extracted text is letter-by-letter reversed within each word. This is the dominant quality issue in this corpus. Always re-extract Arabic PDFs via Tesseract — *don't* try to "fix" pdfplumber output with a reverse-string operation.
- **Audit signal triage:** treat `rtl_score`, `garbled_ratio`, and `arabic_ratio` as **load-bearing**. `lexical_diversity` and `repetition_score` fire false positives on long repetitive legal codes (civil code, penal code) — those flags do not indicate OCR failure.
- **Always back up `corpus.jsonl` before mutating it.** The convention used in this project is `output/corpus_pre_<reason>.jsonl` (snapshot before edit).
- **Tables lose structure under OCR.** Cell text is captured as a row-by-row stream. Acceptable for embedding/RAG use; not acceptable if structured tables are needed.

## Common commands

```bash
# Health checks
.venv/bin/python corpus_audit.py
.venv/bin/python corpus_health.py

# Visual spot-check
.venv/bin/python random_sample.py

# Re-OCR (the production mode):
.venv/bin/python ocr_recovery.py --select non_ocr --dry-run   # verify PDFs resolve
.venv/bin/python ocr_recovery.py --select non_ocr --limit 5   # test sample
.venv/bin/python ocr_recovery.py --select non_ocr             # full run
```

## Backups currently in `output/`

Snapshots from past mutations, safe to delete once you're confident:
- `corpus_pre_reocr_non_ocr.jsonl` — before re-OCRing 116 non-OCR docs (2026-05-17)
- `corpus_pre_dedup.jsonl` — before removing `kw_cbk_0107` (duplicate of `kw_cbk_0190`)
- `corpus_pre_drop_short.jsonl` — before dropping 8 CMA form-template docs
- Older: `corpus_pre_rtlfix.jsonl`, `corpus_pre_ocr14.jsonl`, etc. — earlier passes

## Next phase
Triplet generation from `corpus.jsonl` → fine-tune Arabic embedding model.
