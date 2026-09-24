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


class IntakeSerializer(serializers.ModelSerializer):
    faces = FaceMatchSerializer(many=True, read_only=True)
    profiles = ProfileSerializer(many=True, read_only=True)
    threshold_pct = serializers.FloatField(read_only=True)

    class Meta:
        model = Intake
        fields = ['id', 'media', 'media_type', 'precinct', 'status', 'engine', 'faces_detected', 'threshold_pct',
                  'created_at', 'faces', 'profiles']
        read_only_fields = ['status', 'engine', 'faces_detected', 'created_at']
        extra_kwargs = {'media_type': {'required': False}}


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
