from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str, label: str) -> None:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match in {path}, found {count}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "app/main.py",
    "from .issues import build_metadata_issues, filter_issues, render_issues_csv, render_issues_txt\n",
    "from .issues import build_metadata_issues, filter_issues, render_issues_csv, render_issues_txt\nfrom .path_display import (\n    decorate_album_paths,\n    decorate_issue_paths,\n    decorate_job_report_paths,\n    decorate_review_paths,\n)\n",
    "main path display imports",
)
replace_once(
    "app/main.py",
    'MUSIC_ROOT = Path(os.getenv("MUSIC_ROOT", "/music"))\nDATA_ROOT = Path(os.getenv("DATA_ROOT", "/data"))\n',
    'MUSIC_ROOT = Path(os.getenv("MUSIC_ROOT", "/music"))\nHOST_MUSIC_ROOT = Path(os.getenv("HOST_MUSIC_ROOT", str(MUSIC_ROOT)))\nDATA_ROOT = Path(os.getenv("DATA_ROOT", "/data"))\n',
    "host music root config",
)
replace_once(
    "app/main.py",
    '    review["source_pre_hash"] = bool(source_pre_hash)\n    return _apply_operational_review_checks(review, reserve)\n',
    '    review["source_pre_hash"] = bool(source_pre_hash)\n    review = _apply_operational_review_checks(review, reserve)\n    return decorate_review_paths(review, MUSIC_ROOT, HOST_MUSIC_ROOT)\n',
    "review display paths",
)
replace_once(
    "app/main.py",
    '        "music_root": {\n            "path": str(MUSIC_ROOT),\n            "exists": music_exists,\n',
    '        "music_root": {\n            "path": str(MUSIC_ROOT),\n            "host_path": str(HOST_MUSIC_ROOT),\n            "exists": music_exists,\n',
    "health host music root",
)
replace_once(
    "app/main.py",
    '        "music_root": str(MUSIC_ROOT),\n        "data_root": str(DATA_ROOT),\n',
    '        "music_root": str(MUSIC_ROOT),\n        "host_music_root": str(HOST_MUSIC_ROOT),\n        "data_root": str(DATA_ROOT),\n',
    "status host music root",
)
replace_once(
    "app/main.py",
    '    albums = db.candidate_albums(DB_PATH, cleaned, above)\n    return {"rates": cleaned, "above": above, "count": len(albums), "albums": albums}\n',
    '    albums = db.candidate_albums(DB_PATH, cleaned, above)\n    for album in albums:\n        decorate_album_paths(album, MUSIC_ROOT, HOST_MUSIC_ROOT)\n    return {"rates": cleaned, "above": above, "count": len(albums), "albums": albums}\n',
    "candidate display folders",
)
replace_once(
    "app/main.py",
    '        issues = filter_issues(build_metadata_issues(DB_PATH), severity)\n    except ValueError as exc:\n        raise HTTPException(status_code=400, detail=str(exc)) from exc\n    counts = {"blocking": 0, "warning": 0, "info": 0}\n',
    '        issues = filter_issues(build_metadata_issues(DB_PATH), severity)\n    except ValueError as exc:\n        raise HTTPException(status_code=400, detail=str(exc)) from exc\n    decorate_issue_paths(issues, MUSIC_ROOT, HOST_MUSIC_ROOT)\n    counts = {"blocking": 0, "warning": 0, "info": 0}\n',
    "issues API display paths",
)
# The two report endpoints have the same exception block; patch by including the following return.
replace_once(
    "app/main.py",
    '    return _attachment(\n        render_issues_txt(issues, TIMEZONE),\n',
    '    decorate_issue_paths(issues, MUSIC_ROOT, HOST_MUSIC_ROOT)\n    return _attachment(\n        render_issues_txt(issues, TIMEZONE),\n',
    "issues txt report display paths",
)
replace_once(
    "app/main.py",
    '    return _attachment(\n        render_issues_csv(issues),\n',
    '    decorate_issue_paths(issues, MUSIC_ROOT, HOST_MUSIC_ROOT)\n    return _attachment(\n        render_issues_csv(issues),\n',
    "issues csv report display paths",
)
replace_once(
    "app/main.py",
    '    if not report:\n        raise HTTPException(status_code=404, detail="Job not found")\n    return _attachment(\n        render_job_txt(report),\n',
    '    if not report:\n        raise HTTPException(status_code=404, detail="Job not found")\n    decorate_job_report_paths(report, MUSIC_ROOT, HOST_MUSIC_ROOT)\n    return _attachment(\n        render_job_txt(report),\n',
    "job txt report display paths",
)
replace_once(
    "app/main.py",
    '    if not report:\n        raise HTTPException(status_code=404, detail="Job not found")\n    return _attachment(\n        render_job_csv(report),\n',
    '    if not report:\n        raise HTTPException(status_code=404, detail="Job not found")\n    decorate_job_report_paths(report, MUSIC_ROOT, HOST_MUSIC_ROOT)\n    return _attachment(\n        render_job_csv(report),\n',
    "job csv report display paths",
)

