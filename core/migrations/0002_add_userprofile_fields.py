# Generated manually to add missing UserProfile fields

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='first_name',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='last_name',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='email',
            field=models.EmailField(blank=True, max_length=254),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='phone_number',
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='home_airport',
            field=models.ForeignKey(blank=True, help_text="User's home airport", null=True,
                                    on_delete=django.db.models.deletion.SET_NULL, related_name='home_users', to='core.airport'),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='currency',
            field=models.CharField(choices=[('USD', 'US Dollar ($)'), ('EUR', 'Euro (€)'), ('GBP', 'British Pound (£)'), ('JPY', 'Japanese Yen (¥)'), ('CAD', 'Canadian Dollar (C$)'), (
                'AUD', 'Australian Dollar (A$)'), ('CHF', 'Swiss Franc (CHF)'), ('CNY', 'Chinese Yuan (¥)')], default='EUR', help_text='Preferred currency for price display', max_length=3),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='location_latitude',
            field=models.DecimalField(
                blank=True, decimal_places=6, max_digits=9, null=True),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='location_longitude',
            field=models.DecimalField(
                blank=True, decimal_places=6, max_digits=9, null=True),
        ),
    ]
