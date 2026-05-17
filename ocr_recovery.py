"""
OCR Re-extraction — Corrupted Corpus Documents
================================================
Targets docs already in corpus.jsonl that have garbled/no Arabic text,
re-extracts them using Tesseract OCR, and replaces the bad records
in-place. Does NOT create duplicates.

Two passes:
  1. Find all PDF files for the target IDs (searches all pdfs_* dirs)
  2. OCR each one, replace the bad record in corpus.jsonl

Targets: all severe docs where word_count > 500 and ar_ratio < 0.15
(i.e. worth recovering — too small to bother OCR-ing)

Usage:
  python3 ocr_reextract.py            # full run
  python3 ocr_reextract.py --limit 3  # test first 3
  python3 ocr_reextract.py --dpi 400  # higher quality, slower
  python3 ocr_reextract.py --dry-run  # show targets without extracting
"""

import re, json, argparse, shutil
import pytesseract
from pathlib import Path
from PIL import Image
from pdf2image import convert_from_path
from datetime import datetime
from urllib.parse import unquote

# ── Config ────────────────────────────────────────────────────────────────────

OUTPUT_DIR   = Path("output")
CORPUS_JSONL = OUTPUT_DIR / "corpus.jsonl"
REPORT_FILE  = OUTPUT_DIR / "ocr_reextract_report.json"
DEFAULT_DPI  = 300

# PDF search dirs — all CBK/MOJ/CMA download folders
PDF_DIRS = [
    OUTPUT_DIR / "pdfs",
    OUTPUT_DIR / "pdfs_cbk",
    OUTPUT_DIR / "pdfs_moj",
    OUTPUT_DIR / "pdfs_cma",
]

# ── Health thresholds (same as corpus_health.py) ─────────────────────────────

def arabic_ratio(text):
    if not text: return 0
    arabic = len(re.findall(r'[\u0600-\u06FF]', text))
    total  = len(re.findall(r'\S', text))
    return arabic / total if total > 0 else 0

def junk_ratio(text):
    if not text: return 0
    junk  = len(re.findall(r'(cid:\d+|\(cid:\d+\)|[^\u0000-\u007F\u0600-\u06FF\s]{4,})', text))
    words = len(text.split())
    return junk / words if words > 0 else 0

def is_severe(doc):
    text = doc.get('text', '')
    wc   = doc.get('word_count', 0)
    ar   = arabic_ratio(text)
    junk = junk_ratio(text)
    if wc < 500:    return False   # too short to bother OCR-ing
    if ar < 0.05:   return True    # no Arabic
    if junk > 0.30: return True    # heavily garbled
    if ar < 0.15:   return True    # barely any Arabic
    return False

def is_non_ocr(doc):
    return doc.get('method') != 'ocr_tesseract'

SELECTORS = {'severe': is_severe, 'non_ocr': is_non_ocr}

# ── Helpers ───────────────────────────────────────────────────────────────────

def clean_arabic_text(text):
    if not text: return ""
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return '\n'.join(l.strip() for l in text.splitlines()).strip()

def pdf_filename_from_url(url):
    """Reconstruct the PDF filename the scraper would have used."""
    fname = unquote(url.split('/')[-1])
    fname = re.sub(r'[<>:"/\\|?*\u200b\+]', '_', fname)
    return fname

def find_pdf(url):
    """Search all pdf dirs for the downloaded file."""
    fname = pdf_filename_from_url(url)
    for d in PDF_DIRS:
        p = d / fname
        if p.exists() and p.stat().st_size > 500:
            return p
    return None

def ocr_pdf(pdf_path, dpi):
    """Convert PDF pages to images and run Tesseract Arabic OCR."""
    images = convert_from_path(str(pdf_path), dpi=dpi, fmt='png', thread_count=4)
    page_texts = []
    for img in images:
        text = pytesseract.image_to_string(img, lang='ara', config='--oem 1 --psm 3')
        if text.strip():
            page_texts.append(text)
    return '\n\n'.join(page_texts)

# ── Main ──────────────────────────────────────────────────────────────────────

