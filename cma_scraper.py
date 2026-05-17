"""
Kuwait Capital Markets Authority (CMA) — Arabic Regulatory Corpus Scraper
===========================================================================
Downloads Arabic regulatory PDFs from e.gov.kw (CMA mirror) and appends
them to output/corpus.jsonl, following the same pattern as cbk_scraper.py.

URL patterns confirmed working:
  - https://e.gov.kw/sites/kgoarabic/Forms/N-CMA.pdf  (numbered docs)
  - https://www.e.gov.kw/sites/KGOenglish/Forms/CMACapitalMarketEstablishmentLaw.pdf
  - https://e.gov.kw/sites/kgoarabic/Forms/CMA18_3_1241.pdf

Usage:
  python3 cma_scraper.py
  python3 cma_scraper.py --limit 5
  python3 cma_scraper.py --skip-download
"""

import re, json, time, argparse
import requests, pdfplumber, fitz
from pathlib import Path
from urllib.parse import unquote
from datetime import datetime
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ── Config ────────────────────────────────────────────────────────────────────

OUTPUT_DIR   = Path("output")
PDF_DIR      = OUTPUT_DIR / "pdfs_cma"
CORPUS_JSONL = OUTPUT_DIR / "corpus.jsonl"
FAILED_LOG   = OUTPUT_DIR / "cma_failed.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ar-KW,ar;q=0.9,en;q=0.8",
    "Referer": "https://www.e.gov.kw/",
    "Accept": "application/pdf,application/octet-stream,*/*",
}
DELAY   = 1.5
TIMEOUT = (10, 60)

EGOV_AR = "https://e.gov.kw/sites/kgoarabic/Forms"
EGOV_EN = "https://www.e.gov.kw/sites/KGOenglish/Forms"

# ── All CMA Arabic regulatory PDFs ───────────────────────────────────────────
# Format: (arabic_name, pdf_url, section, doc_type)
#
# The e.gov.kw portal mirrors CMA documents at numbered paths (N-CMA.pdf).
# Confirmed accessible: 16-CMA, 17-CMA, 19-CMA, 25-CMA, 28-CMA, 30-CMA,
#                       33-CMA, 45-CMA, CMA18_3_1241, main law PDF.
# The full range 1-50 is scanned; 404s are skipped gracefully.

DOCS = [

    # ── قانون هيئة أسواق المال (CMA Founding Law — confirmed accessible) ──────
    (
        "قانون رقم 7 لسنة 2010 بشأن إنشاء هيئة أسواق المال وتنظيم نشاط الأوراق المالية",
        f"{EGOV_EN}/CMACapitalMarketEstablishmentLaw.pdf",
        "قانون هيئة أسواق المال",
        "capital_markets_law",
    ),

    # ── قواعد حوكمة الشركات (Corporate Governance — confirmed accessible) ──────
    (
        "قواعد حوكمة الشركات الخاضعة لرقابة هيئة أسواق المال",
        f"{EGOV_AR}/CMA18_3_1241.pdf",
        "لوائح إضافية",
        "capital_markets_regulation",
    ),

    # ── النطاق الكامل للوثائق المرقمة (Full scan of numbered CMA docs 1–50) ───
    # Confirmed: 16, 17, 19, 25, 28, 30, 33, 45. Others attempted; 404s skipped.
] + [
    (
        f"وثيقة هيئة أسواق المال — الملف رقم {n}",
        f"{EGOV_AR}/{n}-CMA.pdf",
        "اللائحة التنفيذية",
        "capital_markets_regulation",
    )
    for n in range(1, 51)
]

# ── Helpers ───────────────────────────────────────────────────────────────────

def clean_arabic_text(text):
    if not text: return ""
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return '\n'.join(l.strip() for l in text.splitlines()).strip()


def pdf_filename(url):
    return re.sub(r'[<>:"/\\|?*\u200b\+]', '_', unquote(url.split('/')[-1]))


def get_existing_urls():
    urls = set()
    if not CORPUS_JSONL.exists(): return urls
    with open(CORPUS_JSONL, encoding='utf-8') as f:
        for line in f:
            try: urls.add(json.loads(line)['url'])
            except: pass
    return urls


def download_pdf(url, session):
    local = PDF_DIR / pdf_filename(url)
    if local.exists() and local.stat().st_size > 500:
        # Verify it's a real PDF
        with open(local, 'rb') as f:
            if f.read(4) == b'%PDF':
                return local
        local.unlink()
    try:
        r = session.get(url, timeout=TIMEOUT, verify=False, stream=True)
        r.raise_for_status()
        content = b''
        for chunk in r.iter_content(8192):
            content += chunk
        if not content.startswith(b'%PDF'):
            return None
        with open(local, 'wb') as f:
            f.write(content)
        return local
    except Exception as e:
        # Suppress verbose 404 noise; just return None
        if '404' not in str(e) and 'NOT FOUND' not in str(e).upper():
            print(f"  [!] {e}")
        return None


