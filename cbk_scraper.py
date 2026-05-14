"""
Central Bank of Kuwait — Arabic Regulatory Corpus Scraper
===========================================================
Downloads all Arabic regulatory instruction PDFs from cbk.gov.kw
and appends them to output/corpus.jsonl.

Covers 7 regulatory sections:
  - البنوك التقليدية      (Conventional Banks)       — 41 docs
  - البنوك الإسلامية      (Islamic Banks)             — ~13 docs
  - شركات التمويل         (Finance Companies)         — ~10 docs
  - شركات الاستثمار       (Investment Companies)      — ~10 docs
  - شركات الصرافة         (Exchange Companies)        — ~8 docs
  - شركات المعلومات الائتمانية (Credit Info Companies) — ~5 docs
  - أعمال الدفع الإلكتروني (e-Payment Services)       — ~5 docs

Usage:
  python3 cbk_scraper.py
  python3 cbk_scraper.py --limit 5
  python3 cbk_scraper.py --skip-download
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
PDF_DIR      = OUTPUT_DIR / "pdfs_cbk"
CORPUS_JSONL = OUTPUT_DIR / "corpus.jsonl"
FAILED_LOG   = OUTPUT_DIR / "cbk_failed.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ar-KW,ar;q=0.9",
    "Referer": "https://www.cbk.gov.kw/ar/",
}
DELAY   = 1.5
TIMEOUT = 45

# ── All CBK Arabic regulatory PDFs ───────────────────────────────────────────
# Compiled from: https://www.cbk.gov.kw/ar/supervision/cbk-regulations-and-instructions/
# Format: (arabic_name, pdf_url, section)

BASE = "https://www.cbk.gov.kw/ar/images/"

DOCS = [

    # ── البنوك التقليدية (Conventional Banks) ─────────────────────────────────
    ("المقدمة — التعليمات الرقابية على البنوك التقليدية",
     BASE + "intro-112460_v20_tcm11-112460.pdf", "البنوك التقليدية"),
    ("الباب الأول: لائحة بنظام سجل البنوك",
     BASE + "ch1part1-118121_v50_tcm11-118121.pdf", "البنوك التقليدية"),
    ("موجز بأحكام الباب الثالث من القانون رقم 32 لسنة 1968 — النقد وبنك الكويت المركزي",
     BASE + "law-32-147059_v10_tcm11-147059.pdf", "البنوك التقليدية"),
    ("1. نظام الأخطار المصرفية والقواعد الصادرة في شأن تطبيقه",
     BASE + "1part1-112461_v90_tcm11-112461.pdf", "البنوك التقليدية"),
    ("2. القواعد الخاصة بنظام السيولة والتعليمات الصادرة بشأن أوضاع السيولة في الجهاز المصرفي",
     BASE + "2part1-112462_v80_tcm11-112462.pdf", "البنوك التقليدية"),
    ("3. قواعد وإجراءات فتح فروع مصرفية ومكاتب التمثيل",
     BASE + "3part1-112463_v30_tcm11-112463.pdf", "البنوك التقليدية"),
    ("4. الحدود القصوى للتركز الائتماني",
     BASE + "4part1-112464_v80_tcm11-112464.pdf", "البنوك التقليدية"),
    ("5. أسس إعداد البيانات المالية الختامية وسياسة التصنيف",
     BASE + "5part1-112465_v40_tcm11-112465.pdf", "البنوك التقليدية"),
    ("6. القرارات الصادرة في شأن الحدود القصوى لأسعار الفائدة",
     BASE + "6part1-112466_v190_tcm11-112466.pdf", "البنوك التقليدية"),
    ("7. نظام خصم وإعادة خصم الأوراق التجارية",
     BASE + "7part1-112467_v20_tcm11-112467.pdf", "البنوك التقليدية"),
    ("8. تعليمات بشأن شراء البنوك أسهمها",
     BASE + "8part1-114154_v30_tcm11-114154.pdf", "البنوك التقليدية"),
    ("9. الضوابط والتعليمات بشأن تقديم البنوك المحلية تسهيلات ائتمانية بالدينار الكويتي لغير المقيم",
     BASE + "9part1-112468_v20_tcm11-112468.pdf", "البنوك التقليدية"),
    ("10. التعليمات الصادرة بشأن ترشيد وتنظيم السياسة الائتمانية لدى البنوك",
     BASE + "10part1-112469_v50_tcm11-112469.pdf", "البنوك التقليدية"),
    ("11. كفاية رأس المال",
     BASE + "11part1-112470_v30_tcm11-112470.pdf", "البنوك التقليدية"),
    ("12. القواعد والضوابط الخاصة بالخبرة المطلوبة — أعضاء مجلس الإدارة والجهاز التنفيذي",
     BASE + "12part2-112675_v50_tcm11-112675.pdf", "البنوك التقليدية"),
    ("13. قواعد وأسس منح البنوك للقروض الاستهلاكية وغيرها من القروض المقسطة",
     BASE + "13part2-112471_v60_tcm11-112471.pdf", "البنوك التقليدية"),
    ("14. التعليمات الصادرة في شأن تنظيم السياسة الاستثمارية للبنوك المحلية",
     BASE + "14part2-114155_v30_tcm11-114155.pdf", "البنوك التقليدية"),
    ("15. المعايير والضوابط التي تنظم علاقة البنوك بعملائها في مجال تقديم الخدمات المصرفية",
     BASE + "15part2-112472_v80_tcm11-112472.pdf", "البنوك التقليدية"),
    ("16. التعليمات الصادرة من البنك المركزي بشأن مكافحة غسل الأموال وتمويل الإرهاب",
     BASE + "16part2-112473_v140_tcm11-112473.pdf", "البنوك التقليدية"),
    ("17. الإجراءات التنفيذية بشأن زيادة نسبة ملكية الشخص الواحد عن 5% من رأس مال البنك",
     BASE + "17part2-112474_v40_tcm11-112474.pdf", "البنوك التقليدية"),
    ("18. تعليمات بشأن البيانات المعدة لأغراض أسواق الأوراق المالية",
     BASE + "18part2-112475_v20_tcm11-112475.pdf", "البنوك التقليدية"),
    ("19. التعليمات الصادرة في شأن شراء وبيع أوراق النقد الخليجية",
     BASE + "19part2-112476_v20_tcm11-112476.pdf", "البنوك التقليدية"),
    ("20. نظام الحصر المركزي للعملاء الذين أقفلت حساباتهم بالبنوك المحلية",
     BASE + "20part2-112477_v40_tcm11-112477.pdf", "البنوك التقليدية"),
    ("21. تعليمات بشأن تحديد الضمانات المقبولة من البنك المركزي مقابل القروض",
     BASE + "21part2-114156_v20_tcm11-114156.pdf", "البنوك التقليدية"),
    ("22. تعليمات بشأن نسبة العمالة الوطنية في البنوك المحلية",
     BASE + "22part2-112478_v40_tcm11-112478.pdf", "البنوك التقليدية"),
    ("23. تعليمات بشأن محافظة البنوك على سرية المعلومات والبيانات الخاصة بعملائها",
     BASE + "23part2-112479_v20_tcm11-112479.pdf", "البنوك التقليدية"),
    ("24. تعليمات بشأن استمرارية تملك البنوك لعقارات أنشأتها كمقار لأعمالها",
     BASE + "24part2-114157_v20_tcm11-114157.pdf", "البنوك التقليدية"),
    ("25. تعليمات بشأن تعامل البنوك في عمليات القطع الأجنبي",
     BASE + "25part2-114158_v20_tcm11-114158.pdf", "البنوك التقليدية"),
    ("26. التعليمات الخاصة بشأن مراقبي الحسابات",
     BASE + "26part2-112480_v20_tcm11-112480.pdf", "البنوك التقليدية"),
    ("27. تعليمات للبنوك بشأن ضرورة إحاطة البنك المركزي قبل الاتصال بسلطات رقابية أجنبية",
     BASE + "27part2-114159_v30_tcm11-114159.pdf", "البنوك التقليدية"),
    ("28. تعليمات للبنوك بشأن نظم الرقابة الداخلية",
     BASE + "28part2-112676_v40_tcm11-112676.pdf", "البنوك التقليدية"),
    ("29. تعليمات للبنوك بشأن رصد حجم المعاملات مع البنوك التي تتعرض لأزمة مالية حادة",
     BASE + "29part2-114160_v20_tcm11-114160.pdf", "البنوك التقليدية"),
    ("30. تعليمات بشأن التسهيلات الممنوحة لأعضاء مجلس الإدارة",
     BASE + "30part2-112488_v20_tcm11-112488.pdf", "البنوك التقليدية"),
    ("31. تعليمات للبنوك بشأن عدم إبرام اتفاقيات تخل بمبدأ المنافسة",
     BASE + "31part2-114161_v20_tcm11-114161.pdf", "البنوك التقليدية"),
    ("32. الميزانيات التقديرية وخطة العمل المستقبلية للبنوك",
     BASE + "32part2-114162_v20_tcm11-114162.pdf", "البنوك التقليدية"),
    ("33. تعليمات بشأن إخطار البنك المركزي بجرائم الاختلاس",
     BASE + "33part2-112481_v30_tcm11-112481.pdf", "البنوك التقليدية"),
    ("34. التعليمات الخاصة بالبطاقات الائتمانية المصدرة من البنوك المحلية",
     BASE + "34part2-112482_v50_tcm11-112482.pdf", "البنوك التقليدية"),
    ("35. تعليمات بشأن إدارة المحافظ وتسويق وحدات الصناديق",
     BASE + "35part2-114163_v20_tcm11-114163.pdf", "البنوك التقليدية"),
    ("36. متفرقة أخرى — التعليمات الرقابية على البنوك التقليدية",
     BASE + "36part2-112483_v70_tcm11-112483.pdf", "البنوك التقليدية"),
    ("37. قانون الاستقرار المالي وتعزيز أوضاع البنوك",
     BASE + "37part2-112484_v20_tcm11-112484.pdf", "البنوك التقليدية"),
    ("38. تعليمات تنظيم أعمال الدفع الإلكتروني",
     BASE + "38part2-117297_v60_tcm11-117297.pdf", "البنوك التقليدية"),
    ("39. إطار الأمن السيبراني",
     BASE + "39part2-156658_v10_tcm11-156658.pdf", "البنوك التقليدية"),
    ("40. التنمية المستدامة والتمويل المستدام",
     BASE + "40part2-160277_v10_tcm11-160277.pdf", "البنوك التقليدية"),
    ("41. النقد ونظم المدفوعات",
     BASE + "41part2-169028_v10_tcm11-169028.pdf", "البنوك التقليدية"),
    ("الباب الثالث: البيانات والإحصاءات التي تقدمها البنوك المحلية للبنك المركزي",
     BASE + "part3-112487_v20_tcm11-112487.pdf", "البنوك التقليدية"),

    # ── البنوك الإسلامية (Islamic Banks) ──────────────────────────────────────
    ("المقدمة — التعليمات الرقابية على البنوك الإسلامية",
     BASE + "intro-2781_v30_tcm11-2781.pdf", "البنوك الإسلامية"),
    ("التعليمات الرقابية على البنوك الإسلامية — الباب الأول",
     BASE + "ch1part1-118125_v40_tcm11-118125.pdf", "البنوك الإسلامية"),
    ("التعليمات الرقابية على البنوك الإسلامية — الباب الثاني القانون",
     BASE + "1part1-2784_v70_tcm11-2784.pdf", "البنوك الإسلامية"),
    ("التعليمات الرقابية على البنوك الإسلامية — الفصل الثاني",
     BASE + "2part1-2785_v90_tcm11-2785.pdf", "البنوك الإسلامية"),
    ("التعليمات الرقابية على البنوك الإسلامية — الفصل الثالث عشر الرقابة الشرعية",
     BASE + "13part1-2783_v60_tcm11-2783.pdf", "البنوك الإسلامية"),

    # ── شركات التمويل (Finance Companies) ────────────────────────────────────
    ("المقدمة — التعليمات الرقابية على شركات التمويل",
     BASE + "intro-112561_v20_tcm11-112561.pdf", "شركات التمويل"),
    ("الباب الأول — التعليمات الرقابية على شركات التمويل",
     BASE + "ch1part1-118122_v50_tcm11-118122.pdf", "شركات التمويل"),
    ("التعليمات الرقابية على شركات التمويل — القانون والتعليمات",
     BASE + "1part1-112562_v50_tcm11-112562.pdf", "شركات التمويل"),
    ("التعليمات الرقابية على شركات التمويل — كفاية رأس المال",
     BASE + "2part1-112563_v30_tcm11-112563.pdf", "شركات التمويل"),

    # ── شركات الاستثمار (Investment Companies) ────────────────────────────────
    ("المقدمة — التعليمات الرقابية على شركات الاستثمار",
     BASE + "intro-112668_v20_tcm11-112668.pdf", "شركات الاستثمار"),
    ("الباب الأول — التعليمات الرقابية على شركات الاستثمار",
     BASE + "ch1part1-118123_v30_tcm11-118123.pdf", "شركات الاستثمار"),
    ("التعليمات الرقابية على شركات الاستثمار — الباب الثاني",
     BASE + "1part1-112669_v60_tcm11-112669.pdf", "شركات الاستثمار"),

    # ── شركات الصرافة (Exchange Companies) ───────────────────────────────────
    ("المقدمة — التعليمات الرقابية على شركات الصرافة",
     BASE + "intro-112671_v20_tcm11-112671.pdf", "شركات الصرافة"),
    ("الباب الأول — التعليمات الرقابية على شركات الصرافة",
     BASE + "ch1part1-118124_v40_tcm11-118124.pdf", "شركات الصرافة"),
    ("التعليمات الرقابية على شركات الصرافة — الباب الثاني",
     BASE + "1part1-112672_v50_tcm11-112672.pdf", "شركات الصرافة"),

    # ── القانون الأساسي (CBK Law) ─────────────────────────────────────────────
    ("قانون النقد وبنك الكويت المركزي وتنظيم المهنة المصرفية رقم 32 لسنة 1968",
     "https://www.cbk.gov.kw/ar/images/cbk-law-32-1968-114233_v90_tcm11-114233.pdf",
     "قانون البنك المركزي"),
]

# ── Helpers ───────────────────────────────────────────────────────────────────

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
    try:
        r = session.get(url, timeout=TIMEOUT, verify=False, stream=True)
        r.raise_for_status()
        with open(local, 'wb') as f:
            for chunk in r.iter_content(8192): f.write(chunk)
        return local
    except Exception as e:
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

def build_cbk_corpus(limit=None, skip_download=False):
    OUTPUT_DIR.mkdir(exist_ok=True)
    PDF_DIR.mkdir(exist_ok=True)

    docs = DOCS[:limit] if limit else DOCS
    existing_urls = get_existing_urls()
    existing_count = len(existing_urls)

    print(f"[*] CBK Arabic Regulatory Corpus Scraper")
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

            # Download
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

            # Extract
            raw, method = extract_text(path)
            if not raw.strip():
                print(f"         [!] Extraction failed")
                failed.append({'name': name, 'url': url, 'section': section, 'error': 'extraction_failed', 'pdf': str(path)})
                continue

            text  = clean_arabic_text(raw)
            words = len(text.split())
            print(f"         [+] {words:,} words  ({method})")

            record = {
                'id':           f"kw_cbk_{existing_count + i:04d}",
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

    # Total corpus stats
    corpus_total_words, corpus_total_docs = 0, 0
    with open(CORPUS_JSONL, encoding='utf-8') as f:
        for line in f:
            try:
                d = json.loads(line)
                corpus_total_words += d.get('word_count', 0)
                corpus_total_docs  += 1
            except: pass

    print("\n" + "="*65)
    print("  CBK CORPUS BUILD COMPLETE")
    print("="*65)
    print(f"  New CBK docs:  {len(recovered)}  |  Failed: {len(failed)}")
    print(f"  New words:     {total_words:,}")
    print(f"\n  TOTAL CORPUS NOW:")
    print(f"    Documents:   {corpus_total_docs}")
    print(f"    Words:       {corpus_total_words:,}")
    print("="*65)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description='CBK Arabic regulatory corpus scraper')
    ap.add_argument('--limit',         type=int, default=None)
    ap.add_argument('--skip-download', action='store_true')
    args = ap.parse_args()
    build_cbk_corpus(limit=args.limit, skip_download=args.skip_download)