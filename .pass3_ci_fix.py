from pathlib import Path

path = Path("backend/services/manager_v2.py")
text = path.read_text(encoding="utf-8")
old = '            current_file_size = int(row["size_bytes"] or 0)'
new = '            current_file_size = int(row.get("size_bytes") or 0)'
count = text.count(old)
if count != 1:
    raise SystemExit(f"expected one size_bytes row access, found {count}")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
print("PASS3 CI COMPAT FIX: PASS")
