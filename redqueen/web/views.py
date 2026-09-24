import mimetypes
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from cases import services
from cases.models import AuditEvent, FaceMatch, Intake, SuspectProfile
from precog import compstat
from precog.risk import ADVISORY, assess_person
from registry.models import Infraction, Person
from django.conf import settings
from vision.engines import EngineError
from vision.media import MediaError, infer_media_type

from .forms import EnrollForm, IntakeForm, JudgmentForm, ReviewForm


def _page(request, queryset, per_page=25):
    return Paginator(queryset, per_page).get_page(request.GET.get('page'))


def risk_context(person):
    """Latest stored assessment, or a fresh unsaved one. None when risk does not apply."""
    if not person.has_conviction_or_fine():
        return None
    stored = person.risk_assessments.first()
    if stored:
        return {
            'score': stored.score, 'level': stored.level, 'trajectory': stored.trajectory,
            'expected_severity': stored.expected_severity, 'votes': stored.votes,
            'minority_report': stored.minority_report or [], 'as_of': stored.created_at, 'advisory': ADVISORY,
        }
    result = assess_person(person, persist=False)
    return {
        'score': result.score, 'level': result.level, 'trajectory': result.trajectory,
        'expected_severity': result.expected_severity, 'votes': [vars(v) for v in result.votes],
        'minority_report': [vars(v) for v in result.minority_report], 'as_of': None, 'advisory': ADVISORY,
    }


def timeline(snapshot_infractions, width=560, height=120):
    """Severity-by-date bars for an inline SVG chart."""
    if not snapshot_infractions:
        return []
    step = width / len(snapshot_infractions)
    bars = []
    for n, item in enumerate(snapshot_infractions):
        bar_height = item['severity'] / 5 * (height - 24)
        bars.append({
            'x': round(n * step + step * 0.2, 1), 'width': round(step * 0.6, 1),
            'y': round(height - 16 - bar_height, 1), 'height': round(bar_height, 1),
            'label_x': round(n * step + step / 2, 1), 'label_y': height - 3,
            'date': item['occurred_at'][:7], 'category': item['category'],
            'severity': item['severity'], 'convicted': item['convicted'],
        })
    return bars


# ---------------------------------------------------------------- dashboard

@login_required
def dashboard(request):
    try:
        days = min(max(int(request.GET.get('days', 28)), 1), 365)
    except ValueError:
        days = 28
    report = compstat.report(days=days)
    rows = report['intelligence']['by_precinct']
    peak = max((r['incidents'] for r in rows), default=0) or 1
    for row in rows:
        row['bar_pct'] = round(row['incidents'] / peak * 100)
    categories = report['intelligence']['by_category']
    top = max(categories.values(), default=0) or 1
    return render(request, 'web/dashboard.html', {
        'report': report, 'days': days, 'day_options': (7, 28, 90, 365),
        'categories': [(name, n, round(n / top * 100)) for name, n in categories.items()],
    })


# ------------------------------------------------------------------- intake

@login_required
def intake_new(request):
    form = IntakeForm(request.POST or None, request.FILES or None)
    known_precincts = (
        Infraction.objects.exclude(precinct='').order_by('precinct').values_list('precinct', flat=True).distinct()
    )
    if request.method == 'POST' and form.is_valid():
        upload = form.cleaned_data['media']
        try:
            intake = Intake(media_type=infer_media_type(upload.name), precinct=form.cleaned_data['precinct'],
                            submitted_by=request.user)
            intake.media.save(upload.name, upload, save=False)
            intake = services.process_intake(intake)
        except (MediaError, services.PipelineError) as exc:
            form.add_error('media', str(exc))
        except EngineError as exc:
            form.add_error(None, f'Face engine unavailable: {exc}')
        else:
            return redirect('intake-detail', pk=intake.pk)
    return render(request, 'web/intake_form.html', {
        'form': form, 'precincts': known_precincts,
        'synthetic': settings.REDQUEEN['VISION_ENGINE'] == 'synthetic'})


