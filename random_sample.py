import json, random, webbrowser, os

corpus_path = "output/corpus.jsonl"
n_samples = 8

with open(corpus_path) as f:
    docs = [json.loads(line) for line in f if line.strip()]

samples = random.sample(docs, min(n_samples, len(docs)))

cards = ""
for d in samples:
    snippet = d["text"][:600]
    cards += f"""
    <div class="card">
      <div class="meta">
        <span class="id">{d['id']}</span>
        <span class="source">{d.get('source', '')} — {d.get('doc_type', '')}</span>
        <span class="year">{d.get('year', '')}</span>
      </div>
      <div class="arabic">{snippet}…</div>
      <div class="wordcount">{d.get('word_count', '?')} words · {d.get('method', '?')}</div>
    </div>"""

html = f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="UTF-8">
  <title>Corpus RTL Sampler</title>
  <style>
    body {{ font-family: 'Segoe UI', Tahoma, Arial, sans-serif; background: #f5f5f0; padding: 2rem; direction: rtl; }}
    h1 {{ font-size: 1.3rem; color: #333; margin-bottom: 1.5rem; direction: ltr; }}
    .card {{ background: white; border: 1px solid #ddd; border-radius: 8px; padding: 1.2rem 1.5rem; margin-bottom: 1.2rem; }}
    .meta {{ display: flex; gap: 1rem; margin-bottom: 0.8rem; flex-wrap: wrap; direction: ltr; }}
    .id {{ font-family: monospace; font-size: 13px; background: #e8f0fe; color: #1a56db; padding: 2px 8px; border-radius: 4px; }}
    .source {{ font-size: 13px; color: #555; }}
    .year {{ font-size: 13px; color: #888; margin-right: auto; }}
    .arabic {{ font-size: 1.15rem; line-height: 2; color: #111; text-align: right; direction: rtl; unicode-bidi: embed; border-top: 1px solid #eee; padding-top: 0.8rem; }}
    .wordcount {{ font-size: 12px; color: #aaa; margin-top: 0.6rem; direction: ltr; text-align: left; }}
  </style>
</head>
<body>
  <h1>Corpus RTL Sampler — {len(samples)} random docs · {len(docs)} total</h1>
  {cards}
</body>
</html>"""

out = "corpus_rtl_sample.html"
with open(out, "w", encoding="utf-8") as f:
    f.write(html)

webbrowser.open("file://" + os.path.abspath(out))
print(f"Opened {out}")