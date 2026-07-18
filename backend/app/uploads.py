from dataclasses import dataclass
from pathlib import Path
import shutil
import uuid

from fastapi import HTTPException, UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError

from .config import settings


@dataclass
class PreparedUpload:
    image_id: str
    original_filename: str
    storage_path: Path
    thumbnail_path: Path
    mime_type: str
    width: int
    height: int
    file_size: int


FORMAT_INFO = {
    "JPEG": (".jpg", "image/jpeg"),
    "PNG": (".png", "image/png"),
}


async def prepare_image_upload(project_id: str, upload: UploadFile) -> PreparedUpload:
    """Stream, inspect and atomically store one trusted JPEG/PNG upload."""
    temp_root = settings.storage_root / ".tmp"
    originals = settings.storage_root / project_id / "originals"
    thumbnails = settings.storage_root / project_id / "thumbnails"
    temp_root.mkdir(parents=True, exist_ok=True)
    originals.mkdir(parents=True, exist_ok=True)
    thumbnails.mkdir(parents=True, exist_ok=True)

    token = uuid.uuid4().hex
    temp_image = temp_root / f"{token}.upload"
    temp_thumb = temp_root / f"{token}.thumb"
    limit = settings.max_image_mb * 1024 * 1024
    size = 0
    try:
        with temp_image.open("wb") as target:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, f"Ficheiro demasiado grande: {Path(upload.filename or 'imagem').name}")
                target.write(chunk)
        if size == 0:
            raise HTTPException(400, "A imagem enviada está vazia.")

        try:
            with Image.open(temp_image) as probe:
                image_format = probe.format
                if image_format not in FORMAT_INFO:
                    raise HTTPException(415, "Apenas imagens JPEG e PNG são suportadas.")
                if probe.width * probe.height > settings.max_image_pixels:
                    raise HTTPException(413, "A resolução da imagem excede o limite de segurança.")
                probe.verify()
            extension, mime_type = FORMAT_INFO[image_format]
            with Image.open(temp_image) as source:
                corrected = ImageOps.exif_transpose(source)
                width, height = corrected.size
                thumbnail = corrected.convert("RGB")
                thumbnail.thumbnail((640, 480))
                thumbnail.save(temp_thumb, "JPEG", quality=86, optimize=True)
        except HTTPException:
            raise
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise HTTPException(400, f"Imagem corrompida ou inválida: {Path(upload.filename or 'imagem').name}") from exc

        image_id = str(uuid.uuid4())
        final_image = originals / f"{image_id}{extension}"
        final_thumb = thumbnails / f"{image_id}.jpg"
        temp_image.replace(final_image)
        temp_thumb.replace(final_thumb)
        return PreparedUpload(
            image_id=image_id,
            original_filename=Path(upload.filename or "imagem").name,
            storage_path=final_image,
            thumbnail_path=final_thumb,
            mime_type=mime_type,
            width=width,
            height=height,
            file_size=size,
        )
    finally:
        temp_image.unlink(missing_ok=True)
        temp_thumb.unlink(missing_ok=True)
        await upload.close()


def remove_prepared_upload(item: PreparedUpload) -> None:
    item.storage_path.unlink(missing_ok=True)
    item.thumbnail_path.unlink(missing_ok=True)


def cleanup_orphaned_temporary_uploads() -> None:
    shutil.rmtree(settings.storage_root / ".tmp", ignore_errors=True)
