from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from .profile_store import (
    create_custom_profile,
    delete_custom_profile,
    duplicate_profile,
    export_profile,
    get_profile,
    import_profile,
    list_all_profiles,
    preview_import,
    update_custom_profile,
)


class DuplicatePresetRequest(BaseModel):
    name: str | None = None


class ImportPresetRequest(BaseModel):
    document: dict[str, Any]
    name: str | None = None


def _fail(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


def build_profiles_router(db_path: Path) -> APIRouter:
    router = APIRouter()

    @router.get("/api/profiles/{profile_id}")
    def get_one_profile(profile_id: str) -> dict[str, Any]:
        try:
            return get_profile(db_path, profile_id).to_dict()
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/api/profiles")
    def create_profile(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return create_custom_profile(db_path, payload).to_dict()
        except ValueError as exc:
            raise _fail(exc) from exc

    @router.put("/api/profiles/{profile_id}")
    def update_profile(profile_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return update_custom_profile(db_path, profile_id, payload).to_dict()
        except ValueError as exc:
            raise _fail(exc) from exc

    @router.delete("/api/profiles/{profile_id}")
    def delete_profile(profile_id: str) -> dict[str, Any]:
        try:
            delete_custom_profile(db_path, profile_id)
        except ValueError as exc:
            raise _fail(exc) from exc
        return {"ok": True, "profile_id": profile_id}

    @router.post("/api/profiles/{profile_id}/duplicate")
    def duplicate(profile_id: str, request: DuplicatePresetRequest) -> dict[str, Any]:
        try:
            return duplicate_profile(db_path, profile_id, request.name).to_dict()
        except ValueError as exc:
            raise _fail(exc) from exc

    @router.get("/api/profiles/{profile_id}/export.json")
    def export(profile_id: str) -> Response:
        try:
            profile = get_profile(db_path, profile_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        document = export_profile(profile)
        filename = "sox-resampler-preset-" + "".join(
            c.lower() if c.isalnum() else "-" for c in profile.name
        ).strip("-")[:80] + ".json"
        return Response(
            content=json.dumps(document, indent=2, sort_keys=True) + "\n",
            media_type="application/json; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @router.post("/api/profiles/import/preview")
    def import_preview(request: ImportPresetRequest) -> dict[str, Any]:
        try:
            profile = preview_import(request.document)
        except ValueError as exc:
            raise _fail(exc) from exc
        return {
            "valid": True,
            "schema": request.document.get("schema"),
            "schema_version": request.document.get("schema_version"),
            "profile": profile.to_dict(),
        }

    @router.post("/api/profiles/import")
    def import_document(request: ImportPresetRequest) -> dict[str, Any]:
        try:
            return import_profile(db_path, request.document, request.name).to_dict()
        except ValueError as exc:
            raise _fail(exc) from exc

    @router.get("/api/profiles-all", include_in_schema=False)
    def compatibility_profile_list() -> dict[str, Any]:
        # Kept as a small diagnostic route while the main /api/profiles endpoint owns the UI list.
        profiles = [profile.to_dict() for profile in list_all_profiles(db_path)]
        return {"profiles": profiles}

    return router
