from django.apps import AppConfig


class HblCoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "hbl_core"
    verbose_name = "HBL · Música y recompensas"

    def ready(self):
        # Registra la validación automática de depósitos USDT al iniciar Django.
        from . import signals  # noqa: F401
