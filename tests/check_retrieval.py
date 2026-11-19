import json
from app.stages.retrieve import retrieve

cases = [json.loads(l) for l in open("eval/cases.jsonl", encoding="utf-8")]
for c in cases:
    print("\n=== ", c["id"], "|", c["user_text"][:70])
    for ch in retrieve(c["user_text"], None, k=5):
        print(f"  [{ch.id}] ({ch.category}) {ch.title}")