@login_required
def intake_list(request):
    intakes = Intake.objects.order_by('-created_at', '-id').annotate(
        n_identified=Count('faces', filter=Q(faces__status='matched'), distinct=True),
        n_profiles=Count('profiles', distinct=True))
    return render(request, 'web/intake_list.html', {'page': _page(request, intakes)})


def face_rows(intake):
    """Faces of an intake with the numbers the template needs: percentages, closest people, profile."""
    profiles = {p.face_match_id: p for p in intake.profiles.all() if p.face_match_id}
    rows = []
    for face in intake.faces.select_related('person', 'candidate'):
        rows.append({
            'face': face,
            'profile': profiles.get(face.pk),
            'candidates': [{'name': c['name'], 'person_id': c['person_id'], 'pct': FaceMatch.pct(c['score'])}
                           for c in face.candidates],
        })
    return rows


@login_required
def intake_detail(request, pk):
    intake = get_object_or_404(Intake, pk=pk)
    rows = face_rows(intake)
    return render(request, 'web/intake_detail.html', {
        'intake': intake, 'rows': rows, 'profiles': intake.profiles.select_related('person'),
        'identified': sum(1 for r in rows if r['face'].status == 'matched'),
        'synthetic': intake.engine == 'synthetic'})


def _serve(field_file):
    try:
        handle = field_file.open('rb')
    except (FileNotFoundError, ValueError):
        raise Http404
    return FileResponse(handle, content_type=mimetypes.guess_type(field_file.name)[0] or 'application/octet-stream')


@login_required
def intake_media(request, pk):
    return _serve(get_object_or_404(Intake, pk=pk).media)


@login_required
def intake_annotated(request, pk):
    return _serve(get_object_or_404(Intake, pk=pk).annotated)


# ----------------------------------------------------------------- profiles

@login_required
def profile_list(request):
    status = request.GET.get('status', '')
    profiles = SuspectProfile.objects.select_related('person', 'intake')
    if status in SuspectProfile.Status.values:
        profiles = profiles.filter(status=status)
    return render(request, 'web/profile_list.html', {
        'page': _page(request, profiles), 'status': status, 'statuses': SuspectProfile.Status.choices})


def _profile_context(request, profile, judgment_form=None):
    recs = services.recommendations(profile) if profile.status == SuspectProfile.Status.VALIDATED else []
    infractions = {i['id']: i for i in profile.snapshot['infractions']}
    for rec in recs:
        rec['infraction'] = infractions.get(rec['infraction_id'])
    return {
        'profile': profile,
        'infractions': profile.snapshot['infractions'],
        'timeline': timeline(profile.snapshot['infractions']),
        'recommendations': recs,
        'risk': risk_context(profile.person),
        'judgment_form': judgment_form or JudgmentForm(person=profile.person),
        'review_form': ReviewForm(),
        'can_review': request.user.has_perm('cases.review_profile'),
        'can_adjudicate': request.user.has_perm('cases.adjudicate'),
        'judgments': profile.judgments.select_related('infraction', 'decided_by'),
        'face': profile.face_match,
        'candidates': [{'name': c['name'], 'pct': FaceMatch.pct(c['score'])}
                       for c in (profile.face_match.candidates if profile.face_match else [])],
    }


@login_required
def profile_detail(request, pk):
    profile = get_object_or_404(SuspectProfile.objects.select_related('person', 'intake', 'face_match'), pk=pk)
    return render(request, 'web/profile_detail.html', _profile_context(request, profile))


@login_required
@permission_required('cases.review_profile', raise_exception=True)
@require_POST
def profile_review(request, pk):
    profile = get_object_or_404(SuspectProfile, pk=pk)
    form = ReviewForm(request.POST)
    approve = request.POST.get('decision') == 'approve'
    if request.POST.get('decision') not in ('approve', 'reject') or not form.is_valid():
        messages.error(request, 'Choose approve or reject.')
        return redirect('profile-detail', pk=pk)
    try:
        services.review_profile(profile, request.user, approve, form.cleaned_data['notes'])
        messages.success(request, 'Profile validated.' if approve else 'Profile rejected.')
    except services.PipelineError as exc:
        messages.error(request, str(exc))
    return redirect('profile-detail', pk=pk)