replace_once(
    "app/issues.py",
    '        folders = issue.get("folders") or ([issue.get("folder", "")] if issue.get("folder") else [])\n',
    '        folders = issue.get("display_folders") or issue.get("folders") or ([issue.get("display_folder") or issue.get("folder", "")] if (issue.get("display_folder") or issue.get("folder")) else [])\n',
    "issue txt display folders",
)
replace_once(
    "app/issues.py",
    '            track_path = track.get("path", "")\n            suffix = f" [{track_path}]" if track_path else ""\n',
    '            track_path = track.get("display_path") or track.get("path", "")\n            suffix = f" [{track_path}]" if track_path else ""\n',
    "issue txt display track path",
)
replace_once(
    "app/issues.py",
    '            track_path = str(track.get("path", ""))\n            folder = str(Path(track_path).parent) if track_path else issue.get("folder", "")\n',
    '            track_path = str(track.get("display_path") or track.get("path", ""))\n            folder = str(Path(track_path).parent) if track_path else (issue.get("display_folder") or issue.get("folder", ""))\n',
    "issue csv display path",
)

replace_once(
    "app/reports.py",
    '            f"{album.get(\'albumartist\') or \'\'} / {album.get(\'album\') or \'\'} / {album.get(\'folder\') or \'\'}"\n',
    '            f"{album.get(\'albumartist\') or \'\'} / {album.get(\'album\') or \'\'} / {album.get(\'display_folder\') or album.get(\'folder\') or \'\'}"\n',
    "review txt display folder",
)
replace_once(
    "app/reports.py",
    '                f"{track.get(\'path\') or \'\'}; "\n',
    '                f"{track.get(\'display_path\') or track.get(\'path\') or \'\'}; "\n',
    "review txt display track path",
)
replace_once(
    "app/reports.py",
    '                    "folder": album.get("folder") or "",\n                    "path": track.get("path") or "",\n',
    '                    "folder": album.get("display_folder") or album.get("folder") or "",\n                    "path": track.get("display_path") or track.get("path") or "",\n',
    "review csv display paths",
)
replace_once(
    "app/reports.py",
    '            f"[{item[\'status\']}] {item.get(\'albumartist\') or \'\'} / {item.get(\'album\') or \'\'} / {item.get(\'path\') or \'\'}"\n',
    '            f"[{item[\'status\']}] {item.get(\'albumartist\') or \'\'} / {item.get(\'album\') or \'\'} / {item.get(\'display_path\') or item.get(\'path\') or \'\'}"\n',
    "job txt display path",
)
replace_once(
    "app/reports.py",
    '                "path": item.get("path") or "",\n',
    '                "path": item.get("display_path") or item.get("path") or "",\n',
    "job csv display path",
)

