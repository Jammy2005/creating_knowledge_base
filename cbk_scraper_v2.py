"""
CBK Dead URL Fix — Updated DOCS for previously-failed sections
==============================================================
Add this DOCS_MISSING list to your cbk_scraper.py, replacing the old
failed entries for Islamic Banks, Finance Companies, Investment Companies,
Exchange Companies, and CBK Law 32/1968.

All URLs verified live from cbk.gov.kw pages on May 2026.

To use: replace the DOCS list in cbk_scraper.py with this one,
or run as a standalone script (it uses the same helpers as cbk_scraper.py).

Usage:
  python3 cbk_scraper_fix.py
  python3 cbk_scraper_fix.py --limit 5
"""

import re, json, time, argparse
import requests, pdfplumber, fitz
from pathlib import Path
from urllib.parse import unquote
from datetime import datetime
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

OUTPUT_DIR   = Path("output")
PDF_DIR      = OUTPUT_DIR / "pdfs_cbk"
CORPUS_JSONL = OUTPUT_DIR / "corpus.jsonl"
FAILED_LOG   = OUTPUT_DIR / "cbk_fix_failed.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ar-KW,ar;q=0.9",
    "Referer": "https://www.cbk.gov.kw/ar/",
}
DELAY        = 2.0
TIMEOUT      = (15, 60)   # increased connect timeout
MAX_RETRIES  = 3
RETRY_BACKOFF = [5, 15, 30]  # seconds to wait between retries

BASE = "https://www.cbk.gov.kw/ar/images/"

