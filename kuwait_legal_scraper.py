"""
Kuwait Ministry of Justice — Legal Corpus Scraper
===================================================
Downloads all Kuwaiti law PDFs from moj.gov.kw,
extracts Arabic text, and saves structured JSONL
ready for embedding model training.

The law list was compiled from the MOJ laws page:
  https://www.moj.gov.kw/AR/Pages/MojLaws.aspx

Output:
  output/pdfs/            — downloaded PDFs
  output/corpus.jsonl     — one JSON record per law (use for training)
  output/corpus_full.json — metadata summary
  output/failed.json      — failures to review

Usage:
  python kuwait_legal_scraper.py                   # full run
  python kuwait_legal_scraper.py --limit 5         # test first 5
  python kuwait_legal_scraper.py --skip-download   # re-extract existing PDFs
"""

import os, re, json, time, argparse
import requests, pdfplumber, fitz
from pathlib import Path
from urllib.parse import unquote
from datetime import datetime
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ── All laws from moj.gov.kw/AR/Pages/MojLaws.aspx ───────────────────────────
# Format: (display_name, pdf_url)
BASE = "https://www.moj.gov.kw/AR/Documents/MojDocs/"

LAWS = [
    # 1962
    ("الدستور الكويتي",
     BASE + "دستور الكويت.pdf"),

    # 1973
    ("قانون رقم 14 لسنه 1973 بشأن إنشاء المحكمة الدستورية",
     BASE + "قانون رقم 14 لسنه 1973 بشأن إنشاء المحكمة الدستورية.pdf"),

    # 1980
    ("قانون رقم 28 لسنه 1980 باصدار قانون التجارة البحرية",
     BASE + "قانون رقم 28 لسنه 1980 باصدار قانـــون التجارة البحرية.pdf"),
    ("قانون رقم 38 لسنة 1980 بإصدار قانون المرافعات المدنية والتجارية وتعديلاته",
     BASE + "قانون رقم 38 لسنة 1980 بإصدار قانون المرافعات المد​نية والتجارية و تعديلاته.pdf"),
    ("قانون رقم 67 لسنة 1980 بإصدار القانون المدني",
     BASE + "قانون رقم 67 لسنة 1980 بإصدار القانون المدني.pdf"),
    ("قانون رقم 68 لسنه 1980 باصدار قانون التجارة",
     BASE + "قانون رقم 68 لسنه 1980 باصدار قانون التجارة وقانون في شأن التوحيد القياسي.pdf"),

    # 1995
    ("قانون رقم 6 لسنة 1995 الاتفاقية العربية لمكافحة الاتجار بالمخدرات",
     BASE + "قانون رقم 6 لسنة 1995 بالموافقة على الاتفاقية العربية لمكافحة الاتجار غير المشروع بالمخدرات والمؤثرات العقلية.pdf"),

    # 1996
    ("قانون رقم 12 لسنة 1996 العهد الدولي الخاص بالحقوق المدنية والسياسية",
     BASE + "قانون رقم 12 لسنة 1996بالموافقة على العهد الدولي الخاص بالحقوق المدنية والسياسية.pdf"),

    # 2000
    ("قانون رقم 25 لسنة 2000 اتفاقية الأمم المتحدة لمكافحة المخدرات",
     BASE + "قانون رقم 25 لسنة 2000 بالموافقة على اتفاقية الامم المتحدة لمكافحة الاتجار غير المشروع في المخدرات والمؤثرات العقلية.pdf"),

    # 2002
    ("قرار وزاري رقم 17 لسنة 2002 في شأن مكافحة غسل الأموال وتمويل الإرهاب",
     BASE + "Law17-2002.pdf"),

    # 2006
    ("قانون رقم 5 لسنة 2006 اتفاقية الأمم المتحدة لمكافحة الجريمة المنظمة",
     BASE + "قانون رقم 5 لسنة 2006 بالموافقة على اتفاقية الامم المتحدة لمكافحة الجريمة المنظمة عبر الوطنية والبروتوكولين المقترنين بها.pdf"),
    ("قانون رقم 47 لسنة 2006 اتفاقية الأمم المتحدة لمكافحة الفساد",
     BASE + "قانون رقم 47 لسنة 2006 بالموافقة على اتفاقية الأمم المتحدة لمكافحة الفساد.pdf"),
    ("قانون رقم 3 لسنه 2006 بشأن المطبوعات والنشر",
     BASE + "قانون رقم 3 لسنه 2006 بشأن المطبوعات والنشر.pdf"),

    # 2007
    ("قانون رقم 61 لسنة 2007 بشأن الإعلام المرئي والمسموع",
     BASE + "قانون رقم 61 لسنة 2007 بشأن الإعلام المرئي والمسموع.pdf"),
    ("قانون الأحوال الشخصية وتعديلاته",
     BASE + "قانون الاحوال الشخصية وتعديلاته.pdf"),

    # 2010
    ("قانون رقم 6 لسنة 2010 قانون العمل في القطاع الأهلي",
     BASE + "قانون رقم 6 لسنة 2010 بإصدار قانون العمل في القطاع الاهلي.pdf"),
    ("قانون رقم 7 لسنة 2010 بشأن إنشاء هيئة أسواق المال",
     BASE + "قانون رقم 7 لسنة 2010 بشأن انشاء هيئة أسواق المال وتنظيم نشاط الأوراق المالية.pdf"),

    # 2013
    ("قانون رقم 106 لسنة 2013 في شأن مكافحة غسل الأموال وتمويل الإرهاب",
     BASE + "Law106-2013.pdf"),
    ("قرار وزاري رقم 37 لسنة 2013 اللائحة التنفيذية لقانون مكافحة غسل الأموال",
     BASE + "Law37-2013.pdf"),
    ("قانون رقم 85 لسنة 2013 الاتفاقية الدولية لقمع تمويل الإرهاب",
     BASE + "القانون 85 لسنة 2013 الاتفاقية الدولية لقمع تمويل الإرهاب.pdf"),
    ("قانون رقم 91 لسنة 2013 بشأن مكافحة الاتجار بالأشخاص وتهريب المهاجرين",
     BASE + "قانون رقم 91 لسنة 2013 بشأن مكافحة الاتجار بالأشخاص و تهريب المهاجرين.pdf"),
    ("قانون رقم 92 لسنة 2013 الاتفاقية العربية لمكافحة الفساد",
     BASE + "قانون رقم 92 لسنة 2013 بالموافقة على الاتفاقية العربية لمكافحة الفساد.pdf"),
    ("قانون رقم 93 لسنة 2013 الاتفاقية العربية لمكافحة غسل الأموال",
     BASE + "قانون رقم 93 لسنة 2013 بالموافقة على الاتفاقية العربية لمكافحة غسل الأموال وتمويل الارهاب.pdf"),
    ("قانون رقم 94 لسنة 2013 الاتفاقية العربية لمكافحة الجريمة المنظمة",
     BASE + "قانون رقم 94 لسنة 2013 بالموافقة على الاتفاقية العربية لمكافحة الجريمة المنظمة عبر الحدود الوطنية.pdf"),

    # 2014
    ("قرار وزاري رقم 4 لسنة 2014 اللجنة الخاصة بتنفيذ قرارات مجلس الأمن",
     BASE + "Law4-2014.pdf"),
    ("قرار وزاري رقم 5 لسنة 2014 اللائحة التنفيذية لقرارات مجلس الأمن",
     BASE + "Law5-2014.pdf"),
    ("قرار وزاري رقم 24 لسنة 2014 الإجراءات الجمركية لغسل الأموال",
     BASE + "Law24-2014.pdf"),
    ("قانون رقم 20 لسنة 2014 بإصدار قانون المعاملات الإلكترونية",
     BASE + "قانون رقم 20 لسنة 2014 بإصدار قانون المعاملات الالكترونية.pdf"),
    ("قانون رقم 37 لسنة 2014 بإنشاء هيئة تنظيم الاتصالات وتقنية المعلومات",
     BASE + "قانون رقم 37 لسنة 2014 بإنشاء هيئة تنظيم الاتصالات وتقنية المعلومات​.pdf"),
    ("قانون رقم 42 لسنة 2014 بإصدار قانون حماية البيئة",
     BASE + "قانون رقم 42 لسنة 2014 بإصدار قانون حماية البيئة.pdf"),

    # 2015
    ("قرار وزاري رقم 55 لسنة 2015 نظام اللجنة الوطنية لمكافحة غسل الأموال",
     BASE + "Law55-2015.pdf"),
    ("قانون رقم 68 لسنة 2015 في شأن العمالة المنزلية",
     BASE + "Law68-2015.pdf"),
    ("قانون رقم 12 لسنة 2015 بإصدار قانون محكمة الأسرة",
     BASE + "قانون رقم 12 لسنة 2015 بإصدار قانون محكمة الأسرة.pdf"),
    ("قانون رقم 21 لسنة 2015 بإصدار قانون حقوق الطفل",
     BASE + "قانون رقم 21 لسنة 2015 بإصدار قانون حقوق الطفل.pdf"),
    ("قانون رقم 63 لسنة 2015 بإصدار قانون مكافحة جرائم تقنية المعلومات",
     BASE + "قانون رقم 63 لسنة 2015 بإصدار قانون مكافحة جرائم تقنية المعلومات.pdf"),
    ("قانون رقم 111 لسنة 2015 بإصدار قانون الأحداث",
     BASE + "قانون رقم 111 لسنة 2015 بإصدار قانون الأحداث.pdf"),

    # 2016
    ("قرار وزاري رقم 432 لسنة 2016 النظام الخاص لتنفيذ قرارات مجلس الأمن",
     BASE + "Law432-2016.pdf"),
    ("قانون رقم 24 لسنة 2016 تعديل قانون مكافحة غسل الأموال",
     BASE + "Law24-2016.pdf"),
    ("قانون رقم 1 لسنه 2016 بشأن إصدار قانون الشركات",
     BASE + "قانون رقم 1 لسنه 2016 بشأن اصدار قانون الشركات.pdf"),
    ("قانون رقم 2 لسنه 2016 بشأن إنشاء الهيئة العامة لمكافحة الفساد",
     BASE + "قانون رقم 2 لسنه 2016 بشأن إنشاء الهيئة العامة لمكافحة الفساد والأحكام الخاصة بالكشف عن الذمة المالية.pdf"),
    ("قانون رقم 8 لسنة 2016 بتنظيم الإعلام الإلكتروني",
     BASE + "قانون رقم 8 لسنة 2016 بتنظيم الإعلام الإلكتروني.pdf"),
    ("قانون رقم 33 لسنة 2016 بشأن بلدية الكويت",
     BASE + "قانون رقم 33 لسنة 2016 بشأن بلدية الكويت.pdf"),

    # 2017
    ("مرسوم رقم 192 لسنة 2017 بالموافقة على مذكرة تفاهم مكافحة تمويل الإرهاب",
     BASE + "Law192-2017.pdf"),

    # 2018
    ("قرار رقم 135 لسنة 2018 تعديل أحكام اللائحة التنفيذية لهيئة أسواق المال",
     BASE + "Law135-2018.pdf"),

    # 2019
    ("قرار رقم 43 لسنة 2019 تعديل أحكام مكافحة غسل الأموال",
     BASE + "Law43-2019.pdf"),
    ("قرار وزاري رقم 382 لسنة 2019 قواعد مصفوفة المخالفات",
     BASE + "Law382-2019.pdf"),
    ("قرار وزاري رقم 86 لسنة 2019 آلية منح الضبطية القضائية",
     BASE + "Law86-2019.pdf"),
    ("قرار وزاري رقم 35 لسنة 2019 اللائحة التنفيذية للجنة مجلس الأمن",
     BASE + "Law35-2019.pdf"),
    ("المذكرات الإيضاحية للقوانين من 1 إلى 8 لسنة 2019",
     BASE + "المذكرات الإيضاحية للقوانين من 1 إلى 8 لسنة 2019.pdf"),
    ("قانون رقم 1 لسنة 2019 اتفاق بين الكويت والولايات المتحدة",
     BASE + "قانون رقم 1 سنة2019 اتفاق بين حكمومة دولة الكويت و حكومة الولايات المتحدة الأمريكية.pdf"),
    ("قانون رقم 2 لسنة 2019 اتفاقية إنشاء مركز الاعتماد الخليجي",
     BASE + "قانون رقم 2 سنة2019 لإتفاقية إنشاء مركز الاعتماد الخليجي.pdf"),
    ("قانون رقم 9 لسنة 2019 بشأن تنظيم تبادل المعلومات الائتمانية",
     BASE + "قانون رقم 9 سنة2019 بشأن تنظيم تبادل المعلومات الائتمانية.pdf"),
    ("قانون رقم 10 لسنة 2019 تعديل بعض أحكام قانون التأمينات الاجتماعية",
     BASE + "قانون رقم 10 سنة2019  بتعديل بعض أحكام قانون التأمينات الاجتماعية.pdf"),

    # 2020
    ("قرار وزاري رقم 196 لسنة 2020 قواعد مصفوفة المخالفات للمؤسسات المالية",
     BASE + "Law196-2020.pdf"),
    ("قانون رقم 9 لسنة 2020 تعديل قانون المرافعات المدنية والتجارية",
     BASE + "قانون رقم 9 لسنة 2020 بتعديل بعض أحكام مرسوم بالقانون رقم 38 لسنة 1980 بإصدار قانون المرافعات المدنية و التجارية.pdf"),
    ("قانون رقم 10 لسنة 2020 بشأن التوثيق",
     BASE + "قانون رقم 10 لسنة 2020 بشأن التوثيق.pdf"),

    # 2021
    ("قرار رقم 38 لسنة 2021 قواعد مكافحة غسل الأموال في مجال التأمين",
     BASE + "Law38-2021.pdf"),

    # 2022
    ("قرار وزاري رقم 22 لسنة 2022 في شأن العمالة المنزلية",
     BASE + "Law22-2022.pdf"),

    # 2023
    ("قرار رقم 57 لسنة 2023 قواعد مكافحة غسل الأموال في التأمين",
     BASE + "Law57-2023.pdf"),
    ("قرار وزاري رقم 141 لسنة 2023 اللائحة التنفيذية لمكافحة الإرهاب",
     BASE + "Law141-2023.pdf"),

    # 2024
    ("قرار رقم 16 لسنة 2024 تعديل أحكام مكافحة غسل الأموال",
     BASE + "Law16-2024.pdf"),
    ("قانون رقم 112 لسنة 2024 اتفاقية تسليم المجرمين مع روسيا",
     BASE + "Law112-2024.pdf"),
    ("قانون رقم 113 لسنة 2024 نقل المحكوم عليهم مع روسيا",
     BASE + "Law113-2024.pdf"),
    ("قرار وزاري رقم 1722 لسنة 2024 تنظيم الوكالات العقارية",
     BASE + "Circular1722-2024.pdf"),
    ("مرسوم بقانون 114 لسنة 2024 قانون إقامة الأجانب",
     BASE + "Law114-2024.pdf"),

    # 2025
    ("قرار وزاري رقم 125 لسنة 2025 بشأن الإعلان الإلكتروني",
     BASE + "Law125-2025.pdf"),
    ("قرار وزاري رقم 194 لسنة 2025 إثبات الدفع في التحويل المصرفي",
     BASE + "194-2025.pdf"),
    ("مرسوم بقانون 9 لسنة 2025 إلغاء المادة 153 من قانون الجزاء",
     BASE + "Law9-2025.pdf"),
    ("قانون 11 لسنة 2025 تعديل قانون الأحوال الشخصية الجعفرية",
     BASE + "مرسوم بقانون 11 لسنة 2025.pdf"),
    ("قانون رقم 59 لسنة 2025 تعديل قانون المرافعات المدنية والتجارية",
     BASE + "Law59-2025.pdf"),
    ("قانون 58 لسنة 2025 تعديل قانون الإفلاس",
     BASE + "Law58-2025.pdf"),
    ("مرسوم بقانون رقم 65 لسنة 2025 تعديل قانون الجزاء",
     BASE + "Law65-2025.pdf"),
    ("مرسوم بقانون رقم 72 لسنة 2025 في شأن الدعاوي قليلة القيمة",
     BASE + "Law72-2025.pdf"),
    ("قانون رقم 69 لسنة 2025 الهيئة العامة لمكافحة الفساد",
     BASE + "Law69-2025.pdf"),
    ("قانون رقم 70 لسنة 2025 إلغاء المادتين 159 و 182 من قانون الجزاء",
     BASE + "Law70-2025.pdf"),

    # مجموعة التشريعات — compiled collections (high value)
    ("مجموعة التشريعات الكويتية — القوانين الخاصة ببعض الجهات والفئات",
     BASE + "مجموعة التشريعات الكويتية.pdf"),
    ("قانون الجزاء والقوانين المكملة",
     BASE + "قانون الجزاء والقوانين المكملة.pdf"),
    ("القوانين المنظمة للجهاز الإداري للدولة",
     BASE + "القوانين المنظمة​ للجهاز الإداري للدولة.pdf"),
    ("القضاء والفتوى والتشريع — التسجيل العقاري والتوثيق",
     BASE + "القضاء والفتوى والتشريع-التسجيل العقاري.pdf"),
]

