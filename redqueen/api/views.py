from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from cases import services
from cases.models import Intake, SuspectProfile
from precog import compstat
from precog.models import RiskAssessment
from precog.risk import assess_person
from registry.models import Person
from vision.engines import EngineError
from vision.media import MediaError, infer_media_type

from . import serializers


def require(perm):
    return type(f'Require_{perm}', (permissions.IsAuthenticated,), {
        'has_permission': lambda self, request, view: (
            request.user.is_authenticated and request.user.has_perm(perm)),
    })


class IntakeViewSet(viewsets.ModelViewSet):
    """Submit a photo or video (POST multipart: media, precinct). Every face is identified; each identified
    person with a record gets a suspect profile. The pipeline runs immediately."""

    queryset = Intake.objects.prefetch_related('faces__person', 'profiles__person', 'profiles__face_match')
    serializer_class = serializers.IntakeSerializer
    parser_classes = [MultiPartParser, FormParser]
    http_method_names = ['get', 'post', 'head', 'options']

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            media_type = serializer.validated_data.get('media_type') or infer_media_type(
                serializer.validated_data['media'].name)
            intake = serializer.save(submitted_by=request.user, media_type=media_type)
            services.process_intake(intake)
        except (MediaError, services.PipelineError) as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except EngineError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        intake.refresh_from_db()
        return Response(self.get_serializer(intake).data, status=status.HTTP_201_CREATED)


class ProfileViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = SuspectProfile.objects.select_related('person', 'intake')
    serializer_class = serializers.ProfileSerializer

    @action(detail=True, methods=['post'], permission_classes=[require('cases.review_profile')],
            serializer_class=serializers.ReviewSerializer)
    def review(self, request, pk=None):
        """Human validation: approve (VALIDATED) or reject (REJECTED) a profile."""
        profile = self.get_object()
        data = serializers.ReviewSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            services.review_profile(profile, request.user, **data.validated_data)
        except services.PipelineError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response(serializers.ProfileSerializer(profile).data)

    @action(detail=True, methods=['post'], permission_classes=[require('cases.adjudicate')],
            serializer_class=serializers.JudgmentInputSerializer)
    def judgment(self, request, pk=None):
        """Apply a conviction (optional) and a sentence to one open infraction of a validated profile."""
        profile = self.get_object()
        data = serializers.JudgmentInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        infraction = values.pop('infraction')
        try:
            judgment = services.apply_judgment(profile, infraction, request.user, **values)
        except services.PipelineError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response(serializers.JudgmentSerializer(judgment).data, status=status.HTTP_201_CREATED)


class PersonRiskView(APIView):
    """Latest risk assessment for a person (?refresh=1 recomputes it)."""

    def get(self, request, person_id):
        try:
            person = Person.objects.get(pk=person_id)
        except Person.DoesNotExist:
            raise NotFound('Unknown person')
        if not person.has_conviction_or_fine():
            return Response({'detail': 'No conviction or fine on record; risk assessment not applicable.'},
                            status=status.HTTP_404_NOT_FOUND)
        assessment = None if request.query_params.get('refresh') else person.risk_assessments.first()
        assessment = assessment or assess_person(person)
        return Response(serializers.RiskSerializer(assessment).data)


class CompstatView(APIView):
    """COMPSTAT report over the last `days` (default 28) compared with the period before."""

    def get(self, request):
        try:
            days = int(request.query_params.get('days', 28))
            if not 1 <= days <= 365:
                raise ValueError
        except ValueError:
            return Response({'detail': 'days must be an integer between 1 and 365'},
                            status=status.HTTP_400_BAD_REQUEST)
        return Response(compstat.report(days=days))