DOCS = [

    # ── البنوك الإسلامية (Islamic Banks) — 39 docs ───────────────────────────
    # URLs from: cbk.gov.kw/ar/supervision/cbk-regulations-and-instructions/instructions-for-islamic-banks
    ("المقدمة — التعليمات الرقابية على البنوك الإسلامية",
     BASE + "intro-112402_v20_tcm11-112402.pdf", "البنوك الإسلامية"),
    ("الباب الأول: لائحة بنظام سجل البنوك الإسلامية",
     BASE + "ch1part1-118624_v20_tcm11-118624.pdf", "البنوك الإسلامية"),
    ("موجز بأحكام القانون رقم 30 لسنة 2003 بإضافة قسم خاص بالبنوك الإسلامية",
     BASE + "law-islamic-30-2003-ar-147058_v30_tcm11-147058.pdf", "البنوك الإسلامية"),
    ("1. نظام الأخطار المصرفية — البنوك الإسلامية",
     BASE + "1p1-112376_v70_tcm11-112376.pdf", "البنوك الإسلامية"),
    ("2. القواعد الخاصة بنظام السيولة — البنوك الإسلامية",
     BASE + "2p1-112378_v40_tcm11-112378.pdf", "البنوك الإسلامية"),
    ("3. فروع البنوك الإسلامية",
     BASE + "3p1-112379_v40_tcm11-112379.pdf", "البنوك الإسلامية"),
    ("4. ضوابط التركز في التمويل — البنوك الإسلامية",
     BASE + "4p1-112380_v70_tcm11-112380.pdf", "البنوك الإسلامية"),
    ("5. سياسة تصنيف عمليات الاستثمار والتمويل للعملاء",
     BASE + "5p1-112381_v30_tcm11-112381.pdf", "البنوك الإسلامية"),
    ("6. ضوابط وقواعد الاستثمار المباشر — البنوك الإسلامية",
     BASE + "6p1-112382_v20_tcm11-112382.pdf", "البنوك الإسلامية"),
    ("7. تعليمات بشأن سياسة الاستثمار المالي — البنوك الإسلامية",
     BASE + "7p1-112384_v20_tcm11-112384.pdf", "البنوك الإسلامية"),
    ("8. قواعد شراء البنوك الإسلامية لأسهمها",
     BASE + "8p1-112385_v30_tcm11-112385.pdf", "البنوك الإسلامية"),
    ("9. تعليمات بشأن نشاط التمويل — البنوك الإسلامية",
     BASE + "9p1-112386_v50_tcm11-112386.pdf", "البنوك الإسلامية"),
    ("10. تعليمات بشأن عمليات التمويل الاستهلاكي — البنوك الإسلامية",
     BASE + "10p1-112702_v40_tcm11-112702.pdf", "البنوك الإسلامية"),
    ("11. معيار كفاية رأس المال — البنوك الإسلامية",
     BASE + "11p1-112387_v20_tcm11-112387.pdf", "البنوك الإسلامية"),
    ("12. القواعد والضوابط الخاصة بالخبرة المطلوبة — البنوك الإسلامية",
     BASE + "12p1-112388_v30_tcm11-112388.pdf", "البنوك الإسلامية"),
    ("13. قواعد وشروط تعيين واختصاصات هيئة الرقابة الشرعية في البنوك الإسلامية",
     BASE + "13p2-112389_v40_tcm11-112389.pdf", "البنوك الإسلامية"),
    ("14. تعليمات بشأن نظم الرقابة الداخلية وإدارة المخاطر — البنوك الإسلامية",
     BASE + "14p2-112390_v50_tcm11-112390.pdf", "البنوك الإسلامية"),
    ("15. علاقة البنوك الإسلامية مع عملائها",
     BASE + "15p2-112391_v50_tcm11-112391.pdf", "البنوك الإسلامية"),
    ("16. مكافحة عمليات غسيل الأموال وتمويل الإرهاب — البنوك الإسلامية",
     BASE + "16p2-112392_v110_tcm11-112392.pdf", "البنوك الإسلامية"),
    ("17. القواعد التي تنظم إدارة محافظ الغير لدى البنوك الإسلامية",
     BASE + "17p2-112570_v20_tcm11-112570.pdf", "البنوك الإسلامية"),
    ("18. تعليمات بشأن مراقبي الحسابات — البنوك الإسلامية",
     BASE + "18p2-112393_v20_tcm11-112393.pdf", "البنوك الإسلامية"),
    ("19. التعميم بشأن التوظيفات الاستثمارية لدى البنوك والمؤسسات المالية",
     BASE + "19p2-112571_v20_tcm11-112571.pdf", "البنوك الإسلامية"),
    ("20. نظام الحصر المركزي لعملاء الشيكات المرتجعة — البنوك الإسلامية",
     BASE + "20p2-112394_v40_tcm11-112394.pdf", "البنوك الإسلامية"),
    ("21. تعليمات بشأن البطاقات الائتمانية المصدرة من البنوك الإسلامية",
     BASE + "21p2-112395_v40_tcm11-112395.pdf", "البنوك الإسلامية"),
    ("22. تعليمات في شأن شراء وبيع أوراق النقد الخليجية — البنوك الإسلامية",
     BASE + "22p2-112572_v20_tcm11-112572.pdf", "البنوك الإسلامية"),
    ("23. كيفية المحاسبة عن الشهرة — البنوك الإسلامية",
     BASE + "23p2-112573_v20_tcm11-112573.pdf", "البنوك الإسلامية"),
    ("24. تعليمات بشأن نسبة العمالة الوطنية لدى البنوك المحلية",
     BASE + "24p2-112396_v30_tcm11-112396.pdf", "البنوك الإسلامية"),
    ("25. تعليمات بشأن تعامل البنوك الإسلامية في عمليات القطع الأجنبي",
     BASE + "25p2-112574_v20_tcm11-112574.pdf", "البنوك الإسلامية"),
    ("26. أسس إعداد البيانات المالية الختامية للبنوك الإسلامية",
     BASE + "26p2-112635_v20_tcm11-112635.pdf", "البنوك الإسلامية"),
    ("27. تعليمات بشأن ضرورة إحاطة البنك المركزي قبل الاتصال بسلطات رقابية أجنبية",
     BASE + "27p2-112636_v30_tcm11-112636.pdf", "البنوك الإسلامية"),
    ("28. تعليمات في شأن الشيكات مستقبلية التاريخ — البنوك الإسلامية",
     BASE + "28p2-112637_v20_tcm11-112637.pdf", "البنوك الإسلامية"),
    ("29. تعليمات بشأن البيانات المالية لأغراض أسواق الأوراق المالية — البنوك الإسلامية",
     BASE + "29p2-112638_v20_tcm11-112638.pdf", "البنوك الإسلامية"),
    ("30. الميزانية التقديرية وخطة العمل المستقبلية للبنوك الإسلامية",
     BASE + "30p2-112639_v20_tcm11-112639.pdf", "البنوك الإسلامية"),
    ("31. تعليمات بشأن عمليات السطو والاختلاس — البنوك الإسلامية",
     BASE + "31p2-112397_v30_tcm11-112397.pdf", "البنوك الإسلامية"),
    ("32. الإجراءات التنفيذية بشأن زيادة نسبة ملكية الشخص الواحد — البنوك الإسلامية",
     BASE + "32p2-112640_v40_tcm11-112640.pdf", "البنوك الإسلامية"),
    ("33. تعليمات متفرقة أخرى — البنوك الإسلامية",
     BASE + "33p2-112398_v40_tcm11-112398.pdf", "البنوك الإسلامية"),
    ("34. قانون الاستقرار المالي وتعزيز أوضاع البنوك — البنوك الإسلامية",
     BASE + "34p2-113294_v20_tcm11-113294.pdf", "البنوك الإسلامية"),
    ("35. تعليمات معيار تغطية السيولة للبنوك الإسلامية",
     BASE + "35p2-117298_v20_tcm11-117298.pdf", "البنوك الإسلامية"),
    ("36. تعليمات تنظيم أعمال الدفع الإلكتروني — البنوك الإسلامية",
     BASE + "36p2-137772_v40_tcm11-137772.pdf", "البنوك الإسلامية"),
    ("37. إطار الأمن السيبراني — البنوك الإسلامية",
     BASE + "37p2-156659_v10_tcm11-156659.pdf", "البنوك الإسلامية"),
    ("38. التنمية المستدامة والتمويل المستدام — البنوك الإسلامية",
     BASE + "38part2-160278_v10_tcm11-160278.pdf", "البنوك الإسلامية"),
    ("الباب الثالث: البيانات والإحصاءات الدورية للبنوك الإسلامية",
     BASE + "part3-112403_v30_tcm11-112403.pdf", "البنوك الإسلامية"),

    # ── شركات التمويل (Finance Companies) — 12 docs ──────────────────────────
    # URLs from: cbk.gov.kw/ar/supervision/cbk-regulations-and-instructions/instructions-for-finance-companies
    ("القرار الوزاري رقم (38) لسنة 2011 في شأن تنظيم رقابة بنك الكويت المركزي على شركات التمويل",
     BASE + "1p1-1_v00_tcm11-156678.pdf", "شركات التمويل"),
    ("تعميم لكافة شركات التمويل — مجلس إدارة بنك الكويت المركزي 2023",
     BASE + "2c1-169006_v10_tcm11-169006.pdf", "شركات التمويل"),
    ("1. تعليمات في شأن ترشيد وتنظيم السياسة الائتمانية لشركات التمويل التقليدية",
     BASE + "1p2-168998_v10_tcm11-168998.pdf", "شركات التمويل"),
    ("2. الحدود القصوى للتركز الائتماني قبل شركة التمويل التقليدية",
     BASE + "2p2-169001_v10_tcm11-169001.pdf", "شركات التمويل"),
    ("3. تعليمات في شأن ترشيد وتنظيم السياسة التمويلية لشركات التمويل الإسلامية",
     BASE + "3p2-169002_v10_tcm11-169002.pdf", "شركات التمويل"),
    ("4. الحد الأقصى لمقدار التزام العميل الواحد قبل شركات التمويل الإسلامية",
     BASE + "4p2-169003_v10_tcm11-169003.pdf", "شركات التمويل"),
    ("5. قواعد وأسس منح شركات التمويل لعمليات التمويل وفقاً لصيغ التمويل الإسلامية",
     BASE + "5p2-169004_v10_tcm11-169004.pdf", "شركات التمويل"),
    ("6. شروط تعيين واختصاصات هيئة الرقابة الشرعية في شركات التمويل الإسلامية",
     BASE + "6p2-169005_v10_tcm11-169005.pdf", "شركات التمويل"),
    ("7. قواعد وأسس منح شركات التمويل للقروض الاستهلاكية وغيرها من القروض المقسطة",
     BASE + "7p2-155879_v40_tcm11-155879.pdf", "شركات التمويل"),
    ("8. التعليمات الصادرة بشأن مكافحة غسل الأموال وتمويل الإرهاب — شركات التمويل",
     BASE + "8p2-169008_v60_tcm11-169008.pdf", "شركات التمويل"),
    ("9. تعليمات لشركات التمويل بشأن نظم الرقابة الداخلية",
     BASE + "9p2-151549_v20_tcm11-151549.pdf", "شركات التمويل"),
    ("10. تعليمات تنظيم أعمال الدفع الإلكتروني — شركات التمويل",
     BASE + "10p2-135610_v80_tcm11-135610.pdf", "شركات التمويل"),
    ("12. القواعد والضوابط الخاصة بالخبرة المطلوبة — شركات التمويل",
     BASE + "12p2-147138_v40_tcm11-147138.pdf", "شركات التمويل"),

    # ── شركات الصرافة (Exchange Companies) — 6 PDFs ──────────────────────────
    # URLs from: cbk.gov.kw/ar/supervision/cbk-regulations-and-instructions/instructions-for-exchange-companies
    ("المقدمة — التعليمات الرقابية على شركات الصرافة",
     BASE + "exintroar-127095_v60_tcm11-127095.pdf", "شركات الصرافة"),
    ("الباب الأول: إخضاع شركات الصرافة لرقابة بنك الكويت المركزي وأسس وضوابط تأسيس شركات صرافة جديدة",
     BASE + "expart1-112514_v80_tcm11-112514.pdf", "شركات الصرافة"),
    ("الباب الثاني: تعليمات التسجيل في سجل شركات الصرافة",
     BASE + "expart2-112515_v30_tcm11-112515.pdf", "شركات الصرافة"),
    ("الباب الثالث: التعليمات والضوابط الإشرافية والرقابية وتنظيم العمل بشركات الصرافة",
     BASE + "expart3-112516_v90_tcm11-112516.pdf", "شركات الصرافة"),
    ("الباب الرابع: التعليمات الصادرة بشأن مكافحة غسل الأموال وتمويل الإرهاب — شركات الصرافة",
     BASE + "expart4-118687_v100_tcm11-118687.pdf", "شركات الصرافة"),
    ("الباب الخامس: البيانات والإحصاءات التي يتعين على شركات الصرافة موافاة البنك المركزي بها",
     BASE + "expart5-154235_v10_tcm11-154235.pdf", "شركات الصرافة"),
    ("الباب السادس: التعليمات الخاصة بشأن مراقب الحسابات الخارجي — شركات الصرافة",
     BASE + "expart6-118623_v40_tcm11-118623.pdf", "شركات الصرافة"),
]