# ── Helpers ───────────────────────────────────────────────────────────────────

OUTPUT_DIR   = Path("output")
PDF_DIR      = OUTPUT_DIR / "pdfs"
CORPUS_JSONL = OUTPUT_DIR / "corpus.jsonl"
CORPUS_FULL  = OUTPUT_DIR / "corpus_full.json"
FAILED_LOG   = OUTPUT_DIR / "failed.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ar-KW,ar;q=0.9,en;q=0.8",
    "Referer": "https://www.moj.gov.kw/",
}
DELAY   = 1.2
TIMEOUT = 30


def clean_arabic_text(text):
    if not text:
        return ""
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return '\n'.join(l.strip() for l in text.splitlines()).strip()


def extract_year(name):
    m = re.search(r'(?:لسنة|لسنه|سنة|سنه)\s*(\d{4})', name)
    if m: return m.group(1)
    m = re.search(r'\b(19\d{2}|20\d{2})\b', name)
    return m.group(1) if m else None


def extract_law_number(name):
    m = re.search(r'رقم\s+(\d+)', name)
    return m.group(1) if m else None


def classify_doc_type(name):
    if 'دستور' in name: return 'constitution'
    if 'قرار وزاري' in name: return 'ministerial_decree'
    if 'مرسوم' in name: return 'amiri_decree'
    if 'اتفاقية' in name or 'اتفاق' in name: return 'international_agreement'
    if 'لائحة' in name: return 'regulation'
    if 'تعميم' in name: return 'circular'
    if 'مجموعة' in name: return 'compiled_collection'
    if 'قانون' in name: return 'law'
    return 'other'


