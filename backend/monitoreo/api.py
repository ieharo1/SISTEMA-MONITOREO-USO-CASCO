from rest_framework import serializers, viewsets
from .models import Evento


class EventoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Evento
        fields = [
            "id",
            "fecha",
            "camara",
            "tipo_evento",
            "confianza",
            "imagen",
            "bounding_box",
            "creado_en",
        ]


class EventoViewSet(viewsets.ModelViewSet):
    queryset = Evento.objects.all()
    serializer_class = EventoSerializer