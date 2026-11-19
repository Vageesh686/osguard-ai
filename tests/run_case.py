import json
import sys

from app import pipeline
from app.schemas import EnvSnapshot

case_id = sys.argv[1] if len(sys.argv) > 1 else "svc-001"
case = next(c for c in map(json.loads, open("eval/cases.jsonl", encoding="utf-8")) if c["id"] == case_id)
res = pipeline.run(case["user_text"], EnvSnapshot(**case["env"]))

ex = res.extraction
print("CLASSIFIED:", ex.category, ex.error_codes, "| goal:", ex.user_goal)
print("\nRETRIEVED:")
for c in res.chunks:
    print(f"  [{c.id}] ({c.category}) {c.title}")
print("\nCLAIMS:")
for c in res.diagnosis.claims:
    print(f"  {c.kind:11} {c.text}   <- {c.evidence_ids}")
print("\nACTIONS:")
for v in res.verified:
    d = v.verdict
    print(f"  {d.final:23} tier={d.effect_tier:11} intent={d.intent} env={d.environment} evidence={d.evidence}")
    print(f"    {v.action.command}")
    for k, r in d.reasons.items():
        print(f"      {k}: {r}")
print("\nNOTES:", res.notes)