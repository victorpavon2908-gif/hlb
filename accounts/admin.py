from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class HBLUserAdmin(UserAdmin):
    list_display = (
        "username", "first_name", "email", "telefono", "country", "preferred_currency", "saldo",
        "codigo_invitacion", "referido_por", "is_staff", "is_active",
    )
    list_filter = ("country", "contact_preference", "is_staff", "is_active")
    search_fields = ("username", "first_name", "last_name", "email", "telefono", "codigo_invitacion")
    readonly_fields = (
        "saldo", "codigo_invitacion", "blocked_at", "blocked_by", "date_joined", "last_login",
    )
    fieldsets = UserAdmin.fieldsets + (
        ("HBL · contacto internacional", {
            "fields": ("country", "preferred_currency", "telefono", "contact_preference", "saldo", "codigo_invitacion", "referido_por")
        }),
        ("HBL · seguridad", {"fields": ("blocked_reason", "blocked_at", "blocked_by")}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("HBL", {"fields": ("first_name", "last_name", "country", "preferred_currency", "email", "telefono", "contact_preference", "referido_por")}),
    )
