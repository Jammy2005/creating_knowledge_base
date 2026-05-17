import json

input_path = "output/corpus.jsonl"
output_path = "output/corpus_clean.jsonl"

with open(input_path) as f:
    docs = [json.loads(line) for line in f if line.strip()]

before = len(docs)
docs = [d for d in docs if d["id"] != "kw_cbk_0203"]
print(f"Removed {before - len(docs)} doc(s). {len(docs)} remaining.")

with open(output_path, "w") as f:
    for d in docs:
        f.write(json.dumps(d, ensure_ascii=False) + "\n")

print(f"Written to {output_path}")