def pdf_filename(url):
    return re.sub(r'[<>:"/\\|?*\u200b]', '_', unquote(url.split('/')[-1]))


def download_pdf(name, url, session):
    local = PDF_DIR / pdf_filename(url)
    if local.exists() and local.stat().st_size > 500:
        return local
    try:
        r = session.get(url, timeout=TIMEOUT, verify=False, stream=True)
        r.raise_for_status()
        with open(local, 'wb') as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
        return local
    except Exception as e:
        print(f"  [!] {e}")
        return None


def extract_text(path):
    # Try pdfplumber first
    try:
        parts = []
        with pdfplumber.open(path) as pdf:
            for pg in pdf.pages:
                t = pg.extract_text()
                if t: parts.append(t)
        text = '\n\n'.join(parts)
        if len(text.strip()) > 100:
            return text, 'pdfplumber'
    except Exception:
        pass
    # PyMuPDF fallback
    try:
        doc = fitz.open(str(path))
        parts = [pg.get_text() for pg in doc]
        doc.close()
        text = '\n\n'.join(parts)
        if len(text.strip()) > 100:
            return text, 'pymupdf'
    except Exception:
        pass
    return "", 'failed'

# ── Main ──────────────────────────────────────────────────────────────────────

def build_corpus(limit=None, skip_download=False):
    OUTPUT_DIR.mkdir(exist_ok=True)
    PDF_DIR.mkdir(exist_ok=True)

    laws = LAWS[:limit] if limit else LAWS
    print(f"[*] Processing {len(laws)} Kuwaiti legal documents\n")

    session = requests.Session()
    session.headers.update(HEADERS)

    corpus_meta, failed = [], []

    with open(CORPUS_JSONL, 'w', encoding='utf-8') as jsonl:
        for i, (name, url) in enumerate(laws, 1):
            print(f"[{i:3d}/{len(laws)}] {name[:65]}")

            # Download
            if skip_download:
                path = PDF_DIR / pdf_filename(url)
                if not path.exists():
                    failed.append({'name': name, 'url': url, 'error': 'not_found_locally'})
                    continue
            else:
                path = download_pdf(name, url, session)
                if not path:
                    failed.append({'name': name, 'url': url, 'error': 'download_failed'})
                    continue
                time.sleep(DELAY)

            # Extract text
            raw, method = extract_text(path)
            if not raw.strip():
                print(f"         [!] Extraction failed — likely scanned image PDF")
                failed.append({'name': name, 'url': url, 'error': 'extraction_failed', 'pdf': str(path)})
                continue

            text = clean_arabic_text(raw)
            words = len(text.split())
            print(f"         [+] {words:,} words  ({method})")

            record = {
                'id':           f"kw_moj_{i:04d}",
                'source':       'Kuwait Ministry of Justice',
                'name':         name,
                'url':          url,
                'year':         extract_year(name),
                'law_number':   extract_law_number(name),
                'doc_type':     classify_doc_type(name),
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

            corpus_meta.append({k: v for k, v in record.items() if k != 'text'})

    # Summary
    by_type = {}
    by_year = {}
    for d in corpus_meta:
        by_type[d['doc_type']] = by_type.get(d['doc_type'], 0) + 1
        yr = d['year'] or 'unknown'
        by_year[yr] = by_year.get(yr, 0) + 1

    total_words = sum(d['word_count'] for d in corpus_meta)

    summary = {
        'scrape_date':     datetime.now().isoformat(),
        'source_url':      'https://www.moj.gov.kw/AR/Pages/MojLaws.aspx',
        'total_documents': len(corpus_meta),
        'failed':          len(failed),
        'total_words':     total_words,
        'by_doc_type':     by_type,
        'by_year':         dict(sorted(by_year.items())),
        'documents':       corpus_meta,
    }

    with open(CORPUS_FULL, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    with open(FAILED_LOG, 'w', encoding='utf-8') as f:
        json.dump(failed, f, ensure_ascii=False, indent=2)

    print("\n" + "="*65)
    print("  CORPUS BUILD COMPLETE")
    print("="*65)
    print(f"  Succeeded : {len(corpus_meta)}   |   Failed: {len(failed)}")
    print(f"  Total words: {total_words:,}")
    print(f"\n  Output files:")
    print(f"    {CORPUS_JSONL}       ← use this for training")
    print(f"    {CORPUS_FULL}   ← metadata summary")
    print(f"    {FAILED_LOG}         ← review failures")
    print(f"    {PDF_DIR}/            ← {len(corpus_meta)} PDFs")
    print(f"\n  Document types:")
    for dt, n in sorted(by_type.items(), key=lambda x: -x[1]):
        print(f"    {dt:<28} {n}")
    print("="*65)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description='Kuwait MOJ Legal Corpus Scraper')
    ap.add_argument('--limit',         type=int, default=None)
    ap.add_argument('--skip-download', action='store_true')
    args = ap.parse_args()
    build_corpus(limit=args.limit, skip_download=args.skip_download)