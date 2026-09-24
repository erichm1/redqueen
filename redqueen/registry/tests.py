from datetime import date, timedelta

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from .demographics import age_range_for
from .models import Infraction, Person


class AgeRangeTests(SimpleTestCase):
    today = date(2026, 9, 24)

    def test_bucket_boundaries(self):
        def bucket(years, extra_days=0):
            return age_range_for(date(2026 - years, 9, 24) - timedelta(days=extra_days), self.today)

        self.assertEqual([bucket(17), bucket(18), bucket(25), bucket(26), bucket(40), bucket(41), bucket(60), bucket(61)],
                         ['0-17', '18-25', '18-25', '26-40', '26-40', '41-60', '41-60', '60+'])
        self.assertEqual(bucket(18, extra_days=-1), '0-17')  # 17 until the birthday

    def test_unknown_or_future_dates_have_no_bucket(self):
        self.assertEqual(age_range_for(None, self.today), '')
        self.assertEqual(age_range_for(date(2030, 1, 1), self.today), '')


class PersonTests(TestCase):
    def test_uuid_is_generated_and_unique(self):
        a, b = Person.objects.create(full_name='A Doe'), Person.objects.create(full_name='B Doe')
        self.assertNotEqual(a.uuid, b.uuid)
        self.assertEqual(Person.objects.get(uuid=a.uuid), a)

    def test_age_range_is_derived_from_date_of_birth(self):
        person = Person.objects.create(full_name='C Doe', date_of_birth=date(1990, 1, 1))
        self.assertEqual(person.age_range, age_range_for(date(1990, 1, 1)))
        person = Person.objects.create(full_name='D Doe', date_of_birth='1950-05-05')  # ISO strings are accepted
        self.assertEqual((person.age_range, person.date_of_birth), ('60+', date(1950, 5, 5)))

    def test_age_range_can_be_set_by_hand_when_the_date_of_birth_is_unknown(self):
        person = Person.objects.create(full_name='E Doe', age_range='26-40', gender='female')
        person.refresh_from_db()
        self.assertEqual((person.age_range, person.gender, person.date_of_birth), ('26-40', 'female', None))

    def test_gender_is_optional(self):
        self.assertIsNone(Person.objects.create(full_name='F Doe').gender)

    def test_total_occurrences_follows_the_infractions(self):
        person = Person.objects.create(full_name='G Doe')
        make = lambda: Infraction.objects.create(person=person, category='theft', severity=2,
                                                 occurred_at=timezone.now())
        first, second = make(), make()
        person.refresh_from_db()
        self.assertEqual(person.total_occurrences, 2)
        first.delete()
        person.refresh_from_db()
        self.assertEqual(person.total_occurrences, 1)
        second.save()  # an update is not a new occurrence
        person.refresh_from_db()
        self.assertEqual(person.total_occurrences, 1)

    def test_deleting_a_person_with_infractions_is_clean(self):
        person = Person.objects.create(full_name='H Doe')
        Infraction.objects.create(person=person, category='theft', severity=2, occurred_at=timezone.now())
        person.delete()
        self.assertFalse(Infraction.objects.exists())
