from django.db import migrations


def clear_legacy_plan_track_links(apps, schema_editor):
    Track = apps.get_model("hbl_core", "Track")
    through = Track.allowed_plans.through
    through.objects.all().delete()


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("hbl_core", "0016_withdrawals_trc20_bep20_only"),
    ]

    operations = [
        migrations.RunPython(clear_legacy_plan_track_links, noop_reverse),
    ]
