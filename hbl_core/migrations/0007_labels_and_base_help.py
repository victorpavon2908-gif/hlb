from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('hbl_core', '0006_withdrawal_multicurrency_methods')]
    operations = [
        migrations.AlterField(
            model_name='currencyrate',
            name='code',
            field=models.CharField(db_index=True, max_length=12, unique=True),
        ),
        migrations.AlterField(
            model_name='paymentmethod',
            name='balance_rate',
            field=models.DecimalField(decimal_places=8, default=1, help_text='Cuántas unidades de moneda base se acreditan por 1 unidad de la moneda de pago.', max_digits=18),
        ),
        migrations.AlterField(
            model_name='wheelprize',
            name='reward_type',
            field=models.CharField(choices=[('balance', 'Saldo (moneda base)'), ('membership_days', 'Días extra de membresía'), ('none', 'Sin premio')], default='balance', max_length=24),
        ),
        migrations.AlterField(
            model_name='giftcode',
            name='reward_type',
            field=models.CharField(choices=[('balance', 'Saldo (moneda base)'), ('membership_days', 'Días extra de membresía')], default='balance', max_length=24),
        ),
        migrations.AlterField(
            model_name='referralearning',
            name='kind',
            field=models.CharField(choices=[('first_deposit', 'Primera recarga'), ('deposit_commission', 'Comisión primera recarga'), ('manual', 'Manual')], max_length=24),
        ),
    ]
