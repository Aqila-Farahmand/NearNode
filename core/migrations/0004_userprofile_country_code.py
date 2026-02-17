# Generated manually for UserProfile country_code

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_tripoption_saved_at_tripoption_saved_by_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='country_code',
            field=models.CharField(
                blank=True,
                help_text='ISO 3166-1 alpha-2 country code (e.g. US, GB)',
                max_length=2,
            ),
        ),
    ]
