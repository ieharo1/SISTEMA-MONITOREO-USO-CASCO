from django.contrib import admin
from .models import Evento


@admin.register(Evento)
class EventoAdmin(admin.ModelAdmin):
    list_display = ("fecha", "camara", "tipo_evento", "confianza")
    list_filter = ("camara", "tipo_evento")
    search_fields = ("camara",)