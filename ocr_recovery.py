"""
OCR Recovery Script — Arabic Legal PDFs
=========================================
Reads output/failed.json, runs Tesseract Arabic OCR on each
scanned PDF, and appends recovered records to output/corpus.jsonl.

Usage:
  python3 ocr_recovery.py
  python3 ocr_recovery.py --limit 5     # test first 5
  python3 ocr_recovery.py --dpi 400     # higher DPI = better quality, slower
"""

import os
import re
import json
import argparse
import pytesseract
from pathlib import Path
from PIL import Image
from pdf2image import convert_from_path
from datetime import datetime

# ── Config ────────────────────────────────────────────────────────────────────

OUTPUT_DIR   = Path("output")
CORPUS_JSONL = OUTPUT_DIR / "corpus.jsonl"
FAILED_LOG   = OUTPUT_DIR / "failed.json"
OCR_FAILED   = OUTPUT_DIR / "ocr_failed.json"

DEFAULT_DPI  = 300   # 300 is good balance of quality vs speed for Arabic
                     # Use 400 for small/dense text, 200 for speed

# ── Helpers ───────────────────────────────────────────────────────────────────

def clean_arabic_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return '\n'.join(l.strip() for l in text.splitlines()).strip()


def extract_year(name: str):
    m = re.search(r'(?:لسنة|لسنه|سنة|سنه)\s*(\d{4})', name)
    if m: return m.group(1)
    m = re.search(r'\b(19\d{2}|20\d{2})\b', name)
    return m.group(1) if m else None


def extract_law_number(name: str):
    m = re.search(r'رقم\s+(\d+)', name)
    return m.group(1) if m else None


def classify_doc_type(name: str) -> str:
    if 'دستور' in name: return 'constitution'
    if 'قرار وزاري' in name: return 'ministerial_decree'
    if 'مرسوم' in name: return 'amiri_decree'
    if 'اتفاقية' in name or 'اتفاق' in name: return 'international_agreement'
    if 'لائحة' in name: return 'regulation'
    if 'تعميم' in name: return 'circular'
    if 'مجموعة' in name: return 'compiled_collection'
    if 'قانون' in name: return 'law'
    return 'other'


def get_existing_ids() -> set:
    """Load IDs already in corpus.jsonl to avoid duplicates."""
    ids = set()
    if not CORPUS_JSONL.exists():
        return ids
    with open(CORPUS_JSONL, 'r', encoding='utf-8') as f:
        for line in f:
            try:
                ids.add(json.loads(line)['url'])
            except Exception:
                pass
    return ids


def ocr_pdf(pdf_path: Path, dpi: int) -> str:
    """
    Convert PDF pages to images and run Tesseract Arabic OCR.
    Returns concatenated text from all pages.
    """
    # Convert PDF to list of PIL images
    images = convert_from_path(
        str(pdf_path),
        dpi=dpi,
        fmt='png',
        thread_count=4,
    )

    page_texts = []
    for i, img in enumerate(images):
        # Tesseract config:
        # --oem 1  = LSTM neural net engine (best for Arabic)
        # --psm 3  = fully automatic page segmentation (default)
        # -l ara   = Arabic language
        text = pytesseract.image_to_string(
            img,
            lang='ara',
            config='--oem 1 --psm 3'
        )
        if text.strip():
            page_texts.append(text)

    return '\n\n'.join(page_texts)


# ── Main ──────────────────────────────────────────────────────────────────────

