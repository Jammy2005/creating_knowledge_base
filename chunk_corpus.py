"""
Chunk corpus.jsonl into embedding-ready passages
=================================================
Reads output/corpus.jsonl and produces output/chunks.jsonl with one chunk per line.

Strategy:
  1. Structural: split on Arabic article markers (مادة / المادة) at line starts
  2. Fallback A: recursively split oversized articles by paragraph → sentence → token window
  3. Fallback B: same recursive split applied to whole-doc when no article markers exist
  4. Drop chunks < 20 tokens (orphan headers)

Token budget: 480 (leaves headroom under e5-large's 512 limit for "passage: " prefix).

Usage:
  python3 chunk_corpus.py                                 # full run -> output/chunks.jsonl
  python3 chunk_corpus.py --limit 3                       # process first 3 docs
  python3 chunk_corpus.py --ids kw_moj_0005,kw_cbk_0096   # only specific docs
  python3 chunk_corpus.py --output output/chunks_test.jsonl
  python3 chunk_corpus.py --dry-run                       # don't write, just print stats
"""

import re, json, argparse, shutil, sys
from pathlib import Path
from datetime import datetime
from collections import Counter

from transformers import AutoTokenizer

# ── Config ────────────────────────────────────────────────────────────────────

OUTPUT_DIR     = Path("output")
CORPUS_JSONL   = OUTPUT_DIR / "corpus.jsonl"
DEFAULT_OUTPUT = OUTPUT_DIR / "chunks.jsonl"
REPORT_FILE    = OUTPUT_DIR / "chunking_report.json"

TOKENIZER_MODEL = "intfloat/multilingual-e5-large"
MAX_TOKENS      = 480          # under 512 to leave room for "passage: " prefix at embed time
OVERLAP_TOKENS  = 50           # used by token-window fallback
MIN_TOKENS      = 20           # drop fragments smaller than this

# Bidirectional marks that pollute OCR'd Arabic
BIDI_MARKS = re.compile(r'[‎‏‪-‮⁦-⁩]')

# ── Article marker detection ──────────────────────────────────────────────────
#
# Matches lines that begin a new article:
#   مادة (1)         المادة (٢)        مادة 1:
#   مادة أولى        المادة الأولى     مادة رقم 5
# Marker must be preceded by newline (or start-of-string) and optional whitespace,
# optionally wrapped in a leading '(' from forms like "(مادة 5)".

ARABIC_ORDINALS  = r'(?:أولى|ثانية|ثالثة|رابعة|خامسة|سادسة|سابعة|ثامنة|تاسعة|عاشرة|حادية|واحدة)'
DEFINITE_ORDINALS = r'(?:الأولى|الثانية|الثالثة|الرابعة|الخامسة|السادسة|السابعة|الثامنة|التاسعة|العاشرة|الحادية)'

# Permissive line-start marker: مادة or المادة at start of a line, with some kind
# of number-like or ordinal token within the next 20 chars (lookahead). The OCR
# output frequently mangles the surrounding parentheses/digits with bidi marks
# and mixed scripts, so we use a loose lookahead and extract the number separately.
ARTICLE_RE = re.compile(
    r'(?:^|\n)\s*\(?\s*(?:ال)?مادة\b'
    r'(?='
        r'[^\n]{0,20}[\d٠-٩۰-۹]'                # any number-like char nearby, OR
        rf'|[^\n]{{0,20}}(?:{DEFINITE_ORDINALS}|{ARABIC_ORDINALS})'
    r')',
    re.MULTILINE
)

# Looser number-extractor used for metadata only. Scans the first ~60 chars of an
# article (the header line) and pulls out the first numeric/ordinal token.
ARTICLE_NUM_EXTRACT = re.compile(
    rf'(?:({DEFINITE_ORDINALS}|{ARABIC_ORDINALS})'
    r'|([\d٠-٩۰-۹]+(?:[/\-][\d٠-٩۰-۹]+)?))'
)

# ── Helpers ───────────────────────────────────────────────────────────────────

def normalize_text(text: str) -> str:
    """Strip bidirectional control marks (U+200E/U+200F/etc.) that pollute OCR output."""
    if not text:
        return ""
    return BIDI_MARKS.sub('', text)


def extract_article_number(header_text: str) -> str | None:
    """
    Pull an article number/ordinal out of the first ~60 chars of a chunk
    (i.e. the line containing the مادة marker). Skips digit sequences embedded
    in the word مادة itself. Returns None if nothing recognisable is found.
    """
    # ARTICLE_RE anchors on the preceding newline, so strip leading whitespace
    # before isolating the marker line.
    head = header_text.lstrip()[:80].split('\n', 1)[0]
    # Strip the leading "(مادة" / "المادة" so we don't extract digits from elsewhere
    head_after_marker = re.split(r'(?:ال)?مادة', head, maxsplit=1)
    candidate = head_after_marker[1] if len(head_after_marker) > 1 else head
    m = ARTICLE_NUM_EXTRACT.search(candidate)
    if not m:
        return None
    return (m.group(1) or m.group(2) or '').strip() or None


