"""
Django management command to help set up Google OAuth
"""
from django.core.management.base import BaseCommand
from django.contrib.sites.models import Site
from allauth.socialaccount.models import SocialApp
from allauth.socialaccount.providers.google.provider import GoogleProvider


class Command(BaseCommand):
    help = 'Set up Google OAuth configuration'

    def add_arguments(self, parser):
        parser.add_argument(
            '--client-id',
            type=str,
            help='Google OAuth Client ID',
        )
        parser.add_argument(
            '--client-secret',
            type=str,
            help='Google OAuth Client Secret',
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Setting up Google OAuth...'))

        # Check/Update Site
        site, _ = Site.objects.get_or_create(pk=1)
        if site.domain != 'localhost:8000':
            self.stdout.write(
                f'Updating site domain from "{site.domain}" to "localhost:8000"')
            site.domain = 'localhost:8000'
            site.name = 'NearNode Development'
            site.save()
            self.stdout.write(self.style.SUCCESS('✓ Site updated'))
        else:
            self.stdout.write(self.style.SUCCESS(
                '✓ Site already configured correctly'))

        # Check/Create Social Application
        try:
            social_app = SocialApp.objects.get(provider='google')
            self.stdout.write(self.style.WARNING(
                'Google Social Application already exists'))
            self.stdout.write(
                f'  Current Client ID: {social_app.client_id[:20]}...')

            if options.get('client_id') and options.get('client_secret'):
                social_app.client_id = options['client_id']
                social_app.secret = options['client_secret']
                social_app.save()
                self.stdout.write(self.style.SUCCESS(
                    '✓ Social Application updated with new credentials'))
            else:
                self.stdout.write(self.style.WARNING(
                    '  Use --client-id and --client-secret to update'))
        except SocialApp.DoesNotExist:
            if not options.get('client_id') or not options.get('client_secret'):
                self.stdout.write(self.style.ERROR(
                    'ERROR: Google Social Application not found!\n'
                    'You need to either:\n'
                    '1. Run this command with --client-id and --client-secret\n'
                    '2. Or configure it manually in Django Admin at /admin/socialaccount/socialapp/'
                ))
                return

            social_app = SocialApp.objects.create(
                provider='google',
                name='Google',
                client_id=options['client_id'],
                secret=options['client_secret'],
            )
            social_app.sites.add(site)
            self.stdout.write(self.style.SUCCESS(
                '✓ Social Application created'))

        # Verify configuration
        self.stdout.write('\n' + '='*60)
        self.stdout.write('Configuration Summary:')
        self.stdout.write('='*60)
        self.stdout.write(f'Site Domain: {site.domain}')
        self.stdout.write(f'Site Name: {site.name}')
        self.stdout.write(f'Social App Provider: {social_app.provider}')
        self.stdout.write(f'Social App Name: {social_app.name}')
        self.stdout.write(
            f'Social App Client ID: {social_app.client_id[:30]}...')
        self.stdout.write(
            f'Social App Sites: {", ".join([s.domain for s in social_app.sites.all()])}')
        self.stdout.write('\n' + '='*60)
        self.stdout.write(self.style.SUCCESS('Setup complete!'))
        self.stdout.write(
            '\nMake sure in Google Cloud Console you have BOTH redirect URIs:')
        self.stdout.write(
            '  - http://localhost:8000/accounts/google/login/callback/')
        self.stdout.write(
            '  - http://127.0.0.1:8000/accounts/google/login/callback/')
        self.stdout.write('\n(Add both because browsers may use either one)')
