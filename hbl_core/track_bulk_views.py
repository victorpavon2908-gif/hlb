import re
from pathlib import Path

from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from .models import AdminAuditLog, PlatformConfig, Track


ALLOWED_AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".m4a", ".aac", ".flac"}
MAX_AUDIO_BYTES = 25 * 1024 * 1024


def _clean_stem(filename):
    stem = Path(filename or "").stem.strip()
    # Quita numeraciones comunes: 01 - Tema, 001. Tema, 03_ Tema, etc.
    stem = re.sub(r"^\s*\d{1,4}\s*(?:[-._)]\s*)?", "", stem).strip()
    return stem or "Pista"


def _title_artist_from_filename(filename, default_artist=""):
    stem = _clean_stem(filename)
    for separator in (" - ", " – ", " — "):
        if separator in stem:
            artist, title = stem.split(separator, 1)
            artist = artist.strip() or default_artist
            title = title.strip() or stem
            return title[:160], artist[:160]
    return stem[:160], (default_artist or "").strip()[:160]


def _unique_slug(title, artist):
    raw = f"{artist}-{title}" if artist else title
    base = (slugify(raw) or "pista")[:165]
    candidate = base
    index = 2
    while Track.objects.filter(slug=candidate).exists():
        suffix = f"-{index}"
        candidate = f"{base[:180-len(suffix)]}{suffix}"
        index += 1
    return candidate


@staff_member_required(login_url="hbl_login")
@require_POST
def upload_track_file(request):
    """Recibe un audio por petición.

    La pantalla de carga masiva envía los archivos uno a uno de forma automática.
    Así el administrador selecciona decenas de canciones una sola vez sin enviar
    un ZIP o una petición HTTP enorme que pueda agotar Render.
    """
    audio = request.FILES.get("audio")
    if not audio:
        return JsonResponse({"ok": False, "error": "No se recibió ningún archivo."}, status=400)

    extension = Path(audio.name or "").suffix.lower()
    if extension not in ALLOWED_AUDIO_EXTENSIONS:
        return JsonResponse({
            "ok": False,
            "error": "Formato no permitido. Usa MP3, WAV, OGG, M4A, AAC o FLAC.",
        }, status=400)
    if getattr(audio, "size", 0) > MAX_AUDIO_BYTES:
        return JsonResponse({"ok": False, "error": "El audio supera el máximo de 25 MB."}, status=400)

    default_artist = (request.POST.get("artist_default") or "").strip()
    title, artist = _title_artist_from_filename(audio.name, default_artist)

    # Evita cargar dos veces la misma pista identificada por título + artista.
    duplicate = Track.objects.filter(title__iexact=title, artist__iexact=artist).first()
    if duplicate:
        return JsonResponse({
            "ok": True,
            "skipped": True,
            "track_id": duplicate.pk,
            "title": duplicate.title,
            "artist": duplicate.artist,
            "message": "Duplicada: ya estaba en el catálogo.",
        })

    config = PlatformConfig.get_solo()
    try:
        min_listen_seconds = int(request.POST.get("min_listen_seconds") or config.listen_verification_seconds or 10)
    except (TypeError, ValueError):
        min_listen_seconds = int(config.listen_verification_seconds or 10)
    min_listen_seconds = max(5, min(120, min_listen_seconds))

    track = Track(
        title=title,
        artist=artist,
        slug=_unique_slug(title, artist),
        audio=audio,
        duration_seconds=max(180, min_listen_seconds),
        min_listen_seconds=min_listen_seconds,
        active=True,
        featured=False,
    )
    track.full_clean()
    track.save()

    AdminAuditLog.objects.create(
        actor=request.user,
        action="track_bulk_uploaded",
        target_type="Track",
        target_id=str(track.pk),
        detail={
            "title": track.title,
            "artist": track.artist,
            "filename": audio.name,
            "size": getattr(audio, "size", 0),
        },
    )

    return JsonResponse({
        "ok": True,
        "skipped": False,
        "track_id": track.pk,
        "title": track.title,
        "artist": track.artist,
        "message": "Canción agregada al catálogo global.",
    })
