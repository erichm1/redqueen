import mimetypes
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.models import Permission
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.db.models import Sum
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render, resolve_url
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme, urlencode
from django.views.decorators.http import require_POST

from cases import services
from cases.models import AuditEvent, FaceMatch, Intake, Judgment, SuspectProfile
from precog import compstat
from precog.risk import ADVISORY, assess_person
from registry.demo import SCENARIOS
from registry.models import FaceTemplate, Infraction, Penalty, Person
from vision.annotate import crop_face, encode_jpeg
from django.conf import settings
from vision.engines import EngineError
from vision.media import MediaError, infer_media_type, load_frames

from .forms import EnrollForm, IntakeForm, JudgmentForm, ProfileForm, ReviewForm


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
    form = IntakeForm(request.POST or None, request.FILES or None,
                      initial={'captured_at': timezone.localtime().replace(second=0, microsecond=0)})
    known_precincts = (
        Infraction.objects.exclude(precinct='').order_by('precinct').values_list('precinct', flat=True).distinct()
    )
    known_places = Infraction.objects.exclude(location='').order_by('location').values_list('location', flat=True).distinct()
    if request.method == 'POST' and form.is_valid():
        upload = form.cleaned_data['media']
        try:
            data = form.cleaned_data
            intake = Intake(media_type=infer_media_type(upload.name), captured_at=data['captured_at'],
                            precinct=data['precinct'], location=data['location'], latitude=data['latitude'],
                            longitude=data['longitude'], submitted_by=request.user)
            intake.media.save(upload.name, upload, save=False)
            intake = services.process_intake(intake)
        except (MediaError, services.PipelineError) as exc:
            form.add_error('media', str(exc))
        except EngineError as exc:
            form.add_error(None, f'Face engine unavailable: {exc}')
        else:
            return redirect('intake-detail', pk=intake.pk)
    return render(request, 'web/intake_form.html', {
        'form': form, 'precincts': known_precincts, 'places': known_places,
        'synthetic': settings.REDQUEEN['VISION_ENGINE'] == 'synthetic'})


@login_required
def intake_list(request):
    intakes = Intake.objects.order_by('-captured_at', '-id').annotate(
        n_identified=Count('faces__person', filter=Q(faces__status='matched'), distinct=True),
        n_profiles=Count('profiles', distinct=True),
        n_occurrences=Count('related_occurrences', distinct=True))
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


def individuals_involved(intake, rows):
    """The distinct people identified in an intake (with their best face match) and how many faces stayed unknown."""
    people = {}
    for row in rows:
        face = row['face']
        if face.status != 'matched' or face.person_id is None:
            continue
        entry = people.setdefault(face.person_id, {'person': face.person, 'faces': [], 'best': face, 'profile': row['profile']})
        entry['faces'].append(face.index)
        if face.score is not None and face.score > (entry['best'].score or -1):
            entry['best'] = face
        entry['profile'] = entry['profile'] or row['profile']
    for entry in people.values():
        person = entry['person']
        entry['photo'] = person.templates.exclude(photo='').order_by('created_at', 'id').first()
        entry['occurrences'] = person.infractions.count()
        entry['open'] = person.infractions.filter(status=Infraction.Status.OPEN).count()
    unknown = sum(1 for row in rows if row['face'].status != 'matched')
    return sorted(people.values(), key=lambda e: e['faces'][0]), unknown


def occurrences_by_person(intake):
    grouped = {}
    for inf in (intake.related_occurrences.select_related('person').prefetch_related('penalties')
                .order_by('person__full_name', '-occurred_at')):
        grouped.setdefault(inf.person, []).append(inf)
    return list(grouped.items())


