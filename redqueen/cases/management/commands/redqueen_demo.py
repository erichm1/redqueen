"""Walk the dummy probe media through the whole pipeline and print what happens."""
import json

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError
from django.test import override_settings

from cases import services
from cases.models import Intake
from precog import compstat
from precog.risk import assess_person

PROBES = ['john.png', 'jane.png', 'susan.png', 'mark.avi', 'stranger.png', 'group.png']


class Command(BaseCommand):
    help = 'Run the dummy photos/videos through recognition, profiling, judgment and risk (needs seed_dummy_data).'

    def handle(self, *args, **options):
        probe_dir = settings.MEDIA_ROOT / 'dummy'
        if not probe_dir.exists():
            raise CommandError('Run `manage.py seed_dummy_data` first.')
        user, _ = get_user_model().objects.get_or_create(username='demo-officer')
        with override_settings(REDQUEEN={**settings.REDQUEEN, 'VISION_ENGINE': 'synthetic'}):
            for filename in PROBES:
                self.stdout.write(self.style.MIGRATE_HEADING(f'\n== {filename}'))
                with open(probe_dir / filename, 'rb') as handle:
                    intake = Intake(precinct='P-01 Harbor', submitted_by=user)
                    intake.media.save(f'demo-{filename}', File(handle), save=False)
                intake = services.process_intake(intake)
                self.stdout.write(f'intake: {intake.status}  faces: {intake.faces_detected}  '
                                  f'threshold: {intake.threshold_pct}%')
                for face in intake.faces.all():
                    who = face.person.full_name if face.person else '-'
                    pct = f'{face.similarity_pct}%' if face.score is not None else '-'
                    self.stdout.write(f'  face #{face.index}: {face.status:<9} {who:<22} similarity {pct}')
                if intake.annotated:
                    self.stdout.write(f'  boxes drawn on: {intake.annotated.path}')
                for profile in intake.profiles.select_related('person'):
                    self.stdout.write(f'  profile #{profile.pk} {profile.person.full_name}: {profile.status}  checks: '
                                      + ', '.join(f"{c['name']}={'ok' if c['passed'] else 'FAIL'}" for c in profile.checks))
                    if profile.status == 'needs_review':
                        services.review_profile(profile, user, approve=True, notes='demo auto-approve')
                    for rec in services.recommendations(profile):
                        self.stdout.write(f'    recommended: {json.dumps(rec)}')
                        infraction = profile.person.infractions.get(pk=rec['infraction_id'])
                        services.apply_judgment(
                            profile, infraction, user, rec['convicted'], rec['sentence_kind'],
                            amount=rec['amount'], hours=rec['hours'], months=rec['months'],
                            rationale='demo: guideline recommendation applied')
                    risk = assess_person(profile.person)
                    if risk:
                        self.stdout.write(f'    risk: {risk.level} ({risk.score}) trajectory={risk.trajectory} '
                                          f'expected_severity={risk.expected_severity}')
                        for dissent in risk.minority_report or []:
                            self.stdout.write(f"      minority report: {dissent['precog']} says {dissent['level']} "
                                              f"- {dissent['rationale']}")

        report = compstat.report()
        self.stdout.write(self.style.MIGRATE_HEADING('\n== COMPSTAT (28 days)'))
        intel = report['intelligence']
        self.stdout.write(f"incidents: {intel['total']} (previous {intel['previous_total']}, {intel['change_pct']}%)")
        for hotspot in report['tactics']:
            self.stdout.write(f"hot spot {hotspot['precinct']}: {hotspot['recommendation']}")
        self.stdout.write(f"deployment: {report['deployment']}")
        follow = report['follow_up']
        self.stdout.write(f"follow-up: {follow['open_infractions']} open, "
                          f"{[w['name'] for w in follow['high_risk_watchlist']]} on watchlist")
