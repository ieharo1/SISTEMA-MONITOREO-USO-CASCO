from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from monitoreo.api import EventoViewSet
from monitoreo import views

router = DefaultRouter()
router.register(r"eventos", EventoViewSet, basename="evento")

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include(router.urls)),
    path("", views.dashboard, name="dashboard"),
    path("stream/", views.stream_mjpeg, name="stream_mjpeg"),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)