@login_required
@permission_required('cases.adjudicate', raise_exception=True)
@require_POST
def profile_judgment(request, pk):
    profile = get_object_or_404(SuspectProfile.objects.select_related('person'), pk=pk)
    form = JudgmentForm(request.POST, person=profile.person)
    if not form.is_valid():
        return render(request, 'web/profile_detail.html', _profile_context(request, profile, form), status=400)
    data = form.cleaned_data
    try:
        services.apply_judgment(
            profile, data['infraction'], request.user, data['convicted'], data['sentence_kind'],
            amount=data['amount'], hours=data['hours'], months=data['months'], rationale=data['rationale'])
        messages.success(request, 'Judgment recorded and risk reassessed.')
    except services.PipelineError as exc:
        messages.error(request, str(exc))
    return redirect('profile-detail', pk=pk)


# ------------------------------------------------------------------- people

@login_required
def person_list(request):
    query = request.GET.get('q', '').strip()
    people = Person.objects.annotate(
        n_infractions=Count('infractions', distinct=True),
        n_open=Count('infractions', filter=Q(infractions__status='open'), distinct=True))
    if query:
        people = people.filter(full_name__icontains=query)
    return render(request, 'web/person_list.html', {
        'page': _page(request, people.order_by('full_name')), 'q': query,
        'can_enroll': request.user.has_perm('registry.add_person')})


@login_required
def person_detail(request, pk):
    person = get_object_or_404(Person, pk=pk)
    snapshot = services.record_snapshot(person)
    return render(request, 'web/person_detail.html', {
        'person': person, 'infractions': snapshot['infractions'], 'timeline': timeline(snapshot['infractions']),
        'risk': risk_context(person), 'profiles': person.profiles.select_related('intake'),
        'templates_count': person.templates.count(),
        'appearances': person.face_matches.select_related('intake').order_by('-intake__created_at')[:20],
        'can_delete': request.user.has_perm('registry.delete_person')})


@login_required
@permission_required('registry.add_person', raise_exception=True)
def person_enroll(request):
    form = EnrollForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data
        try:
            person = services.enroll_person(
                request.user, data['full_name'], data['date_of_birth'],
                [p.read() for p in data['photos']], data['scenario'], data['gender'])
        except services.EnrollmentError as exc:
            form.add_error(None, str(exc))
        except EngineError as exc:
            form.add_error(None, f'Face engine unavailable: {exc}')
        else:
            messages.success(request, f'{person.full_name} enrolled. Try a new intake with the webcam.')
            return redirect('person-detail', pk=person.pk)
    return render(request, 'web/person_enroll.html', {
        'form': form, 'max_photos': EnrollForm.MAX_PHOTOS,
        'synthetic': settings.REDQUEEN['VISION_ENGINE'] == 'synthetic'})


@login_required
@permission_required('registry.delete_person', raise_exception=True)
@require_POST
def person_delete(request, pk):
    person = get_object_or_404(Person, pk=pk)
    name = person.full_name
    services.delete_person(request.user, person)
    messages.success(request, f'{name} and all associated face data, records and intake media were erased.')
    return redirect('person-list')


# -------------------------------------------------------------------- audit

@login_required
@permission_required('cases.view_auditevent', raise_exception=True)
def audit_log(request):
    events = AuditEvent.objects.select_related('actor').order_by('-created_at', '-id')
    action = request.GET.get('action', '')
    if action:
        events = events.filter(action=action)
    return render(request, 'web/audit.html', {
        'page': _page(request, events, 50), 'action': action,
        'actions': AuditEvent.objects.order_by().values_list('action', flat=True).distinct()})