replace_once(
    "app/static/ui.js",
    "  const relative=String(album.folder||'').replace(/^\\/music\\/?/,'');\n",
    "  const relative=String(album.folder||'').replace(/^\\/music\\/?/,'');\n  const displayFolder=album.display_folder||album.folder||'';\n",
    "library display folder variable",
)
replace_once(
    "app/static/ui.js",
    "<span class=\"muted\">Folder</span><span class=\"copyLine\"><code>${esc(album.folder||'')}</code><button class=\"copyPath\">Copy Path</button></span>",
    "<span class=\"muted\">Folder</span><span class=\"copyLine\"><code>${esc(displayFolder)}</code><button class=\"copyPath\">Copy Path</button></span>",
    "library visible host folder",
)
replace_once(
    "app/static/ui.js",
    "    detail.querySelector('.copyPath').onclick=()=>navigator.clipboard?.writeText(album.folder||'');\n",
    "    detail.querySelector('.copyPath').onclick=()=>navigator.clipboard?.writeText(album.display_folder||album.folder||'');\n",
    "library copy host folder",
)

replace_once(
    "app/static/issues-ui.js",
    "  const folders=(issue.folders||[]).join(' ');\n  return `${issue.albumartist||''} ${issue.album||''} ${issue.folder||''} ${folders} ${issue.summary||''} ${issue.issue_type||''} ${tracks}`.toLowerCase().includes(issueUiState.query);\n",
    "  const folders=(issue.display_folders||issue.folders||[]).join(' ');\n  return `${issue.albumartist||''} ${issue.album||''} ${issue.display_folder||issue.folder||''} ${folders} ${issue.summary||''} ${issue.issue_type||''} ${tracks}`.toLowerCase().includes(issueUiState.query);\n",
    "issues search display paths",
)
replace_once(
    "app/static/issues-ui.js",
    "    const folders=(issue.folders||[]).length?issue.folders:[issue.folder].filter(Boolean);\n",
    "    const folders=(issue.display_folders||[]).length?issue.display_folders:((issue.folders||[]).length?issue.folders:[issue.display_folder||issue.folder].filter(Boolean));\n",
    "issues visible host folders",
)
replace_once(
    "app/static/issues-ui.js",
    "  box.querySelectorAll('[data-copy-folder]').forEach(button=>button.onclick=()=>{const [i,f]=button.dataset.copyFolder.split(':').map(Number);const issue=rows[i];const folders=(issue?.folders||[]).length?issue.folders:[issue?.folder].filter(Boolean);navigator.clipboard?.writeText(folders[f]||'')});\n",
    "  box.querySelectorAll('[data-copy-folder]').forEach(button=>button.onclick=()=>{const [i,f]=button.dataset.copyFolder.split(':').map(Number);const issue=rows[i];const folders=(issue?.display_folders||[]).length?issue.display_folders:((issue?.folders||[]).length?issue.folders:[issue?.display_folder||issue?.folder].filter(Boolean));navigator.clipboard?.writeText(folders[f]||'')});\n",
    "issues copy host folder",
)
replace_once(
    "app/static/issues-ui.js",
    "  box.querySelectorAll('[data-copy-track]').forEach(button=>button.onclick=()=>{const [i,t]=button.dataset.copyTrack.split(':').map(Number);const track=rows[i]?.affected_tracks?.[t];navigator.clipboard?.writeText(track?.path||'')});\n",
    "  box.querySelectorAll('[data-copy-track]').forEach(button=>button.onclick=()=>{const [i,t]=button.dataset.copyTrack.split(':').map(Number);const track=rows[i]?.affected_tracks?.[t];navigator.clipboard?.writeText(track?.display_path||track?.path||'')});\n",
    "issues copy host track path",
)
replace_once(
    "app/static/issues-ui.js",
    "  const tracks=(issue.affected_tracks||[]).map(t=>`${t.filename||''} ${t.path||''} ${t.value||''}`).join(' ');\n",
    "  const tracks=(issue.affected_tracks||[]).map(t=>`${t.filename||''} ${t.display_path||t.path||''} ${t.value||''}`).join(' ');\n",
    "issues track search host path",
)

