"""
Corpus Deep Quality Audit
==========================
Thoroughly analyses output/corpus.jsonl and produces:
  1. A per-doc scorecard with 6 quality signals
  2. Readable text samples from flagged docs
  3. Duplicate detection
  4. A final summary with pass/warn/fail counts

Quality signals checked per doc:
  - arabic_ratio      : % of non-whitespace chars that are Arabic
  - garbled_ratio     : % of words with corrupted character patterns
  - rtl_score         : likelihood text is still RTL-reversed
  - repetition_score  : % of sentences that are near-duplicates (OCR loops)
  - lexical_diversity : unique words / total words (low = repetitive/garbled)
  - coherence_sample  : 3 random chunks printed for human review

Usage:
  python3 corpus_audit.py                  # full audit
  python3 corpus_audit.py --samples-only   # just print text samples
  python3 corpus_audit.py --flag-only      # only show flagged docs
"""

import json, re, random, argparse
from pathlib import Path
from collections import Counter

CORPUS = Path("output/corpus.jsonl")
REPORT = Path("output/corpus_audit_report.json")

random.seed(42)

# ── Thresholds ────────────────────────────────────────────────────────────────
THRESHOLDS = {
    'arabic_ratio':      {'warn': 0.70, 'fail': 0.50},
    'garbled_ratio':     {'warn': 0.05, 'fail': 0.10},
    'rtl_score':         {'warn': 0.40, 'fail': 0.65},
    'repetition_score':  {'warn': 0.15, 'fail': 0.30},
    'lexical_diversity': {'warn': 0.30, 'fail': 0.15},  # lower = worse
}

# ── Metrics ───────────────────────────────────────────────────────────────────

def arabic_ratio(text):
    if not text: return 0
    arabic = len(re.findall(r'[\u0600-\u06FF]', text))
    total  = len(re.findall(r'\S', text))
    return arabic / total if total > 0 else 0


def garbled_ratio(text):
    words = text.split()
    if not words: return 0
    garbled = sum(1 for w in words if len(w) >= 2 and (
        re.search(r'(.)\1{3,}', w) or
        (re.search(r'[\u0600-\u06FF]', w) and re.search(r'[a-zA-Z]', w))
    ))
    return garbled / len(words)


def rtl_score(text):
    """Score likelihood that text is still RTL-reversed."""
    words = text.split()[:200]
    if not words: return 0
    reversed_markers = {'ىلع','نأشب','رادصإب','ةدام','نوناقلا','يزكرملا',
                        'ةئيهلا','كونبلا','ةكرشلا','نيناوقلا','ماكحلأا',
                        'تاميلعتلا','تارارقلا','ريدملا','ةرادإ','صاصتخا'}
    correct_markers  = {'على','بشأن','بإصدار','مادة','القانون','المركزي',
                        'الهيئة','البنوك','الشركة','القوانين','الأحكام',
                        'التعليمات','القرارات','المدير','إدارة','اختصاص'}
    rev  = sum(1 for w in words if w in reversed_markers)
    cor  = sum(1 for w in words if w in correct_markers)
    total = rev + cor
    return rev / total if total > 0 else 0


def repetition_score(text):
    """Detect repeated sentences — sign of OCR looping or copy-paste errors."""
    sentences = [s.strip() for s in re.split(r'[.،؛\n]', text) if len(s.strip()) > 20]
    if len(sentences) < 5: return 0
    counts = Counter(sentences)
    repeated = sum(c - 1 for c in counts.values() if c > 1)
    return repeated / len(sentences)


def lexical_diversity(text):
    """Unique words / total words. Low score = repetitive or garbled."""
    words = [w for w in text.split() if re.search(r'[\u0600-\u06FF]', w)]
    if len(words) < 10: return 1.0
    return len(set(words)) / len(words)


def random_samples(text, n=3, chunk_words=80):
    """Extract n random chunks of ~chunk_words words from the text."""
    words = text.split()
    if len(words) < chunk_words:
        return [' '.join(words)]
    max_start = len(words) - chunk_words
    starts = sorted(random.sample(range(max_start), min(n, max_start)))
    return [' '.join(words[s:s+chunk_words]) for s in starts]


def score_doc(d):
    text = d.get('text', '')
    ar   = arabic_ratio(text)
    gr   = garbled_ratio(text)
    rtl  = rtl_score(text)
    rep  = repetition_score(text)
    lex  = lexical_diversity(text)

    signals = {
        'arabic_ratio':     round(ar,  3),
        'garbled_ratio':    round(gr,  3),
        'rtl_score':        round(rtl, 3),
        'repetition_score': round(rep, 3),
        'lexical_diversity':round(lex, 3),
    }

    flags = []
    for metric, val in signals.items():
        t = THRESHOLDS[metric]
        if metric == 'lexical_diversity':
            # Lower is worse for diversity
            if val < t['fail']:   flags.append(f"FAIL:{metric}={val:.2f}")
            elif val < t['warn']: flags.append(f"WARN:{metric}={val:.2f}")
        else:
            # Higher is worse for all other metrics
            if metric == 'arabic_ratio':
                if val < t['fail']:   flags.append(f"FAIL:{metric}={val:.2f}")
                elif val < t['warn']: flags.append(f"WARN:{metric}={val:.2f}")
            else:
                if val > t['fail']:   flags.append(f"FAIL:{metric}={val:.2f}")
                elif val > t['warn']: flags.append(f"WARN:{metric}={val:.2f}")

    overall = 'FAIL' if any(f.startswith('FAIL') for f in flags) else \
              'WARN' if flags else 'PASS'

    return signals, flags, overall


