from pathlib import Path

path = Path(__file__).with_name("v106_followup_patch.py")
text = path.read_text(encoding="utf-8")
old = '    "${Object.entries(t.sources||{}).map(([k,v])=>`${k}: ${v}`).join(\', \')}",\n'
new = '    "${Object.entries(t.sources).map(([k,v])=>`${k}: ${v}`).join(\', \')}",\n'
count = text.count(old)
if count != 1:
    raise SystemExit(f"stats-source patch fixture: expected 1 match, found {count}")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
print("follow-up patch fixture corrected")
