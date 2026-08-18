
from decimal import Decimal
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('hbl_core', '0003_ultra_control_rewards'),
    ]

    operations = [
        migrations.AddField(
            model_name='platformconfig',
            name='base_currency_code',
            field=models.CharField(default='NIO', max_length=12),
        ),
        migrations.AddField(
            model_name='platformconfig',
            name='base_currency_symbol',
            field=models.CharField(default='C$', max_length=8),
        ),
        migrations.AddField(
            model_name='platformconfig',
            name='free_upgrade_referrals_required',
            field=models.PositiveSmallIntegerField(default=5),
        ),
        migrations.AddField(
            model_name='platformconfig',
            name='wheel_min_qualified_referrals',
            field=models.PositiveSmallIntegerField(default=1),
        ),
        migrations.AddField(
            model_name='platformconfig',
            name='wheel_requires_qualified_referral',
            field=models.BooleanField(default=True),
        ),
        migrations.AlterField(
            model_name='platformconfig',
            name='withdrawal_min',
            field=models.DecimalField(decimal_places=2, default=Decimal('500.00'), max_digits=12),
        ),
        migrations.AlterField(
            model_name='platformconfig',
            name='referral_first_deposit_percent',
            field=models.DecimalField(decimal_places=2, default=Decimal('10.00'), max_digits=5),
        ),
        migrations.AlterField(
            model_name='track',
            name='min_listen_seconds',
            field=models.PositiveIntegerField(default=10),
        ),
        migrations.CreateModel(
            name='ReferralUpgradeClaim',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('qualified_referrals', models.PositiveIntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('from_plan', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='upgrade_claims_from', to='hbl_core.membershipplan')),
                ('to_plan', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='upgrade_claims_to', to='hbl_core.membershipplan')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='hbl_referral_upgrade_claims', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.AddConstraint(
            model_name='referralupgradeclaim',
            constraint=models.UniqueConstraint(fields=('user', 'to_plan'), name='uniq_hbl_referral_upgrade_user_toplan'),
        ),
    ]
