"""Upload d'images vers Cloudinary, meme compte que trankyl_backend_nodejs
(CLOUDINARY_CLOUD_NAME) pour que tout vive dans le meme cloud. Comme ce
backend Node, on utilise uniquement l'upload NON SIGNE (cloud name + upload
preset "unsigned" configure cote dashboard Cloudinary) : pas besoin de
CLOUDINARY_API_KEY / CLOUDINARY_API_SECRET."""
import os

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MAX_UPLOAD_BYTES = 8 * 1024 * 1024  # 8 Mo


class ImageUploadError(Exception):
    pass


def upload_image(content: bytes, content_type: str) -> str:
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise ImageUploadError(f"Format non supporte : {content_type}. Utilisez JPEG, PNG, WEBP ou GIF.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise ImageUploadError("Image trop volumineuse (8 Mo maximum).")

    cloud_name = os.environ.get("CLOUDINARY_CLOUD_NAME")
    upload_preset = os.environ.get("CLOUDINARY_UPLOAD_PRESET")
    if not cloud_name or not upload_preset:
        raise ImageUploadError(
            "Upload d'images non configure (CLOUDINARY_CLOUD_NAME / CLOUDINARY_UPLOAD_PRESET manquants)."
        )

    import cloudinary
    import cloudinary.uploader

    cloudinary.config(cloud_name=cloud_name)

    try:
        # Pas de `folder`/transformation ici : le preset non signe partage
        # avec trankyl_backend_nodejs decide seul de ces reglages cote
        # dashboard Cloudinary (meme approche que src/utils/cloudinary.ts,
        # qui n'envoie que le fichier + upload_preset).
        result = cloudinary.uploader.unsigned_upload(
            content,
            upload_preset,
            resource_type="image",
        )
    except Exception as e:
        raise ImageUploadError(f"Echec de l'upload vers Cloudinary : {e}") from e

    return result["secure_url"]
