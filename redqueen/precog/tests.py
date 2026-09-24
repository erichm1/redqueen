from datetime import timedelta

from django.utils import timezone

from redqueen.testing import DummyWorldTestCase
from registry.models import Person

from . import compstat
from .risk import assess_person, assess_records, level_for


class RiskTests(DummyWorldTestCase):
    def assess(self, name):
        return assess_person(Person.objects.get(full_name=name), persist=False)

    def test_escalating_history_is_higher_risk_and_more_severe(self):
        john, jane = self.assess('John Doe'), self.assess('Jane Doe')
        self.assertGreater(john.score, jane.score)
        self.assertEqual(john.level, 'high')
        self.assertEqual(jane.level, 'low')
        self.assertEqual(john.trajectory, 'more_severe')

    def test_desisting_history_is_less_severe(self):
        self.assertEqual(self.assess('Mark Doe').trajectory, 'less_severe')

    def test_no_conviction_or_fine_means_no_assessment(self):
        self.assertIsNone(assess_person(Person.objects.get(full_name='Susan Doe')))

    def test_persisted_assessment_stores_votes_and_minority_report(self):
        assessment = assess_person(Person.objects.get(full_name='Mark Doe'))
        self.assertEqual([v['precog'] for v in assessment.votes], ['agatha', 'arthur', 'dashiell'])
        consensus = assessment.level
        for dissent in assessment.minority_report or []:
            self.assertNotEqual(dissent['level'], consensus)

    def test_inputs_are_record_history_only(self):
        now = timezone.now()
        infractions = [{'occurred_at': now - timedelta(days=30), 'severity': 2, 'convicted': True}]
        result = assess_records(infractions, [], now)
        self.assertIn(result.level, ('low', 'moderate', 'high'))
        self.assertIsNone(assess_records([], [], now))

    def test_level_boundaries(self):
        self.assertEqual([level_for(x) for x in (0, 0.329, 0.33, 0.659, 0.66, 1)],
                         ['low', 'low', 'moderate', 'moderate', 'high', 'high'])


class CompstatTests(DummyWorldTestCase):
    bulk = 40

    def test_report_has_all_four_sections(self):
        for person in Person.objects.filter(full_name__in=['John Doe', 'Mark Doe']):
            assess_person(person)
        report = compstat.report(days=28)
        self.assertGreater(report['intelligence']['total'], 0)
        self.assertEqual(sum(report['intelligence']['by_category'].values()), report['intelligence']['total'])
        self.assertTrue(report['tactics'])
        self.assertAlmostEqual(sum(d['share_pct'] for d in report['deployment']), 100, delta=0.5)
        self.assertEqual([w['name'] for w in report['follow_up']['high_risk_watchlist']], ['John Doe'])
        self.assertEqual(report['follow_up']['defaulted_penalties'], 1)

    def test_previous_period_comparison(self):
        wide = compstat.report(days=365)
        self.assertEqual(wide['intelligence']['previous_total'], 2)  # John 640d ago, Jane 400d ago
        self.assertEqual(compstat._pct_change(3, 2), 50.0)
        self.assertEqual(compstat._pct_change(3, 0), 100.0)
        self.assertIsNone(compstat._pct_change(0, 0))