@login_required
def intake_detail(request, pk):
    intake = get_object_or_404(Intake.objects.select_related('submitted_by'), pk=pk)
    rows = face_rows(intake)
    individuals, unknown = individuals_involved(intake, rows)
    occurrences = occurrences_by_person(intake)
    return render(request, 'web/intake_detail.html', {
        'intake': intake, 'rows': rows, 'profiles': intake.profiles.select_related('person'),
        'identified': len(individuals), 'individuals': individuals, 'unknown_faces': unknown,
        'occurrences': occurrences, 'occurrence_count': sum(len(v) for _, v in occurrences),
        'open_occurrences': sum(1 for _, v in occurrences for i in v if i.status == Infraction.Status.OPEN),
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


@login_required
def intake_face_crop(request, pk, index):
    """The face at `index` in an intake, cropped from the original media (not stored separately)."""
    face = get_object_or_404(FaceMatch.objects.select_related('intake'), intake_id=pk, index=index)
    if face.box is None:
        raise Http404
    try:
        frames = load_frames(face.intake.media.path, face.intake.media_type)
        crop = crop_face(frames[face.frame_index], face.box)
    except (FileNotFoundError, ValueError, MediaError, IndexError):
        raise Http404
    response = HttpResponse(encode_jpeg(crop), content_type='image/jpeg')
    response['Cache-Control'] = 'private, max-age=3600'
    return response


@login_required
def person_photo(request, pk, template_pk):
    """A registered face photo (private: only for logged-in users)."""
    template = get_object_or_404(FaceTemplate, pk=template_pk, person_id=pk)
    return _serve(template.photo)


# ----------------------------------------------------------------- profiles

@login_required
def profile_list(request):
    status = request.GET.get('status', '')
    profiles = SuspectProfile.objects.select_related('person', 'intake')
    if status in SuspectProfile.Status.values:
        profiles = profiles.filter(status=status)
    return render(request, 'web/profile_list.html', {
        'page': _page(request, profiles), 'status': status, 'statuses': SuspectProfile.Status.choices})


def sanctions_summary(person):
    """Totals over the person's whole record."""
    infractions = person.infractions.all()
    penalties = Penalty.objects.filter(infraction__person=person)

    def total(kind, field, **extra):
        return penalties.filter(kind=kind, **extra).aggregate(t=Sum(field))['t'] or 0

    Status = Penalty.Status
    return {
        'infractions': infractions.count(),
        'open': infractions.filter(status=Infraction.Status.OPEN).count(),
        'convictions': infractions.filter(convicted=True).count(),
        'first': infractions.order_by('occurred_at').first(),
        'last': infractions.order_by('-occurred_at').first(),
        'fines_total': total(Penalty.Kind.FINE, 'amount'),
        'fines_outstanding': total(Penalty.Kind.FINE, 'amount', status__in=[Status.PENDING, Status.DEFAULTED]),
        'service_hours': total(Penalty.Kind.COMMUNITY_SERVICE, 'hours'),
        'service_hours_done': total(Penalty.Kind.COMMUNITY_SERVICE, 'hours', status=Status.COMPLETED),
        'probation_months': total(Penalty.Kind.PROBATION, 'months'),
        'prison_months': total(Penalty.Kind.IMPRISONMENT, 'months'),
        'pending': penalties.filter(status=Status.PENDING).count(),
        'defaulted': penalties.filter(status=Status.DEFAULTED).count(),
        'by_category': list(infractions.values_list('category').annotate(n=Count('id')).order_by('-n', 'category')),
    }


def subject_context(person):
    """What the identity card needs: the registered photos and how many templates lack one."""
    templates = list(person.templates.order_by('created_at', 'id'))
    return {
        'person': person,
        'photos': [t for t in templates if t.photo],
        'templates_count': len(templates),
        'templates_without_photo': sum(1 for t in templates if not t.photo),
    }


def _profile_context(request, profile, judgment_form=None):
    recs = services.recommendations(profile) if profile.status == SuspectProfile.Status.VALIDATED else []
    infractions = {i['id']: i for i in profile.snapshot['infractions']}
    for rec in recs:
        rec['infraction'] = infractions.get(rec['infraction_id'])
    person = profile.person
    live = services.record_snapshot(person)
    face = profile.face_match
    can_audit = request.user.has_perm('cases.view_auditevent')
    return {
        **subject_context(person),
        'profile': profile,
        'infractions': live['infractions'],
        'timeline': timeline(live['infractions']),
        'snapshot_infractions': profile.snapshot['infractions'],
        'sanctions': sanctions_summary(person),
        'other_appearances': person.face_matches.select_related('intake').exclude(pk=face.pk if face else None)
                                 .order_by('-intake__created_at')[:12],
        'other_profiles': person.profiles.exclude(pk=profile.pk).order_by('-created_at'),
        'events': (AuditEvent.objects.select_related('actor').filter(
                       Q(target=f'profile:{profile.pk}') | Q(target=f'person:{person.pk}') | Q(detail__person=person.pk)
                   ).order_by('-created_at', '-id')[:25]) if can_audit else None,
        'face_has_crop': bool(face and face.box is not None and profile.intake_id),
        'recommendations': recs,
        'risk': risk_context(profile.person),
        'judgment_form': judgment_form or JudgmentForm(person=profile.person),
        'review_form': ReviewForm(),
        'can_review': request.user.has_perm('cases.review_profile'),
        'can_adjudicate': request.user.has_perm('cases.adjudicate'),
        'judgments': profile.judgments.select_related('infraction', 'decided_by'),
        'face': face,
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
        **subject_context(person),
        'sanctions': sanctions_summary(person),
        'infractions': snapshot['infractions'], 'timeline': timeline(snapshot['infractions']),
        'risk': risk_context(person), 'profiles': person.profiles.select_related('intake'),
        'appearances': person.face_matches.select_related('intake').order_by('-intake__created_at')[:20],
        'can_delete': request.user.has_perm('registry.delete_person')})


def scenario_previews():
    """What each dummy record scenario will attach, for the enrolment page."""
    previews = []
    for key, (label, records) in SCENARIOS.items():
        rows = [{'days_ago': days, 'category': category, 'severity': severity, 'convicted': convicted,
                 'open': not closed, 'penalty': penalty}
                for days, category, severity, convicted, closed, penalty in records]
        previews.append({'key': key, 'label': label, 'rows': rows, 'count': len(rows)})
    return previews


@login_required
@permission_required('registry.add_person', raise_exception=True)
def person_enroll(request):
    form = EnrollForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data
        try:
            person = services.enroll_person(
                request.user, data['full_name'], data['date_of_birth'],
                [p.read() for p in data['photos']], data['scenario'], data['gender'], data['age_range'])
        except services.EnrollmentError as exc:
            form.add_error(None, str(exc))
        except EngineError as exc:
            form.add_error(None, f'Face engine unavailable: {exc}')
        else:
            messages.success(request, f'{person.full_name} enrolled. Try a new intake with the webcam.')
            return redirect('person-detail', pk=person.pk)
    return render(request, 'web/person_enroll.html', {
        'form': form, 'max_photos': EnrollForm.MAX_PHOTOS, 'previews': scenario_previews(),
        'selected_scenario': form['scenario'].value() or 'escalating', 'now': timezone.now(),
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


# ------------------------------------------------------------ my profile

# Only RedQueen's own apps (plus auth, for users/groups) are worth listing: the full Permission
# table also holds Django's internal admin/session/contenttype models.
RELEVANT_APP_LABELS = ('registry', 'cases', 'precog', 'auth')


def permission_overview(user):
    """Every relevant permission with whether this user has it, and whether it was granted directly
    (rather than through a group)."""
    granted = user.get_all_permissions()
    direct = {f'{app}.{code}' for app, code in user.user_permissions.values_list('content_type__app_label', 'codename')}
    rows = []
    for perm in (Permission.objects.filter(content_type__app_label__in=RELEVANT_APP_LABELS)
                 .select_related('content_type').order_by('content_type__app_label', 'content_type__model', 'codename')):
        key = f'{perm.content_type.app_label}.{perm.codename}'
        rows.append({'label': str(perm).replace('Authentication and Authorization', 'Auth'),
                     'granted': user.is_superuser or key in granted, 'direct': key in direct})
    rows.sort(key=lambda r: not r['granted'])  # what you have first (stable: keeps the app/model order within each group)
    return rows


def activity_summary(user):
    return {
        'intakes': Intake.objects.filter(submitted_by=user).count(),
        'reviews': SuspectProfile.objects.filter(reviewed_by=user).count(),
        'judgments': Judgment.objects.filter(decided_by=user).count(),
        'enrolled': AuditEvent.objects.filter(actor=user, action='person.enrolled').count(),
        'logins': AuditEvent.objects.filter(actor=user, action='user.login').count(),
    }


@login_required
def my_profile(request):
    User = get_user_model()
    # The form mutates the instance it is given, even when validation fails, so it gets its own copy and
    # the page always shows what is actually saved.
    form = ProfileForm(request.POST or None, instance=User.objects.get(pk=request.user.pk))
    user = User.objects.get(pk=request.user.pk)
    if request.method == 'POST' and form.is_valid():
        if form.has_changed():
            form.save()
            services.audit(user, 'user.profile_updated', f'user:{user.pk}', changed=form.changed_data)
            messages.success(request, 'Profile updated.')
        else:
            messages.info(request, 'Nothing to change.')
        return redirect('my-profile')

    permissions = permission_overview(user)
    return render(request, 'web/account.html', {
        'account': user, 'form': form,
        'groups': user.groups.order_by('name'),
        'permissions': permissions,
        'permissions_granted': sum(1 for p in permissions if p['granted']),
        'activity': activity_summary(user),
        'events': AuditEvent.objects.filter(actor=user).order_by('-created_at', '-id')[:10],
        'capabilities': [
            ('Review and validate suspect profiles', user.has_perm('cases.review_profile')),
            ('Apply convictions and sentences', user.has_perm('cases.adjudicate')),
            ('Enroll people', user.has_perm('registry.add_person')),
            ('Erase people and their face data', user.has_perm('registry.delete_person')),
            ('Read the audit log', user.has_perm('cases.view_auditevent')),
        ],
    })


# ------------------------------------------------------------------ sign-in portal

class PortalLoginView(auth_views.LoginView):
    """Sign in, then pass through the hellgate portal on the way to the requested page (or the home page)."""

    def get_success_url(self):
        target = self.get_redirect_url() or resolve_url(settings.LOGIN_REDIRECT_URL)   # get_redirect_url() only returns safe URLs
        return f"{reverse('portal')}?{urlencode({'next': target})}"


def safe_destination(request, candidate):
    """The page to open after the portal: the requested one if it is on this site, otherwise the home page."""
    portal_path = reverse('portal')
    if (candidate and not candidate.startswith(portal_path)
            and url_has_allowed_host_and_scheme(candidate, allowed_hosts={request.get_host()}, require_https=request.is_secure())):
        return candidate
    return resolve_url(settings.LOGIN_REDIRECT_URL)


@login_required
def portal(request):
    """A few seconds of demonic gate animation with an "Accessing..." message, then the app opens.

    The delay is purely visual: the user is already signed in when they get here."""
    seconds = settings.REDQUEEN['PORTAL_DELAY_SECONDS']
    return render(request, 'web/portal.html', {
        'destination': safe_destination(request, request.GET.get('next', '')),
        'delay': seconds, 'delay_ms': int(seconds * 1000),
        'name': request.user.get_full_name() or request.user.get_username()})
