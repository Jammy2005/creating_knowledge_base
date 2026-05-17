"""
OCR re-extraction for 14 docs with Arabic presentation-form encoding issues.
Finds their PDFs, runs Tesseract, replaces records in corpus.jsonl in-place.
"""
import json, os, shutil
from pathlib import Path
from pdf2image import convert_from_path
import pytesseract

TARGET_IDS = {
    "kw_cbk_0089", "kw_cbk_0097", "kw_cbk_0098", "kw_cbk_0101",
    "kw_cma_0002", "kw_cbk_0208", "kw_cbk_0210", "kw_cbk_0211",
    "kw_cbk_0212", "kw_cbk_0215", "kw_cbk_0216", "kw_cbk_0218",
    "kw_cbk_0248", "kw_cbk_0249"
}

PDF_DIRS = ["output/pdfs_cbk", "output/pdfs_cma", "output/pdfs"]
CORPUS   = "output/corpus.jsonl"
DPI      = 200

def find_pdf(doc_id):
    for d in PDF_DIRS:
        p = Path(d) / f"{doc_id}.pdf"
        if p.exists():
            return p
    return None

def ocr_pdf(pdf_path):
    pages = convert_from_path(str(pdf_path), dpi=DPI)
    return "\n".join(
        pytesseract.image_to_string(page, lang="ara") for page in pages
    ).strip()

shutil.copy(CORPUS, CORPUS.replace(".jsonl", "_pre_ocr14.jsonl"))

with open(CORPUS) as f:
    docs = [json.loads(line) for line in f if line.strip()]

fixed, missing = [], []
for doc in docs:
    if doc["id"] not in TARGET_IDS:
        continue
    pdf = find_pdf(doc["id"])
    if not pdf:
        missing.append(doc["id"])
        continue
    print(f"OCR-ing {doc['id']} ({pdf}) ...", flush=True)
    text = ocr_pdf(pdf)
    words = text.split()
    doc["text"]   = text
    doc["method"] = "ocr_tesseract"
    doc["word_count"] = len(words)
    doc["char_count"] = len(text)
    doc["rtl_fixed"]  = False
    fixed.append(doc["id"])
    print(f"  → {len(words)} words extracted")

with open(CORPUS, "w") as f:
    for doc in docs:
        f.write(json.dumps(doc, ensure_ascii=False) + "\n")

print(f"\nDone. Fixed: {len(fixed)}, Missing PDFs: {len(missing)}")
if missing:
    print("No PDF found for:", missing)