def split_structural(text: str) -> list[tuple[int, int, str | None]]:
    """
    Split text on article markers. Returns list of (start, end, article_number)
    where [start, end) is the slice of `text` for that article. Returns empty list
    if no markers found.
    """
    matches = list(ARTICLE_RE.finditer(text))
    if not matches:
        return []

    # Optional preamble before the first article is dropped (usually headers/title pages)
    spans = []
    for i, m in enumerate(matches):
        start = m.start()
        end   = matches[i+1].start() if i+1 < len(matches) else len(text)
        # Article number parsed from the first ~50 chars of the chunk (the header line)
        header = text[start:start+80]
        num    = extract_article_number(header)
        spans.append((start, end, num))
    return spans


# Arabic sentence enders (period, Arabic comma, semicolon, question mark, exclamation)
# plus newline as a soft boundary.
SENTENCE_SPLIT_RE = re.compile(r'(?<=[\.\?\!،؛])\s+|\n+')
PARAGRAPH_SPLIT_RE = re.compile(r'\n\s*\n+')


def split_by_paragraph(text: str) -> list[str]:
    parts = PARAGRAPH_SPLIT_RE.split(text)
    return [p.strip() for p in parts if p.strip()]


def split_by_sentence(text: str) -> list[str]:
    parts = SENTENCE_SPLIT_RE.split(text)
    return [p.strip() for p in parts if p.strip()]


# ── Tokenizer-aware chunking ──────────────────────────────────────────────────

class TokenChunker:
    """Wraps a HuggingFace tokenizer to do token-count-aware chunking."""

    def __init__(self, model_name: str = TOKENIZER_MODEL, max_tokens: int = MAX_TOKENS,
                 overlap_tokens: int = OVERLAP_TOKENS):
        print(f"[*] Loading tokenizer: {model_name}")
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.max_tokens = max_tokens
        self.overlap_tokens = overlap_tokens

    def count(self, text: str) -> int:
        return len(self.tokenizer(text, add_special_tokens=False, truncation=False)["input_ids"])

    def token_window_split(self, text: str) -> list[str]:
        """Last-resort splitter: token-window with overlap. Decodes back to text."""
        ids = self.tokenizer(text, add_special_tokens=False, truncation=False)["input_ids"]
        if len(ids) <= self.max_tokens:
            return [text]
        chunks = []
        step = self.max_tokens - self.overlap_tokens
        for start in range(0, len(ids), step):
            window = ids[start:start + self.max_tokens]
            if not window:
                break
            chunks.append(self.tokenizer.decode(window, skip_special_tokens=True).strip())
            if start + self.max_tokens >= len(ids):
                break
        return chunks

    def recursive_split(self, text: str) -> list[tuple[str, str]]:
        """
        Recursive split for oversized text: paragraph -> sentence -> token-window.
        Returns list of (chunk_text, method) tuples, where method describes the
        final granularity that produced this chunk.
        """
        if self.count(text) <= self.max_tokens:
            return [(text, "fallback_paragraph")]

        out: list[tuple[str, str]] = []

        # 1) Try paragraphs: greedily pack paragraphs until budget hit
        paragraphs = split_by_paragraph(text)
        if len(paragraphs) > 1:
            buffer, buf_tokens = [], 0
            for para in paragraphs:
                pt = self.count(para)
                if pt > self.max_tokens:
                    # Flush buffer first
                    if buffer:
                        out.append(("\n\n".join(buffer), "fallback_paragraph"))
                        buffer, buf_tokens = [], 0
                    # Oversized paragraph -> sentence split
                    out.extend(self._sentence_pack(para))
                elif buf_tokens + pt > self.max_tokens:
                    out.append(("\n\n".join(buffer), "fallback_paragraph"))
                    buffer, buf_tokens = [para], pt
                else:
                    buffer.append(para)
                    buf_tokens += pt
            if buffer:
                out.append(("\n\n".join(buffer), "fallback_paragraph"))
            return out

        # 2) Single paragraph but oversized -> sentence split
        return self._sentence_pack(text)

    def _sentence_pack(self, text: str) -> list[tuple[str, str]]:
        """Pack sentences into chunks <= max_tokens; if a sentence alone is too big, token-window it."""
        sentences = split_by_sentence(text)
        if len(sentences) <= 1:
            # Can't sentence-split; last resort is token windowing
            return [(c, "fallback_token") for c in self.token_window_split(text)]

        out: list[tuple[str, str]] = []
        buffer, buf_tokens = [], 0
        for sent in sentences:
            st = self.count(sent)
            if st > self.max_tokens:
                if buffer:
                    out.append((" ".join(buffer), "fallback_paragraph"))
                    buffer, buf_tokens = [], 0
                for c in self.token_window_split(sent):
                    out.append((c, "fallback_token"))
            elif buf_tokens + st > self.max_tokens:
                out.append((" ".join(buffer), "fallback_paragraph"))
                buffer, buf_tokens = [sent], st
            else:
                buffer.append(sent)
                buf_tokens += st
        if buffer:
            out.append((" ".join(buffer), "fallback_paragraph"))
        return out


