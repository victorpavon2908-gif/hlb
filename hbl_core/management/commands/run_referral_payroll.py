from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from hbl_core.services import create_referral_payroll


class Command(BaseCommand):
    help = "Genera el sueldo semanal por referidos activos de forma idempotente."

    def add_arguments(self, parser):
        parser.add_argument("--pay", action="store_true", help="Acredita el sueldo al saldo al crearlo.")

    def handle(self, *args, **options):
        User = get_user_model()
        users = User.objects.filter(referidos__isnull=False).distinct() if hasattr(User, "referidos") else User.objects.all()
        created = paid = 0
        for user in users.iterator():
            payroll, was_created = create_referral_payroll(user, pay=options["pay"])
            if was_created:
                created += 1
                if payroll.status == payroll.Status.PAID:
                    paid += 1
        self.stdout.write(self.style.SUCCESS(f"Nóminas creadas: {created}. Pagadas: {paid}."))
