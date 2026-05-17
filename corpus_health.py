"""
Corpus Health Diagnostic
Analyses output/corpus.jsonl and produces a full health report.
"""
import json, re, sys
from pathlib import Path
from collections import defaultdict

CORPUS = Path("output/corpus.jsonl")

def arabic_ratio(text):
    if not text: return 0
    arabic = len(re.findall(r'[\u0600-\u06FF]', text))
    total  = len(re.findall(r'\S', text))
    return arabic / total if total > 0 else 0

def junk_ratio(text):
    if not text: return 0
    # CID placeholders, garbled chars, excessive punctuation clusters
    junk = len(re.findall(r'(cid:\d+|\(cid:\d+\)|[^\u0000-\u007F\u0600-\u06FF\s]{4,})', text))
    words = len(text.split())
    return junk / words if words > 0 else 0

def rtl_reversal_score(text):
    """Rough check: reversed Arabic tends to have many single-char 'words'"""
    if not text: return 0
    words = text.split()
    if not words: return 0
    single_chars = sum(1 for w in words if len(w) == 1 and re.match(r'[\u0600-\u06FF]', w))
    return single_chars / len(words)

docs = []
errors = []
with open(CORPUS, encoding='utf-8') as f:
    for i, line in enumerate(f):
        try:
            docs.append(json.loads(line.strip()))
        except Exception as e:
            errors.append((i+1, str(e)))

print(f"\n{'='*65}")
print(f"  KUWAIT LEGAL AI — CORPUS HEALTH REPORT")
print(f"{'='*65}")
print(f"  Total documents:  {len(docs)}")
print(f"  Total words:      {sum(d.get('word_count',0) for d in docs):,}")
print(f"  Parse errors:     {len(errors)}")

# ── Per-source breakdown ───────────────────────────────────────────
sources = defaultdict(lambda: {'count':0,'words':0})
for d in docs:
    s = d.get('source','Unknown')
    sources[s]['count'] += 1
    sources[s]['words'] += d.get('word_count', 0)

print(f"\n{'─'*65}")
print(f"  SOURCE BREAKDOWN")
print(f"{'─'*65}")
for src, stats in sorted(sources.items(), key=lambda x: -x[1]['count']):
    print(f"  {src[:45]:<45} {stats['count']:>4} docs  {stats['words']:>10,} words")

# ── Extraction method ──────────────────────────────────────────────
methods = defaultdict(int)
for d in docs:
    methods[d.get('method','unknown')] += 1

print(f"\n{'─'*65}")
print(f"  EXTRACTION METHODS")
print(f"{'─'*65}")
for m, cnt in sorted(methods.items(), key=lambda x: -x[1]):
    print(f"  {m:<20} {cnt:>4} docs")

# ── Health classification ──────────────────────────────────────────
SEVERE   = []  # drop before training
PARTIAL  = []  # keep, flag
HEALTHY  = []

for d in docs:
    text = d.get('text','')
    wc   = d.get('word_count', 0)
    ar   = arabic_ratio(text)
    junk = junk_ratio(text)
    rtl  = rtl_reversal_score(text)

    d['_ar_ratio']   = ar
    d['_junk_ratio'] = junk
    d['_rtl_score']  = rtl

    if wc < 50:
        SEVERE.append(('too_short', d))
    elif ar < 0.05:
        SEVERE.append(('no_arabic', d))
    elif junk > 0.30 or ar < 0.15:
        SEVERE.append(('garbled', d))
    elif junk > 0.05 or ar < 0.40:
        PARTIAL.append(d)
    else:
        HEALTHY.append(d)

print(f"\n{'─'*65}")
print(f"  HEALTH CLASSIFICATION")
print(f"{'─'*65}")
print(f"  ✅ Healthy (ready for training):  {len(HEALTHY):>4} docs")
print(f"  ⚠️  Partial (keep, flag):          {len(PARTIAL):>4} docs")
print(f"  ❌ Severe (drop before training): {len(SEVERE):>4} docs")

# ── Severe details ─────────────────────────────────────────────────
if SEVERE:
    print(f"\n{'─'*65}")
    print(f"  SEVERE DOCUMENTS — DROP BEFORE TRAINING")
    print(f"{'─'*65}")
    for reason, d in SEVERE:
        print(f"  {d['id']:<18} | {reason:<12} | ar={d['_ar_ratio']:.0%} junk={d['_junk_ratio']:.0%} words={d.get('word_count',0):,}")
        print(f"    {d.get('name','')[:65]}")

# ── Partial details ────────────────────────────────────────────────
if PARTIAL:
    print(f"\n{'─'*65}")
    print(f"  PARTIAL DOCUMENTS — KEEP BUT REVIEW")
    print(f"{'─'*65}")
    for d in PARTIAL:
        print(f"  {d['id']:<18} | ar={d['_ar_ratio']:.0%} junk={d['_junk_ratio']:.0%} rtl={d['_rtl_score']:.0%} words={d.get('word_count',0):,}")
        print(f"    {d.get('name','')[:65]}")

# ── Word count distribution ────────────────────────────────────────
wcs = sorted([d.get('word_count',0) for d in docs])
buckets = [(0,100),(100,500),(500,2000),(2000,10000),(10000,50000),(50000,999999)]
print(f"\n{'─'*65}")
print(f"  WORD COUNT DISTRIBUTION")
print(f"{'─'*65}")
for lo, hi in buckets:
    cnt = sum(1 for w in wcs if lo <= w < hi)
    label = f"{lo:,}–{hi:,}" if hi < 999999 else f"{lo:,}+"
    bar = '█' * min(cnt, 40)
    print(f"  {label:<15} {cnt:>4} docs  {bar}")

# ── Very short docs ────────────────────────────────────────────────
short = [(d['id'], d.get('word_count',0), d.get('name','')[:50]) 
         for d in docs if d.get('word_count',0) < 200]
if short:
    print(f"\n{'─'*65}")
    print(f"  VERY SHORT DOCS (< 200 words) — review if meaningful")
    print(f"{'─'*65}")
    for id_, wc, name in sorted(short, key=lambda x: x[1]):
        print(f"  {id_:<18} {wc:>5} words  {name}")

print(f"\n{'='*65}\n")