# ── Per-doc chunking ──────────────────────────────────────────────────────────

def chunk_doc(doc: dict, chunker: TokenChunker) -> list[dict]:
    """Apply the chunking pipeline to one document. Returns list of chunk dicts."""
    raw_text  = doc.get("text", "")
    text      = normalize_text(raw_text)
    if not text.strip():
        return []

    spans   = split_structural(text)
    chunks  : list[dict] = []
    chunk_i = 0

    def make_chunk(chunk_text: str, char_start: int, char_end: int,
                   article_number: str | None, method: str) -> dict:
        nonlocal chunk_i
        tc = chunker.count(chunk_text)
        cid = f"{doc['id']}_c{chunk_i:04d}"
        chunk_i += 1
        return {
            "chunk_id":       cid,
            "doc_id":         doc["id"],
            "source":         doc.get("source"),
            "name":           doc.get("name"),
            "year":           doc.get("year"),
            "doc_type":       doc.get("doc_type"),
            "language":       doc.get("language", "ar"),
            "jurisdiction":   doc.get("jurisdiction", "KW"),
            "url":            doc.get("url"),
            "text":           chunk_text,
            "char_start":     char_start,
            "char_end":       char_end,
            "token_count":    tc,
            "article_number": article_number,
            "chunk_method":   method,
        }

    if spans:
        # Structural path
        for start, end, art_num in spans:
            article_text = text[start:end].strip()
            if not article_text:
                continue
            tc = chunker.count(article_text)
            if tc <= MAX_TOKENS:
                chunks.append(make_chunk(article_text, start, end, art_num, "structural"))
            else:
                # Oversized article -> recursive split, carry article_number through
                sub_offset = 0
                for sub_text, sub_method in chunker.recursive_split(article_text):
                    sub_text = sub_text.strip()
                    if not sub_text:
                        continue
                    # We can't reliably re-locate sub-chunk offsets in normalized text
                    # without a full alignment pass; record the article span and rely on
                    # the text itself as the source of truth.
                    chunks.append(make_chunk(
                        sub_text,
                        start + sub_offset,
                        start + sub_offset + len(sub_text),
                        art_num,
                        sub_method,
                    ))
                    sub_offset += len(sub_text)
    else:
        # No article markers: fallback B
        for sub_text, sub_method in chunker.recursive_split(text):
            sub_text = sub_text.strip()
            if not sub_text:
                continue
            chunks.append(make_chunk(sub_text, 0, len(sub_text), None, sub_method))

    # Drop fragments below MIN_TOKENS (orphan headers, page numbers, etc.)
    chunks = [c for c in chunks if c["token_count"] >= MIN_TOKENS]
    # Re-number sequentially after dropping (chunk_ids must be contiguous per doc)
    for new_i, c in enumerate(chunks):
        c["chunk_id"] = f"{doc['id']}_c{new_i:04d}"

    return chunks


# ── Main ──────────────────────────────────────────────────────────────────────