def check_duplicates(docs):
    """Find docs with identical or near-identical text (first 500 chars)."""
    seen = {}
    dupes = []
    for d in docs:
        key = ' '.join(d.get('text','')[:500].split())
        if key in seen:
            dupes.append((seen[key], d['id'], d.get('name','')[:50]))
        else:
            seen[key] = d['id']
    return dupes


# ── Main ──────────────────────────────────────────────────────────────────────

def run(samples_only=False, flag_only=False):
    print(f"\n{'='*70}")
    print(f"  KUWAIT LEGAL AI — CORPUS DEEP QUALITY AUDIT")
    print(f"{'='*70}\n")

    docs = [json.loads(l) for l in open(CORPUS, encoding='utf-8')]
    print(f"  Loaded {len(docs)} documents\n")

    # ── Score all docs ─────────────────────────────────────────────────────
    results = []
    counts  = {'PASS': 0, 'WARN': 0, 'FAIL': 0}

    for d in docs:
        signals, flags, overall = score_doc(d)
        counts[overall] += 1
        results.append({
            'id':      d['id'],
            'source':  d['source'],
            'method':  d.get('method','?'),
            'words':   d.get('word_count', 0),
            'name':    d.get('name','')[:60],
            'signals': signals,
            'flags':   flags,
            'overall': overall,
        })

    # ── Summary ────────────────────────────────────────────────────────────
    print(f"  OVERALL RESULTS")
    print(f"  {'─'*40}")
    print(f"  ✅ PASS : {counts['PASS']:>4} docs")
    print(f"  ⚠️  WARN : {counts['WARN']:>4} docs")
    print(f"  ❌ FAIL : {counts['FAIL']:>4} docs")
    print()

    # ── Duplicate check ────────────────────────────────────────────────────
    dupes = check_duplicates(docs)
    if dupes:
        print(f"  ⚠️  DUPLICATE CONTENT DETECTED: {len(dupes)} pairs")
        for id1, id2, name in dupes:
            print(f"     {id1} ↔ {id2}  ({name})")
    else:
        print(f"  ✅ No duplicates detected")
    print()

    # ── Per-doc scorecard ──────────────────────────────────────────────────
    flagged = [r for r in results if r['overall'] in ('WARN','FAIL')]

    if not samples_only:
        print(f"  {'─'*70}")
        print(f"  FLAGGED DOCS ({len(flagged)}) — WARN + FAIL")
        print(f"  {'─'*70}")
        print(f"  {'ID':<18} {'STATUS':<6} {'ar':>5} {'grb':>5} {'rtl':>5} {'rep':>5} {'lex':>5}  {'words':>7}  name")
        print(f"  {'─'*70}")

        for r in sorted(flagged, key=lambda x: (x['overall'] == 'PASS', x['overall'])):
            s = r['signals']
            print(f"  {r['id']:<18} {r['overall']:<6} "
                  f"{s['arabic_ratio']:>5.2f} "
                  f"{s['garbled_ratio']:>5.2f} "
                  f"{s['rtl_score']:>5.2f} "
                  f"{s['repetition_score']:>5.2f} "
                  f"{s['lexical_diversity']:>5.2f}  "
                  f"{r['words']:>7,}  {r['name'][:40]}")
            if r['flags']:
                print(f"    ↳ {' | '.join(r['flags'])}")

        print()
        print(f"  COLUMNS: ar=arabic_ratio  grb=garbled  rtl=rtl_score  rep=repetition  lex=lexical_diversity")
        print()

    # ── Text samples from flagged docs ─────────────────────────────────────
    print(f"\n  {'='*70}")
    print(f"  TEXT SAMPLES — FLAGGED DOCS (3 random chunks each)")
    print(f"  {'='*70}")

    show = flagged if flag_only else flagged
    # Also show 3 random PASS docs as a sanity baseline
    pass_docs = [r for r in results if r['overall'] == 'PASS']
    baseline  = random.sample(pass_docs, min(3, len(pass_docs)))

    print(f"\n  ── BASELINE (3 random PASS docs — should look clean) ──────────")
    doc_map = {d['id']: d for d in docs}
    for r in baseline:
        d = doc_map[r['id']]
        chunks = random_samples(d['text'], n=2, chunk_words=60)
        print(f"\n  [{r['id']}] {r['name'][:55]}  ({r['words']:,}w)")
        for i, chunk in enumerate(chunks, 1):
            print(f"  Sample {i}: {chunk[:300]}")
            print()

    print(f"\n  ── FLAGGED DOCS — text samples ─────────────────────────────────")
    for r in flagged[:30]:  # cap at 30 to avoid overwhelming output
        d = doc_map[r['id']]
        chunks = random_samples(d['text'], n=3, chunk_words=60)
        status_icon = '❌' if r['overall'] == 'FAIL' else '⚠️ '
        print(f"\n  {status_icon} [{r['id']}] {r['name'][:55]}  ({r['words']:,}w)")
        print(f"     Flags: {' | '.join(r['flags']) if r['flags'] else 'none'}")
        for i, chunk in enumerate(chunks, 1):
            print(f"  Sample {i}: {chunk[:300]}")
            print()

    # ── Save full report ───────────────────────────────────────────────────
    report = {
        'summary': counts,
        'duplicates': [{'id1': d[0], 'id2': d[1], 'name': d[2]} for d in dupes],
        'docs': results,
    }
    with open(REPORT, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\n  {'='*70}")
    print(f"  Full report saved to: {REPORT}")
    print(f"  {'='*70}\n")


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--samples-only', action='store_true')
    ap.add_argument('--flag-only',    action='store_true')
    args = ap.parse_args()
    run(samples_only=args.samples_only, flag_only=args.flag_only)