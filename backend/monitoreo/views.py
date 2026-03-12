import os
import time
from datetime import date

from django.conf import settings
from django.db.models import Count
from django.http import StreamingHttpResponse
from django.shortcuts import render

from .models import Evento

STREAM_FRAME_PATH = os.environ.get("STREAM_FRAME_PATH", str(settings.MEDIA_ROOT / "stream" / "latest.jpg"))


def dashboard(request):
    today = date.today()
    eventos_hoy = Evento.objects.filter(fecha__date=today, tipo_evento="no-helmet")
    total_alertas = eventos_hoy.count()
    eventos_recientes = Evento.objects.all()[:20]

    context = {
        "total_alertas": total_alertas,
        "eventos": eventos_recientes,
        "stream_url": "/stream/",
    }
    return render(request, "monitoreo/dashboard.html", context)


def _frame_generator():
    boundary = b"--frame\r\n"
    while True:
        if os.path.exists(STREAM_FRAME_PATH):
            with open(STREAM_FRAME_PATH, "rb") as f:
                frame = f.read()
            yield boundary
            yield b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
        time.sleep(0.05)


def stream_mjpeg(request):
    return StreamingHttpResponse(
        _frame_generator(),
        content_type="multipart/x-mixed-replace; boundary=frame",
    )