from pathlib import Path

path = Path("tools/one_shot_source_prehash.py")
text = path.read_text(encoding="utf-8")
old = '''    count = text.count(old)\n    allowed_ambiguous_first = label == "retry review pre-hash pass" and count == 2\n    if count != 1 and not allowed_ambiguous_first:\n        raise SystemExit(f"{label}: expected one match in {path}, found {count}")\n    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")\n'''
new = '''    count = text.count(old)\n    allowed_ambiguous_first = (\n        label in {"retry review pre-hash pass", "retry start operational snapshot"}\n        and count == 2\n    )\n    if count != 1 and not allowed_ambiguous_first:\n        raise SystemExit(f"{label}: expected one match in {path}, found {count}")\n    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")\n'''
if text.count(old) != 1:
    raise SystemExit("current source pre-hash helper guard did not match exactly once")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
print("Extended source pre-hash helper ambiguity guard")