def run(limit=None, ids=None, output_path=DEFAULT_OUTPUT, dry_run=False):
    print(f"\n{'='*70}")
    print(f"  KUWAIT LEGAL KB — STRUCTURAL CHUNKER")
    print(f"{'='*70}\n")

    print("[*] Loading corpus...")
    docs = []
    with open(CORPUS_JSONL, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                docs.append(json.loads(line))
    print(f"[*] Loaded {len(docs)} docs")

    if ids:
        wanted = set(ids)
        docs = [d for d in docs if d["id"] in wanted]
        print(f"[*] Filtered to {len(docs)} docs by --ids")
    if limit:
        docs = docs[:limit]
        print(f"[*] Limited to first {len(docs)} docs")

    chunker = TokenChunker()

    all_chunks: list[dict] = []
    per_doc_counts: list[tuple[str, int, int]] = []  # (doc_id, doc_words, n_chunks)

    for i, d in enumerate(docs, 1):
        wc = d.get("word_count", 0)
        try:
            chunks = chunk_doc(d, chunker)
        except Exception as e:
            print(f"[!] ERROR on {d['id']}: {e}")
            continue
        all_chunks.extend(chunks)
        per_doc_counts.append((d["id"], wc, len(chunks)))
        if i % 20 == 0 or i == len(docs) or wc > 50_000:
            print(f"  [{i:3d}/{len(docs)}] {d['id']:<18} {wc:>8,}w -> {len(chunks):>5} chunks")

    # ── Stats ─────────────────────────────────────────────────────────────────
    print(f"\n{'─'*70}")
    print(f"  CHUNKING STATS")
    print(f"{'─'*70}")

    methods   = Counter(c["chunk_method"] for c in all_chunks)
    sources   = Counter(c["source"] for c in all_chunks)
    n_chunks  = len(all_chunks)
    with_num  = sum(1 for c in all_chunks if c["article_number"])

    print(f"  Total chunks: {n_chunks:,}")
    print(f"  Source breakdown: {dict(sources)}")
    print(f"  Method breakdown: {dict(methods)}")
    print(f"  Chunks with parsed article_number: {with_num:,} / {n_chunks:,} ({with_num/n_chunks:.0%})")

    # Token histogram
    buckets = Counter()
    over = 0
    for c in all_chunks:
        tc = c["token_count"]
        if tc > MAX_TOKENS: over += 1
        if   tc < 50:                 buckets["<50"] += 1
        elif tc < 200:                buckets["50-200"] += 1
        elif tc < 400:                buckets["200-400"] += 1
        elif tc <= MAX_TOKENS:        buckets[f"400-{MAX_TOKENS}"] += 1
        else:                         buckets[f">{MAX_TOKENS}"] += 1
    print(f"  Token-count buckets:")
    for k in ["<50", "50-200", "200-400", f"400-{MAX_TOKENS}", f">{MAX_TOKENS}"]:
        print(f"    {k:>10}: {buckets[k]:>6,}")
    if over:
        print(f"  [!] {over} chunks exceed MAX_TOKENS={MAX_TOKENS} — review needed")
    else:
        print(f"  [+] All chunks within {MAX_TOKENS}-token budget")

    # Per-doc summary: docs that produced zero chunks
    zero_chunk_docs = [(did, wc) for did, wc, n in per_doc_counts if n == 0]
    if zero_chunk_docs:
        print(f"\n  [!] {len(zero_chunk_docs)} docs produced zero chunks:")
        for did, wc in zero_chunk_docs[:10]:
            print(f"      {did} ({wc:,}w)")

    # ── Write output ──────────────────────────────────────────────────────────
    if dry_run:
        print(f"\n[*] DRY RUN — not writing output.")
    else:
        output_path = Path(output_path)
        if output_path.exists():
            backup = output_path.with_name(f"{output_path.stem}_pre_rechunk{output_path.suffix}")
            print(f"\n[*] Existing {output_path.name} -> backing up to {backup.name}")
            shutil.copy(output_path, backup)
        print(f"[*] Writing {n_chunks:,} chunks to {output_path}")
        with open(output_path, "w", encoding="utf-8") as f:
            for c in all_chunks:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")

        # Report
        report = {
            "timestamp":         datetime.now().isoformat(),
            "tokenizer":         TOKENIZER_MODEL,
            "max_tokens":        MAX_TOKENS,
            "min_tokens":        MIN_TOKENS,
            "n_docs_processed":  len(docs),
            "n_chunks":          n_chunks,
            "method_breakdown":  dict(methods),
            "source_breakdown":  dict(sources),
            "token_buckets":     dict(buckets),
            "chunks_over_limit": over,
            "zero_chunk_docs":   [did for did, wc in zero_chunk_docs],
        }
        with open(REPORT_FILE, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"[*] Report saved to: {REPORT_FILE}")

    print(f"\n{'='*70}\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Chunk corpus.jsonl into embedding-ready passages")
    ap.add_argument("--limit",   type=int, default=None, help="Process only first N docs")
    ap.add_argument("--ids",     type=str, default=None, help="Comma-separated doc IDs to process")
    ap.add_argument("--output",  type=str, default=str(DEFAULT_OUTPUT), help="Output path")
    ap.add_argument("--dry-run", action="store_true", help="Run pipeline + print stats without writing")
    args = ap.parse_args()

    id_list = [x.strip() for x in args.ids.split(",")] if args.ids else None
    run(limit=args.limit, ids=id_list, output_path=args.output, dry_run=args.dry_run)
