from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0005_tripoption_display_data'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='preferred_language',
            field=models.CharField(
                choices=[
                    ('en', 'English'),
                    ('fr', 'French'),
                    ('de', 'German'),
                    ('es', 'Spanish'),
                    ('it', 'Italian'),
                    ('pt', 'Portuguese'),
                    ('nl', 'Dutch'),
                    ('ar', 'Arabic'),
                    ('zh', 'Chinese (Simplified)'),
                    ('ja', 'Japanese'),
                    ('ko', 'Korean'),
                    ('hi', 'Hindi'),
                ],
                default='en',
                help_text='Preferred UI language code',
                max_length=5,
            ),
        ),
    ]
