from django.apps import AppConfig


class HblCoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "hbl_core"
    verbose_name = "HBL · Música y recompensas"

    def ready(self):
        # Conserva la validación de depósitos antiguos que todavía tengan TXID.
        from . import signals  # noqa: F401

        # Reglas comerciales globales: plan activo para recompensas de referidos
        # y para solicitar retiros.
        from .eligibility_policies import install_eligibility_policies
        install_eligibility_policies()
