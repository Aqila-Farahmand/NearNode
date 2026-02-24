"""
Test if the configured Ollama (or other AI Search LLM) is reachable.

Run: python manage.py test_ollama

Sends a simple "Reply with exactly: hi" and prints the response or error.
Use this to verify Ollama is running and AI_SEARCH_LLM_BACKEND=ollama is set.
"""
from django.core.management.base import BaseCommand
from django.conf import settings

from api.services import AISearchService


class Command(BaseCommand):
    help = 'Test AI Search LLM (e.g. Ollama): send "hi" and print response or error'

    def handle(self, *args, **options):
        backend = getattr(settings, 'AI_SEARCH_LLM_BACKEND', None) or ''
        backend = (backend or '').strip().lower()
        self.stdout.write('AI_SEARCH_LLM_BACKEND = %r' %
                          (backend or '(not set)'))

        client, model = AISearchService._get_llm_client_and_model()
        if client is None:
            self.stdout.write(self.style.WARNING(
                'No LLM client configured. For Ollama: set AI_SEARCH_LLM_BACKEND=ollama in .env and restart.'
            ))
            return

        self.stdout.write('Using model: %s' % model)
        self.stdout.write('Sending: "Reply with exactly: hi" ...')

        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {'role': 'user', 'content': 'Reply with exactly: hi'}],
                temperature=0,
                timeout=30.0,
            )
            raw = response.choices[0].message.content if response.choices else None
            if raw is not None:
                self.stdout.write(self.style.SUCCESS('Response: %r' % raw))
                self.stdout.write(
                    'Ollama / AI Search LLM is set up correctly.')
            else:
                self.stdout.write(self.style.WARNING(
                    'Empty response from model.'))
        except Exception as e:
            self.stderr.write(self.style.ERROR('Error: %s' % e))
            self.stderr.write(
                'Check: Ollama running and .env has OLLAMA_BASE_URL and AI_SEARCH_OLLAMA_MODEL set.')
