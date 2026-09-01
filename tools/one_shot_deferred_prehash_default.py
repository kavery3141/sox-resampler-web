from pathlib import Path

path = Path("app/jobs.py")
text = path.read_text(encoding="utf-8")
old = """    def _retry_deferred_files(\n        self,\n        job_id: int,\n        profile: ResampleProfile,\n        source_pre_hash: bool,\n    ) -> tuple[str, str | None]:\n"""
new = """    def _retry_deferred_files(\n        self,\n        job_id: int,\n        profile: ResampleProfile,\n        source_pre_hash: bool = False,\n    ) -> tuple[str, str | None]:\n"""
count = text.count(old)
if count != 1:
    raise SystemExit(f"expected exactly one deferred retry signature, found {count}")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
print("Defaulted deferred retry source pre-hash to false")
