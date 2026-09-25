"""Populate the database with dummy people, records and probe media. Nobody here is real."""
import random
from datetime import date, timedelta

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.utils import timezone

from registry.demo import PRECINCTS, create_records, place_for
from registry.models import FaceTemplate, Infraction, Person
from vision.annotate import encode_jpeg
from vision.dummy import make_portrait, write_group_photo, write_photo, write_video
from vision.engines import get_engine

C = Infraction.Category
PEOPLE = {  # name: (birth year, scenario, gender)
    'John Doe': (1988, 'escalating', 'male'),
    'Jane Doe': (1991, 'minor', 'female'),
    'Susan Doe': (1985, 'clean', 'female'),
    'Mark Doe': (1979, 'desisting', 'male'),
}


class Command(BaseCommand):
    help = 'Create dummy people (John/Jane/Susan/Mark Doe), records, face templates and probe media.'

    def add_arguments(self, parser):
        parser.add_argument('--bulk', type=int, default=40, help='extra background infractions for COMPSTAT stats')
        parser.add_argument('--users', action='store_true',
                            help="create dev logins: 'officer' (view + intake) and 'judge' (can also review and "
                                 "adjudicate), both with password 'redqueen-demo'")
        parser.add_argument('--reset', action='store_true', help='delete existing people and records first')

    def handle(self, *args, bulk, reset, users, **options):
        if reset:
            Person.objects.all().delete()
        now = timezone.now()
        engine = get_engine('synthetic')  # dummy portraits are only meaningful to the synthetic engine
        probe_dir = settings.MEDIA_ROOT / 'dummy'
        probe_dir.mkdir(parents=True, exist_ok=True)

        for name, (year, scenario, gender) in PEOPLE.items():
            person, _ = Person.objects.get_or_create(
                full_name=name, defaults={'date_of_birth': date(year, 6, 15), 'gender': gender})
            portrait = make_portrait(name)
            if not person.templates.exists():
                embedding = engine.embed(portrait)[0]
                FaceTemplate.objects.create(person=person, engine=engine.name,
                                            embedding=embedding.tolist(), source='seed')
            for template in person.templates.filter(photo=''):  # also backfills templates seeded before photos existed
                template.photo.save(f'seed-{person.uuid}.jpg', ContentFile(encode_jpeg(portrait)), save=True)
            if not person.infractions.exists():
                create_records(person, scenario, now)
            slug = name.split()[0].lower()
            write_photo(name, probe_dir / f'{slug}.png', variant=1)
            write_video(name, probe_dir / f'{slug}.avi')
        write_photo('Unknown Stranger', probe_dir / 'stranger.png', variant=1)
        # group photo: three people with records, one clean, one stranger (synthetic engine reads one face per tile)
        write_group_photo(['John Doe', 'Susan Doe', 'Unknown Stranger', 'Jane Doe', 'Mark Doe'], probe_dir / 'group.png')

        rng = random.Random(42)
        categories = list(C)
        for n in range(bulk):
            person, _ = Person.objects.get_or_create(full_name=f'Background Doe {n % 12:02d}')
            category = rng.choice(categories)
            precinct = rng.choice(PRECINCTS[:3] if rng.random() < 0.7 else PRECINCTS)
            Infraction.objects.create(
                person=person, category=category, severity=rng.randint(1, 4),
                occurred_at=now - timedelta(days=rng.randint(1, 56), hours=rng.randint(0, 23), minutes=rng.randint(0, 59)),
                precinct=precinct, location=place_for(precinct, rng.random()),
                description='Dummy background record', status=Infraction.Status.CLOSED,
            )
        if users:
            self._create_users()
        self.stdout.write(self.style.SUCCESS(
            f'Seeded {Person.objects.count()} people, {Infraction.objects.count()} infractions. '
            f'Probe media in {probe_dir}'))

    def _create_users(self):
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Permission

        User = get_user_model()
        for username, codenames in (('officer', []), ('judge', ['review_profile', 'adjudicate', 'view_auditevent', 'add_person', 'delete_person'])):
            user, created = User.objects.get_or_create(username=username)
            if created:
                user.set_password('redqueen-demo')
                user.save()
            user.user_permissions.set(Permission.objects.filter(codename__in=codenames))