def run(limit=None, dpi=DEFAULT_DPI, dry_run=False):

    # ── Load corpus ───────────────────────────────────────────────────────────
    print("[*] Loading corpus...")
    docs = []
    with open(CORPUS_JSONL, encoding='utf-8') as f:
        for line in f:
            try: docs.append(json.loads(line.strip()))
            except: pass

    # ── Identify targets ──────────────────────────────────────────────────────
    targets = [d for d in docs if is_severe(d)]
    print(f"[*] Severe docs eligible for OCR recovery: {len(targets)}")
    print(f"[*] (skipping docs with word_count < 500 — not worth OCR-ing)\n")

    if limit:
        targets = targets[:limit]

    if dry_run:
        print("DRY RUN — targets that would be processed:")
        for d in targets:
            url = d.get('url', '')
            pdf = find_pdf(url)
            status = f"PDF found: {pdf.name}" if pdf else "NO PDF FOUND"
            print(f"  {d['id']:<18} {d.get('word_count',0):>8,}w  {status}")
            print(f"    {d.get('name','')[:70]}")
        return

    # ── Process each target ───────────────────────────────────────────────────
    recovered   = []
    no_pdf      = []
    ocr_failed  = []
    still_bad   = []

    for i, doc in enumerate(targets, 1):
        doc_id = doc['id']
        name   = doc.get('name', '')
        url    = doc.get('url', '')
        old_wc = doc.get('word_count', 0)

        print(f"[{i:3d}/{len(targets)}] {name[:65]}")
        print(f"           id={doc_id}  old_words={old_wc:,}  ar={arabic_ratio(doc.get('text','')):.0%}")

        # Find the PDF
        pdf_path = find_pdf(url)
        if not pdf_path:
            print(f"           [!] PDF not found — cannot recover")
            no_pdf.append(doc_id)
            continue

        # Run OCR
        try:
            raw = ocr_pdf(pdf_path, dpi=dpi)
        except Exception as e:
            print(f"           [!] OCR error: {e}")
            ocr_failed.append({'id': doc_id, 'error': str(e)})
            continue

        if not raw.strip():
            print(f"           [!] OCR returned empty text")
            ocr_failed.append({'id': doc_id, 'error': 'empty_output'})
            continue

        text  = clean_arabic_text(raw)
        words = len(text.split())
        ar    = arabic_ratio(text)
        junk  = junk_ratio(text)

        print(f"           [+] {words:,} words  ar={ar:.0%}  junk={junk:.0%}  (ocr)")

        # Check OCR actually improved things
        if ar < 0.10 and words < 500:
            print(f"           [~] OCR didn't help much — marking as unrecoverable")
            still_bad.append(doc_id)
            continue

        # Update the doc record in-place
        doc['text']       = text
        doc['word_count'] = words
        doc['char_count'] = len(text)
        doc['method']     = 'ocr_tesseract'
        doc['ocr_dpi']    = dpi
        doc['ocr_reextracted_at'] = datetime.now().isoformat()

        recovered.append(doc_id)

    # ── Rewrite corpus.jsonl with updated records ─────────────────────────────
    if recovered:
        print(f"\n[*] Rewriting corpus.jsonl with {len(recovered)} updated records...")
        doc_map = {d['id']: d for d in docs}
        with open(CORPUS_JSONL, 'w', encoding='utf-8') as f:
            for d in docs:
                f.write(json.dumps(doc_map[d['id']], ensure_ascii=False) + '\n')
        print(f"[*] Done.")

    # ── Save report ───────────────────────────────────────────────────────────
    report = {
        'recovered':   recovered,
        'no_pdf':      no_pdf,
        'ocr_failed':  ocr_failed,
        'still_bad':   still_bad,
        'timestamp':   datetime.now().isoformat(),
    }
    with open(REPORT_FILE, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # ── Final corpus stats ────────────────────────────────────────────────────
    total_docs, total_words = 0, 0
    with open(CORPUS_JSONL, encoding='utf-8') as f:
        for line in f:
            try:
                d = json.loads(line)
                total_docs  += 1
                total_words += d.get('word_count', 0)
            except: pass

    print(f"\n{'='*65}")
    print(f"  OCR RE-EXTRACTION COMPLETE")
    print(f"{'='*65}")
    print(f"  Recovered (updated in corpus): {len(recovered)}")
    print(f"  No PDF found (skip):           {len(no_pdf)}")
    print(f"  OCR failed:                    {len(ocr_failed)}")
    print(f"  OCR didn't help (still bad):   {len(still_bad)}")
    print(f"\n  TOTAL CORPUS NOW:")
    print(f"    Documents: {total_docs}")
    print(f"    Words:     {total_words:,}")
    print(f"{'='*65}")
    print(f"\n  Full report saved to: {REPORT_FILE}")


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description='OCR re-extraction for corrupted corpus docs')
    ap.add_argument('--limit',   type=int,  default=None,  help='Process only N targets')
    ap.add_argument('--dpi',     type=int,  default=DEFAULT_DPI, help='OCR DPI (default 300)')
    ap.add_argument('--dry-run', action='store_true', help='Show targets without extracting')
    args = ap.parse_args()
    run(limit=args.limit, dpi=args.dpi, dry_run=args.dry_run)