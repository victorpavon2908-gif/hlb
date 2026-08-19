from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Ejecuta todas las reconciliaciones automáticas de pagos HBL."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **options):
        limit = max(1, min(int(options["limit"] or 100), 1000))
        commands = [
            "sync_binance_pay",
            "sync_paypal_deposits",
            "sync_tilopay_deposits",
            "sync_crypto_deposits",
        ]
        for command in commands:
            self.stdout.write(self.style.MIGRATE_HEADING(f"== {command} =="))
            try:
                call_command(command, limit=limit)
            except Exception as exc:
                # Un proveedor sin credenciales no debe impedir reconciliar los demás.
                self.stderr.write(self.style.WARNING(f"{command}: {exc}"))

        self.stdout.write(self.style.SUCCESS("Reconciliación global de pagos finalizada."))