def run_ocr_recovery(limit=None, dpi=DEFAULT_DPI):
    # Load failed list
    if not FAILED_LOG.exists():
        print("[!] output/failed.json not found. Run kuwait_legal_scraper.py first.")
        return

    with open(FAILED_LOG, 'r', encoding='utf-8') as f:
        failed = json.load(f)

    # Filter to only extraction failures (not download failures)
    # Download failures don't have a local PDF to OCR
    to_ocr = [
        f for f in failed
        if f.get('error') in ('extraction_failed',)
        and f.get('pdf')  # has a local pdf path
    ]

    # Also handle cases where pdf key is missing but file exists in pdfs/
    for f in failed:
        if f.get('error') == 'extraction_failed' and not f.get('pdf'):
            # Try to find it by URL filename
            from urllib.parse import unquote
            fname = re.sub(r'[<>:"/\\|?*\u200b]', '_', unquote(f['url'].split('/')[-1]))
            candidate = OUTPUT_DIR / 'pdfs' / fname
            if candidate.exists():
                f['pdf'] = str(candidate)
                if f not in to_ocr:
                    to_ocr.append(f)

    if limit:
        to_ocr = to_ocr[:limit]

    existing_urls = get_existing_ids()
    print(f"[*] {len(to_ocr)} scanned PDFs to OCR")
    print(f"[*] DPI: {dpi}")
    print(f"[*] Already in corpus: {len(existing_urls)} documents\n")

    recovered   = []
    still_failed = []

    # Count existing corpus records for ID numbering
    existing_count = len(existing_urls)

    with open(CORPUS_JSONL, 'a', encoding='utf-8') as jsonl:
        for i, item in enumerate(to_ocr, 1):
            name     = item.get('name', 'unknown')
            url      = item.get('url', '')
            pdf_path = Path(item['pdf'])

            print(f"[{i:3d}/{len(to_ocr)}] {name[:65]}")

            # Skip if already in corpus
            if url in existing_urls:
                print(f"         [~] Already in corpus, skipping")
                continue

            if not pdf_path.exists():
                print(f"         [!] PDF not found: {pdf_path}")
                still_failed.append({**item, 'ocr_error': 'pdf_not_found'})
                continue

            # Run OCR
            try:
                raw_text = ocr_pdf(pdf_path, dpi=dpi)
            except Exception as e:
                print(f"         [!] OCR error: {e}")
                still_failed.append({**item, 'ocr_error': str(e)})
                continue

            if not raw_text.strip():
                print(f"         [!] OCR returned empty text")
                still_failed.append({**item, 'ocr_error': 'empty_output'})
                continue

            text       = clean_arabic_text(raw_text)
            word_count = len(text.split())

            # Flag low-confidence OCR results
            quality = 'good' if word_count > 200 else 'low'
            print(f"         [+] {word_count:,} words  (ocr, quality={quality})")

            record = {
                'id':           f"kw_moj_ocr_{existing_count + i:04d}",
                'source':       'Kuwait Ministry of Justice',
                'name':         name,
                'url':          url,
                'year':         extract_year(name),
                'law_number':   extract_law_number(name),
                'doc_type':     classify_doc_type(name),
                'language':     'ar',
                'jurisdiction': 'Kuwait',
                'text':         text,
                'word_count':   word_count,
                'char_count':   len(text),
                'method':       'ocr_tesseract',
                'ocr_dpi':      dpi,
                'ocr_quality':  quality,
                'scraped_at':   datetime.now().isoformat(),
            }

            jsonl.write(json.dumps(record, ensure_ascii=False) + '\n')
            jsonl.flush()
            recovered.append({k: v for k, v in record.items() if k != 'text'})
            existing_urls.add(url)

    # Save updated failed log (only truly unrecoverable ones)
    with open(OCR_FAILED, 'w', encoding='utf-8') as f:
        json.dump(still_failed, f, ensure_ascii=False, indent=2)

    # ── Summary ───────────────────────────────────────────────────────────────
    total_new_words = sum(r['word_count'] for r in recovered)

    print("\n" + "="*65)
    print("  OCR RECOVERY COMPLETE")
    print("="*65)
    print(f"  Recovered:    {len(recovered)} documents")
    print(f"  Still failed: {len(still_failed)} documents")
    print(f"  New words:    {total_new_words:,}")
    print(f"\n  Low-quality OCR results (review these):")
    low = [r for r in recovered if r.get('ocr_quality') == 'low']
    if low:
        for r in low:
            print(f"    {r['name'][:60]}  ({r['word_count']} words)")
    else:
        print("    None — all results look reasonable")
    print(f"\n  Unrecoverable saved to: {OCR_FAILED}")
    print("="*65)

    # Print updated total corpus stats
    total_words = 0
    total_docs  = 0
    if CORPUS_JSONL.exists():
        with open(CORPUS_JSONL, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    d = json.loads(line)
                    total_words += d.get('word_count', 0)
                    total_docs  += 1
                except Exception:
                    pass
    print(f"\n  TOTAL CORPUS NOW:")
    print(f"    Documents: {total_docs}")
    print(f"    Words:     {total_words:,}")
    print("="*65)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description='OCR recovery for scanned Arabic legal PDFs')
    ap.add_argument('--limit', type=int, default=None, help='Process only N docs (test mode)')
    ap.add_argument('--dpi',   type=int, default=DEFAULT_DPI, help='OCR resolution (default: 300)')
    args = ap.parse_args()
    run_ocr_recovery(limit=args.limit, dpi=args.dpi)