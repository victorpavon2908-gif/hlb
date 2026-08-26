from django.core.management.base import BaseCommand

from hbl_core.nowpayments_catalog import sync_nowpayments_methods


class Command(BaseCommand):
    help = "Sincroniza el catálogo NOWPayments fuera de las peticiones web."

    def handle(self, *args, **options):
        try:
            count = sync_nowpayments_methods(force=True)
        except Exception as exc:
            # El catálogo nunca debe impedir un despliegue. Los métodos base
            # USDT quedan disponibles mediante seed_payment_gateways.
            self.stderr.write(self.style.WARNING(
                f"No se pudo sincronizar NOWPayments durante el deploy: {exc}"
            ))
            return

        if count:
            self.stdout.write(self.style.SUCCESS(
                f"Catálogo NOWPayments sincronizado: {count} métodos disponibles."
            ))
        else:
            self.stdout.write(self.style.WARNING(
                "NOWPayments no devolvió catálogo; se conservan los métodos existentes."
            ))
