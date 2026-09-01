from pathlib import Path

path = Path("app/main.py")
text = path.read_text(encoding="utf-8")
old = 'APP_VERSION = "0.7.0-dev"\n'
new = 'APP_VERSION = os.getenv("APP_VERSION", "0.7.0-dev")\n'
count = text.count(old)
if count != 1:
    raise SystemExit(f"Expected one APP_VERSION declaration, found {count}")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
