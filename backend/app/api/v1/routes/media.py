"""Serve locally stored claim images. Paths contain unguessable UUIDs."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import Response

from app.core.errors import NotFoundError, ProviderUnavailableError
from app.media.storage import FileSystemStorage, get_storage

router = APIRouter(tags=["media"])


@router.get("/media/{key:path}")
def get_media(key: str):
    storage = get_storage()
    if not isinstance(storage, FileSystemStorage):
        raise NotFoundError("Direct media URLs are only used with local filesystem storage.")
    try:
        data = storage.get(key)
    except ProviderUnavailableError as exc:
        raise NotFoundError("Image not found.") from exc
    suffix = key.rsplit(".", 1)[-1].lower()
    media = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}.get(
        suffix, "application/octet-stream"
    )
    return Response(content=data, media_type=media)
