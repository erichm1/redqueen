from datetime import timedelta

from django.utils import timezone
from rest_framework import serializers

from cases.models import FaceMatch, Intake, Judgment, SuspectProfile
from precog.models import RiskAssessment
from registry.models import Infraction, Penalty, Person


class PersonSerializer(serializers.ModelSerializer):
    """`id` is the person's public UUID. age_range is derived from date_of_birth when that is set."""

    id = serializers.UUIDField(source='uuid', read_only=True)

    class Meta:
        model = Person
        fields = ['id', 'full_name', 'date_of_birth', 'age_range', 'gender', 'total_occurrences', 'created_at']
        read_only_fields = ['total_occurrences', 'created_at']


class ProfileSerializer(serializers.ModelSerializer):
    person_name = serializers.CharField(source='person.full_name', read_only=True)
    similarity_pct = serializers.FloatField(source='face_match.similarity_pct', read_only=True, default=None)
    recommendations = serializers.SerializerMethodField()

    class Meta:
        model = SuspectProfile
        fields = ['id', 'intake', 'person', 'person_name', 'status', 'similarity_pct', 'snapshot', 'checks',
                  'reviewed_by', 'review_notes', 'reviewed_at', 'created_at', 'recommendations']

    def get_recommendations(self, profile):
        from cases.services import recommendations
        if profile.status != SuspectProfile.Status.VALIDATED:
            return []
        return recommendations(profile)


class FaceMatchSerializer(serializers.ModelSerializer):
    """One face found in the media. `similarity_pct` is cosine similarity x 100, not a probability."""

    person_name = serializers.CharField(source='person.full_name', read_only=True, default=None)
    box = serializers.SerializerMethodField()
    profile = serializers.SerializerMethodField()

    class Meta:
        model = FaceMatch
        fields = ['index', 'frame_index', 'box', 'status', 'person', 'person_name', 'similarity_pct',
                  'runner_up_pct', 'support', 'candidates', 'profile']

    def get_box(self, face):
        return dict(zip('xywh', face.box)) if face.box else None

    def get_profile(self, face):
        profile = getattr(face, 'profile', None)
        return profile.pk if profile else None


class OccurrenceSerializer(serializers.ModelSerializer):
    """One occurrence (infraction) with when and where it happened."""

    person = serializers.UUIDField(source='person.uuid', read_only=True)
    person_name = serializers.CharField(source='person.full_name', read_only=True)
    date = serializers.SerializerMethodField()
    time = serializers.SerializerMethodField()
    hour = serializers.SerializerMethodField()
    penalties = serializers.SerializerMethodField()

    class Meta:
        model = Infraction
        fields = ['id', 'person', 'person_name', 'category', 'severity', 'occurred_at', 'date', 'time', 'hour',
                  'precinct', 'location', 'status', 'convicted', 'penalties']

    def _local(self, obj):
        return timezone.localtime(obj.occurred_at)

    def get_date(self, obj):
        return self._local(obj).date().isoformat()

    def get_time(self, obj):
        return self._local(obj).strftime('%H:%M:%S')

    def get_hour(self, obj):
        return self._local(obj).hour

    def get_penalties(self, obj):
        return [{'kind': p.kind, 'amount': p.amount, 'hours': p.hours, 'months': p.months, 'status': p.status}
                for p in obj.penalties.all()]


class IntakeSerializer(serializers.ModelSerializer):
    """`captured_at` (defaults to now) is when the media was taken; `date`, `time` and `hour` are derived from it
    in the server time zone. `individuals` are the distinct people identified; `occurrences` all related records."""

    faces = FaceMatchSerializer(many=True, read_only=True)
    profiles = ProfileSerializer(many=True, read_only=True)
    threshold_pct = serializers.FloatField(read_only=True)
    date = serializers.SerializerMethodField()
    time = serializers.SerializerMethodField()
    hour = serializers.SerializerMethodField()
    individuals = serializers.SerializerMethodField()
    occurrences = OccurrenceSerializer(source='related_occurrences', many=True, read_only=True)

    class Meta:
        model = Intake
        fields = ['id', 'media', 'media_type', 'captured_at', 'date', 'time', 'hour', 'precinct', 'location',
                  'latitude', 'longitude', 'status', 'engine', 'faces_detected', 'threshold_pct', 'created_at',
                  'individuals', 'occurrences', 'faces', 'profiles']
        read_only_fields = ['status', 'engine', 'faces_detected', 'created_at']
        extra_kwargs = {'media_type': {'required': False}, 'captured_at': {'required': False}}

    def validate_captured_at(self, value):
        if value > timezone.now() + timedelta(minutes=5):
            raise serializers.ValidationError('The capture time cannot be in the future.')
        return value

    def validate(self, data):
        if (data.get('latitude') is None) != (data.get('longitude') is None):
            raise serializers.ValidationError('Give both latitude and longitude, or neither.')
        return data

    def _local(self, obj):
        return timezone.localtime(obj.captured_at)

    def get_date(self, obj):
        return self._local(obj).date().isoformat()

    def get_time(self, obj):
        return self._local(obj).strftime('%H:%M:%S')

    def get_hour(self, obj):
        return self._local(obj).hour

    def get_individuals(self, obj):
        people = {}
        for face in obj.faces.all():
            if face.status != 'matched' or face.person_id is None:
                continue
            entry = people.setdefault(face.person_id, {
                'id': str(face.person.uuid), 'name': face.person.full_name, 'age_range': face.person.age_range,
                'gender': face.person.gender, 'faces': [], 'similarity_pct': face.similarity_pct,
                'occurrences': face.person.infractions.count(), 'profile': None})
            entry['faces'].append(face.index)
            entry['similarity_pct'] = max(entry['similarity_pct'], face.similarity_pct)
        for profile in obj.profiles.all():
            if profile.person_id in people:
                people[profile.person_id]['profile'] = profile.pk
        unknown = sum(1 for f in obj.faces.all() if f.status != 'matched')
        return {'identified': list(people.values()), 'unidentified_faces': unknown}


class ReviewSerializer(serializers.Serializer):
    approve = serializers.BooleanField()
    notes = serializers.CharField(required=False, allow_blank=True, default='')


class JudgmentInputSerializer(serializers.Serializer):
    infraction = serializers.PrimaryKeyRelatedField(queryset=Infraction.objects.all())
    convicted = serializers.BooleanField(default=False)
    sentence_kind = serializers.ChoiceField(choices=Penalty.Kind.choices)
    amount = serializers.DecimalField(max_digits=10, decimal_places=2, required=False, allow_null=True)
    hours = serializers.IntegerField(min_value=0, required=False, allow_null=True)
    months = serializers.IntegerField(min_value=0, required=False, allow_null=True)
    rationale = serializers.CharField(required=False, allow_blank=True, default='')


class JudgmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Judgment
        fields = ['id', 'profile', 'infraction', 'convicted', 'sentence_kind', 'amount', 'hours',
                  'months', 'rationale', 'decided_by', 'decided_at']


class RiskSerializer(serializers.ModelSerializer):
    advisory = serializers.SerializerMethodField()

    class Meta:
        model = RiskAssessment
        fields = ['id', 'person', 'score', 'level', 'trajectory', 'expected_severity', 'votes',
                  'minority_report', 'created_at', 'advisory']

    def get_advisory(self, _):
        from precog.risk import ADVISORY
        return ADVISORY