def extract_text(path):
    try:
        parts = []
        with pdfplumber.open(path) as pdf:
            for pg in pdf.pages:
                t = pg.extract_text()
                if t: parts.append(t)
        text = '\n\n'.join(parts)
        if len(text.strip()) > 100: return text, 'pdfplumber'
    except: pass
    try:
        doc = fitz.open(str(path))
        parts = [pg.get_text() for pg in doc]
        doc.close()
        text = '\n\n'.join(parts)
        if len(text.strip()) > 100: return text, 'pymupdf'
    except: pass
    return "", 'failed'


# ── Main ──────────────────────────────────────────────────────────────────────

def build_cma_corpus(limit=None, skip_download=False):
    OUTPUT_DIR.mkdir(exist_ok=True)
    PDF_DIR.mkdir(exist_ok=True)

    docs = DOCS[:limit] if limit else DOCS
    existing_urls = get_existing_urls()

    cma_count = 0
    if CORPUS_JSONL.exists():
        with open(CORPUS_JSONL, encoding='utf-8') as f:
            for line in f:
                try:
                    if json.loads(line).get('source') == 'Capital Markets Authority Kuwait':
                        cma_count += 1
                except: pass

    print(f"[*] Kuwait CMA Arabic Regulatory Corpus Scraper")
    print(f"[*] {len(docs)} URLs to attempt (many will 404 — that is expected)")
    print(f"[*] Already in corpus: {len(existing_urls)} total docs\n")

    session = requests.Session()
    session.headers.update(HEADERS)

    recovered, failed = [], []

    with open(CORPUS_JSONL, 'a', encoding='utf-8') as jsonl:
        for i, (name, url, section, doc_type) in enumerate(docs, 1):
            if url in existing_urls:
                continue

            if skip_download:
                path = PDF_DIR / pdf_filename(url)
                if not path.exists():
                    failed.append({'name': name, 'url': url, 'error': 'not_found_locally'})
                    continue
            else:
                path = download_pdf(url, session)
                if not path:
                    failed.append({'name': name, 'url': url, 'error': 'download_failed'})
                    continue
                time.sleep(DELAY)

            raw, method = extract_text(path)
            if not raw.strip():
                failed.append({'name': name, 'url': url, 'error': 'extraction_failed'})
                continue

            text  = clean_arabic_text(raw)
            words = len(text.split())

            if words < 50:
                failed.append({'name': name, 'url': url, 'error': 'too_short', 'words': words})
                continue

            cma_count += 1
            print(f"  [+] {url.split('/')[-1]:<35} {words:>7,} words  ({method})")

            record = {
                'id':           f"kw_cma_{cma_count:04d}",
                'source':       'Capital Markets Authority Kuwait',
                'name':         name,
                'url':          url,
                'section':      section,
                'year':         None,
                'doc_type':     doc_type,
                'language':     'ar',
                'jurisdiction': 'Kuwait',
                'text':         text,
                'word_count':   words,
                'char_count':   len(text),
                'method':       method,
                'scraped_at':   datetime.now().isoformat(),
            }

            jsonl.write(json.dumps(record, ensure_ascii=False) + '\n')
            jsonl.flush()
            recovered.append({k: v for k, v in record.items() if k != 'text'})
            existing_urls.add(url)

    with open(FAILED_LOG, 'w', encoding='utf-8') as f:
        json.dump(failed, f, ensure_ascii=False, indent=2)

    total_words = sum(r['word_count'] for r in recovered)

    corpus_docs, corpus_words = 0, 0
    with open(CORPUS_JSONL, encoding='utf-8') as f:
        for line in f:
            try:
                d = json.loads(line)
                corpus_words += d.get('word_count', 0)
                corpus_docs  += 1
            except: pass

    print("\n" + "="*65)
    print("  CMA CORPUS BUILD COMPLETE")
    print("="*65)
    print(f"  New CMA docs added:  {len(recovered)}")
    print(f"  New words:           {total_words:,}")
    print(f"\n  TOTAL CORPUS NOW:")
    print(f"    Documents:         {corpus_docs}")
    print(f"    Words:             {corpus_words:,}")
    print("="*65)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description='Kuwait CMA Arabic regulatory corpus scraper')
    ap.add_argument('--limit',         type=int, default=None)
    ap.add_argument('--skip-download', action='store_true')
    args = ap.parse_args()
    build_cma_corpus(limit=args.limit, skip_download=args.skip_download)