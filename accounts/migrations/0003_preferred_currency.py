from django.db import migrations, models


def fill_currency(apps, schema_editor):
    User = apps.get_model('accounts', 'User')
    try:
        from accounts.country_currency import COUNTRY_CURRENCY
    except Exception:
        COUNTRY_CURRENCY = {}
    for user in User.objects.all().only('id', 'country', 'preferred_currency').iterator():
        if not user.preferred_currency:
            user.preferred_currency = COUNTRY_CURRENCY.get(user.country, 'USD')
            user.save(update_fields=['preferred_currency'])


class Migration(migrations.Migration):
    dependencies = [('accounts', '0002_worldwide_contact_blocking')]
    operations = [
        migrations.AddField(
            model_name='user',
            name='preferred_currency',
            field=models.CharField(blank=True, default='', help_text='Moneda usada para mostrar equivalencias al usuario.', max_length=3),
        ),
        migrations.RunPython(fill_currency, migrations.RunPython.noop),
    ]
