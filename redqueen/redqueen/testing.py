"""Shared test fixtures: synthetic engine, throw-away media dir, seeded dummy people."""
import io
import shutil
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.test import TestCase, override_settings


class DummyWorldTestCase(TestCase):
    bulk = 0

    @classmethod
    def setUpClass(cls):
        cls._media = Path(tempfile.mkdtemp())
        cls._override = override_settings(
            MEDIA_ROOT=cls._media, REDQUEEN={**settings.REDQUEEN, 'VISION_ENGINE': 'synthetic'})
        cls._override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._override.disable()
        shutil.rmtree(cls._media, ignore_errors=True)

    @classmethod
    def setUpTestData(cls):
        call_command('seed_dummy_data', bulk=cls.bulk, stdout=io.StringIO())

    @property
    def probes(self):
        return self._media / 'dummy'
