from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Evento",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("fecha", models.DateTimeField(default=django.utils.timezone.now)),
                ("camara", models.CharField(max_length=100)),
                ("tipo_evento", models.CharField(choices=[("no-helmet", "No Helmet"), ("helmet", "Helmet")], max_length=20)),
                ("confianza", models.FloatField()),
                ("imagen", models.ImageField(upload_to="evidence/%Y/%m/%d/")),
                ("bounding_box", models.JSONField()),
                ("creado_en", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "eventos",
                "ordering": ["-fecha"],
            },
        ),
    ]