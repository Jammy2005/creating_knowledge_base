import json, random, webbrowser, os

chunks_path = "output/chunks.jsonl"
n_samples = 12

with open(chunks_path) as f:
    chunks = [json.loads(line) for line in f if line.strip()]

samples = random.sample(chunks, min(n_samples, len(chunks)))

cards = ""
for c in samples:
    method_color = {
        "structural":         "#0f9d58",  # green
        "fallback_paragraph": "#f4b400",  # amber
        "fallback_token":     "#db4437",  # red
    }.get(c.get("chunk_method", ""), "#888")

    art = c.get("article_number")
    art_html = f'<span class="art">art {art}</span>' if art else ''

    cards += f"""
    <div class="card">
      <div class="meta">
        <span class="id">{c['chunk_id']}</span>
        <span class="source">{c.get('source','')} — {c.get('doc_type','')}</span>
        {art_html}
        <span class="method" style="background:{method_color}">{c.get('chunk_method','')}</span>
        <span class="tokens">{c.get('token_count','?')} tok</span>
      </div>
      <div class="arabic">{c['text']}</div>
      <div class="footer">doc: {c.get('doc_id','')} · year: {c.get('year','?')} · chars [{c.get('char_start','?')}–{c.get('char_end','?')}]</div>
    </div>"""

html = f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="UTF-8">
  <title>Chunks RTL Sampler</title>
  <style>
    body {{ font-family: 'Segoe UI', Tahoma, Arial, sans-serif; background: #f5f5f0; padding: 2rem; direction: rtl; }}
    h1 {{ font-size: 1.3rem; color: #333; margin-bottom: 1.5rem; direction: ltr; }}
    .card {{ background: white; border: 1px solid #ddd; border-radius: 8px; padding: 1.2rem 1.5rem; margin-bottom: 1.2rem; }}
    .meta {{ display: flex; gap: 0.6rem; margin-bottom: 0.8rem; flex-wrap: wrap; direction: ltr; align-items: center; }}
    .id {{ font-family: monospace; font-size: 12px; background: #e8f0fe; color: #1a56db; padding: 2px 8px; border-radius: 4px; }}
    .source {{ font-size: 12px; color: #555; }}
    .art {{ font-family: monospace; font-size: 12px; background: #fef3c7; color: #92400e; padding: 2px 8px; border-radius: 4px; }}
    .method {{ font-family: monospace; font-size: 11px; color: white; padding: 2px 8px; border-radius: 4px; }}
    .tokens {{ font-size: 11px; color: #666; margin-left: auto; font-family: monospace; }}
    .arabic {{ font-size: 1.05rem; line-height: 1.95; color: #111; text-align: right; direction: rtl; unicode-bidi: embed; border-top: 1px solid #eee; padding-top: 0.8rem; white-space: pre-wrap; }}
    .footer {{ font-size: 11px; color: #aaa; margin-top: 0.6rem; direction: ltr; text-align: left; font-family: monospace; }}
  </style>
</head>
<body>
  <h1>Chunks RTL Sampler — {len(samples)} random chunks · {len(chunks):,} total</h1>
  {cards}
</body>
</html>"""

out = "chunks_rtl_sample.html"
with open(out, "w", encoding="utf-8") as f:
    f.write(html)

webbrowser.open("file://" + os.path.abspath(out))
print(f"Opened {out}")