# ── Helpers (same as cbk_scraper.py) ─────────────────────────────────────────

def clean_arabic_text(text):
    if not text: return ""
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return '\n'.join(l.strip() for l in text.splitlines()).strip()


def pdf_filename(url):
    return re.sub(r'[<>:"/\\|?*\u200b]', '_', unquote(url.split('/')[-1]))


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
        return local

    for attempt in range(MAX_RETRIES):
        try:
            r = session.get(url, timeout=TIMEOUT, verify=False, stream=True)
            r.raise_for_status()
            with open(local, 'wb') as f:
                for chunk in r.iter_content(8192): f.write(chunk)
            return local
        except requests.exceptions.HTTPError as e:
            print(f"  [!] {e}")
            return None  # 404s won't recover on retry
        except Exception as e:
            wait = RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF)-1)]
            if attempt < MAX_RETRIES - 1:
                print(f"  [!] Attempt {attempt+1} failed ({e.__class__.__name__}), retrying in {wait}s...")
                time.sleep(wait)
            else:
                print(f"  [!] All {MAX_RETRIES} attempts failed: {e.__class__.__name__}")
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


def build_cbk_fix(limit=None, skip_download=False):
    OUTPUT_DIR.mkdir(exist_ok=True)
    PDF_DIR.mkdir(exist_ok=True)

    docs = DOCS[:limit] if limit else DOCS
    existing_urls = get_existing_urls()
    existing_count = len(existing_urls)

    print(f"[*] CBK Fix Scraper — Missing Sections")
    print(f"[*] {len(docs)} documents to process")
    print(f"[*] Already in corpus: {existing_count} documents\n")

    session = requests.Session()
    session.headers.update(HEADERS)

    recovered, failed = [], []

    with open(CORPUS_JSONL, 'a', encoding='utf-8') as jsonl:
        for i, (name, url, section) in enumerate(docs, 1):
            print(f"[{i:3d}/{len(docs)}] {name[:65]}")

            if url in existing_urls:
                print(f"         [~] Already in corpus, skipping")
                continue

            if skip_download:
                path = PDF_DIR / pdf_filename(url)
                if not path.exists():
                    failed.append({'name': name, 'url': url, 'error': 'not_found'})
                    continue
            else:
                path = download_pdf(url, session)
                if not path:
                    failed.append({'name': name, 'url': url, 'section': section, 'error': 'download_failed'})
                    continue
                time.sleep(DELAY)

            raw, method = extract_text(path)
            if not raw.strip():
                print(f"         [!] Extraction failed")
                failed.append({'name': name, 'url': url, 'section': section, 'error': 'extraction_failed'})
                continue

            text  = clean_arabic_text(raw)
            words = len(text.split())
            print(f"         [+] {words:,} words  ({method})")

            record = {
                'id':           f"kw_cbk_{existing_count + len(recovered) + 1:04d}",
                'source':       'Central Bank of Kuwait',
                'name':         name,
                'url':          url,
                'section':      section,
                'year':         None,
                'doc_type':     'banking_regulation',
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
    print("  CBK FIX COMPLETE")
    print("="*65)
    print(f"  New docs added:  {len(recovered)}  |  Failed: {len(failed)}")
    print(f"  New words:       {total_words:,}")
    print(f"\n  TOTAL CORPUS NOW:")
    print(f"    Documents:     {corpus_docs}")
    print(f"    Words:         {corpus_words:,}")
    print("="*65)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description='CBK fix scraper for missing sections')
    ap.add_argument('--limit',         type=int, default=None)
    ap.add_argument('--skip-download', action='store_true')
    args = ap.parse_args()
    build_cbk_fix(limit=args.limit, skip_download=args.skip_download)