replace_once(
    "compose.truenas.yaml",
    "      MUSIC_ROOT: /music\n      DATA_ROOT: /data\n",
    "      MUSIC_ROOT: /music\n      HOST_MUSIC_ROOT: /mnt/MainStorage/StorageDataset/Music\n      DATA_ROOT: /data\n",
    "compose host music root",
)
replace_once(
    "README.md",
    "- music dataset: `/mnt/MainStorage/StorageDataset/Music` -> `/music`\n",
    "- music dataset: `/mnt/MainStorage/StorageDataset/Music` -> `/music`; `HOST_MUSIC_ROOT` preserves the TrueNAS-visible path for UI copy actions and reports while internal conversion paths stay under `/music`\n",
    "README host path documentation",
)

# Extend path-display tests to prove exports choose host-visible paths when available.
replace_once(
    "tests/test_path_display.py",
    "from app.path_display import (\n",
    "from app.issues import render_issues_csv, render_issues_txt\nfrom app.path_display import (\n",
    "path display issue render imports",
)
replace_once(
    "tests/test_path_display.py",
    "from app.path_display import (\n    decorate_issue_paths,\n",
    "from app.path_display import (\n    decorate_issue_paths,\n",
    "path display stable import anchor",
)
# Add reports imports separately after the path_display import block.
replace_once(
    "tests/test_path_display.py",
    "    host_music_path,\n)\n\n\nclass HostMusicPathTests",
    "    host_music_path,\n)\nfrom app.reports import render_job_csv, render_job_txt\n\n\nclass HostMusicPathTests",
    "path display job render imports",
)
replace_once(
    "tests/test_path_display.py",
    "        self.assertEqual(\n            report[\"files\"][0][\"display_path\"],\n            \"/mnt/MainStorage/StorageDataset/Music/Artist/Album/01.flac\",\n        )\n\n\nif __name__ == \"__main__\":\n",
    "        self.assertEqual(\n            report[\"files\"][0][\"display_path\"],\n            \"/mnt/MainStorage/StorageDataset/Music/Artist/Album/01.flac\",\n        )\n\n    def test_exports_prefer_true_nas_display_paths(self) -> None:\n        issues = [{\n            \"severity\": \"blocking\",\n            \"issue_type\": \"missing_album\",\n            \"albumartist\": \"Artist\",\n            \"album\": \"Album\",\n            \"folder\": \"/music/Artist/Album\",\n            \"folders\": [\"/music/Artist/Album\"],\n            \"summary\": \"ALBUM missing\",\n            \"affected_tracks\": [{\"path\": \"/music/Artist/Album/01.flac\", \"filename\": \"01.flac\", \"value\": \"(missing)\"}],\n        }]\n        decorate_issue_paths(issues, self.music_root, self.host_root)\n        txt = render_issues_txt(issues, \"America/Indiana/Indianapolis\")\n        csv_text = render_issues_csv(issues)\n        self.assertIn(\"/mnt/MainStorage/StorageDataset/Music/Artist/Album/01.flac\", txt)\n        self.assertIn(\"/mnt/MainStorage/StorageDataset/Music/Artist/Album/01.flac\", csv_text)\n\n        report = {\n            \"job_id\": 1, \"timezone\": \"America/Indiana/Indianapolis\", \"status\": \"completed\",\n            \"created_at\": \"\", \"started_at\": \"\", \"finished_at\": \"\", \"profile_id\": \"test\",\n            \"profile\": {}, \"workers\": 1, \"operational\": {}, \"events\": [], \"job_error\": None,\n            \"totals\": {\"files\": 1, \"completed\": 1, \"failed\": 0, \"remaining\": 0, \"source_bytes\": 1, \"final_bytes\": 1, \"savings_bytes\": 0},\n            \"files\": [{\"status\": \"completed\", \"albumartist\": \"Artist\", \"album\": \"Album\", \"path\": \"/music/Artist/Album/01.flac\", \"source_bytes\": 1, \"final_bytes\": 1, \"savings_bytes\": 0}],\n        }\n        decorate_job_report_paths(report, self.music_root, self.host_root)\n        self.assertIn(\"/mnt/MainStorage/StorageDataset/Music/Artist/Album/01.flac\", render_job_txt(report))\n        self.assertIn(\"/mnt/MainStorage/StorageDataset/Music/Artist/Album/01.flac\", render_job_csv(report))\n\n\nif __name__ == \"__main__\":\n",
    "path display export tests",
)
