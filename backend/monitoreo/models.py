from django.db import models
from django.utils import timezone


class Evento(models.Model):
    TIPO_EVENTO_CHOICES = [
        ("no-helmet", "No Helmet"),
        ("helmet", "Helmet"),
    ]

    fecha = models.DateTimeField(default=timezone.now)
    camara = models.CharField(max_length=100)
    tipo_evento = models.CharField(max_length=20, choices=TIPO_EVENTO_CHOICES)
    confianza = models.FloatField()
    imagen = models.ImageField(upload_to="evidence/%Y/%m/%d/")
    bounding_box = models.JSONField()
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "eventos"
        ordering = ["-fecha"]

    def __str__(self) -> str:
        return f"{self.camara} - {self.tipo_evento} - {self.fecha}"