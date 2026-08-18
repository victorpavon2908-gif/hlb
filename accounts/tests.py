from django.test import TestCase
from .models import User


class UserModelTests(TestCase):
    def test_referral_code_is_created(self):
        user = User.objects.create_user(username="demo", password="StrongPass123!")
        self.assertTrue(user.codigo_invitacion)
        self.assertEqual(len(user.codigo_invitacion), 8)

    def test_email_and_phone_can_each_be_optional(self):
        phone_user = User.objects.create_user(username="phone", telefono="+50588888888", password="StrongPass123!")
        email_user = User.objects.create_user(username="email", email="demo@example.com", password="StrongPass123!")
        self.assertIsNone(phone_user.email)
        self.assertIsNone(email_user.telefono)

    def test_block_and_unblock_tracks_reason(self):
        admin = User.objects.create_user(username="admin", password="StrongPass123!", is_staff=True)
        user = User.objects.create_user(username="blocked", email="blocked@example.com", password="StrongPass123!")
        user.block(actor=admin, reason="Revisión de seguridad")
        user.refresh_from_db()
        self.assertFalse(user.is_active)
        self.assertEqual(user.blocked_by_id, admin.id)
        self.assertEqual(user.blocked_reason, "Revisión de seguridad")
        user.unblock()
        user.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertFalse(user.blocked_reason)
