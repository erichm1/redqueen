"""The RedQueen pipeline.

    media -> face recognition -> record lookup -> suspect profile -> validation
          -> (human) conviction / sentence -> risk reassessment
"""
from collections import defaultdict
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from precog.risk import assess_person
from registry.demo import SCENARIOS, create_records
from registry.models import FaceTemplate, Infraction, Penalty, Person
from vision.annotate import draw, encode_jpeg
from vision.engines import get_engine
from vision.media import MediaError, infer_media_type
from vision.service import embed_image_bytes, existing_identity, recognize

from .models import AuditEvent, FaceMatch, Intake, Judgment, SuspectProfile
from .sentencing import recommend


class PipelineError(Exception):
    pass


def audit(actor, action, target, **detail):
    AuditEvent.objects.create(
        actor=actor if getattr(actor, 'pk', None) else None, action=action, target=target, detail=detail
    )


def record_snapshot(person: Person) -> dict:
    infractions = person.infractions.prefetch_related('penalties')
    return {
        'person': {'id': person.pk, 'full_name': person.full_name, 'date_of_birth': person.date_of_birth.isoformat() if person.date_of_birth else None},
        'infractions': [
            {
                'id': i.pk,
                'category': i.category,
                'severity': i.severity,
                'occurred_at': i.occurred_at.isoformat(),
                'precinct': i.precinct,
                'convicted': i.convicted,
                'status': i.status,
                'penalties': [
                    {'kind': p.kind, 'amount': str(p.amount) if p.amount is not None else None,
                     'hours': p.hours, 'months': p.months, 'status': p.status}
                    for p in i.penalties.all()
                ],
            }
            for i in infractions
        ],
    }


def validation_checks(face: FaceMatch, person: Person, threshold: float, faces_of_person: int) -> list[dict]:
    """Automated checks; any failure sends the profile to a human reviewer."""
    config = settings.REDQUEEN
    needed = threshold + config['AUTO_VALIDATE_EXTRA']
    margin = face.score - face.runner_up_score
    now = timezone.now()
    return [
        {
            'name': 'identity_confidence',
            'passed': face.score >= needed,
            'detail': f'similarity {face.similarity_pct}%, needs {needed * 100:.1f}%',
        },
        {
            'name': 'identity_margin',
            'passed': margin >= 2 * config['MATCH_MARGIN'],
            'detail': f'{margin * 100:.1f} points ahead of the next closest person',
        },
        {
            'name': 'unique_in_frame',
            'passed': faces_of_person == 1,
            'detail': f'matched to {faces_of_person} face(s) in this media',
        },
        {
            'name': 'record_consistency',
            'passed': not person.infractions.filter(occurred_at__gt=now).exists()
            and not Penalty.objects.filter(infraction__person=person, imposed_at__gt=now).exists(),
            'detail': 'no records dated in the future',
        },
    ]


@transaction.atomic
def process_intake(intake: Intake) -> Intake:
    """Recognise every face in an intake; each identified person with a record gets a suspect profile."""
    try:
        intake.media_type = intake.media_type or infer_media_type(intake.media.name)
        engine = get_engine()
        recognition = recognize(intake.media.path, intake.media_type)
    except MediaError as exc:
        raise PipelineError(str(exc)) from exc

    intake.engine = engine.name
    intake.faces_detected = recognition.faces_detected
    intake.match_threshold = recognition.threshold
    intake.save()

    results = recognition.results
    person_ids = {i for r in results for i in (r.person_id, r.candidate_id, *(c for c, _ in r.candidates)) if i}
    people = Person.objects.in_bulk(person_ids)
    with_record = set(Infraction.objects.filter(person_id__in=person_ids).values_list('person_id', flat=True))

    faces = []
    for number, r in enumerate(results, start=1):
        x, y, w, h = r.box or (None, None, None, None)
        faces.append(FaceMatch.objects.create(
            intake=intake, index=number, frame_index=r.frame_index, box_x=x, box_y=y, box_w=w, box_h=h,
            status=r.status, person=people.get(r.person_id), candidate=people.get(r.candidate_id),
            score=r.score, runner_up_score=r.runner_up_score, support=r.support,
            candidates=[{'person_id': pid, 'name': people[pid].full_name, 'score': round(score, 4)}
                        for pid, score in r.candidates],
        ))

    if results and recognition.frame is not None:
        image = draw(recognition.frame, results, {pid: p.full_name for pid, p in people.items()}, with_record)
        intake.annotated.save(f'{Path(intake.media.name).stem}-boxes.jpg', ContentFile(encode_jpeg(image)), save=False)

    by_person = defaultdict(list)
    for face in faces:
        if face.status == FaceMatch.Status.MATCHED:
            by_person[face.person_id].append(face)

    profiles = 0
    for person_id, rows in by_person.items():
        best = max(rows, key=lambda f: f.score)
        person = people[person_id]
        audit(intake.submitted_by, 'intake.identified', f'intake:{intake.pk}',
              person=person.pk, similarity_pct=best.similarity_pct, face=best.index, has_record=person_id in with_record)
        if person_id not in with_record:
            continue
        checks = validation_checks(best, person, recognition.threshold, len(rows))
        profile = SuspectProfile.objects.create(
            intake=intake, face_match=best, person=person,
            status=(SuspectProfile.Status.VALIDATED if all(c['passed'] for c in checks)
                    else SuspectProfile.Status.NEEDS_REVIEW),
            snapshot=record_snapshot(person), checks=checks,
        )
        audit(None, 'profile.created', f'profile:{profile.pk}', status=profile.status, intake=intake.pk)
        profiles += 1

    if not faces and not recognition.faces_detected:
        intake.status = Intake.Status.NO_FACE
    elif profiles:
        intake.status = Intake.Status.PROFILED
    elif by_person:
        intake.status = Intake.Status.NO_RECORD
    elif any(f.status == FaceMatch.Status.AMBIGUOUS for f in faces):
        intake.status = Intake.Status.AMBIGUOUS
    else:
        intake.status = Intake.Status.NO_MATCH
    intake.save()
    audit(intake.submitted_by, 'intake.processed', f'intake:{intake.pk}', status=intake.status,
          faces=recognition.faces_detected, identified=len(by_person), profiles=profiles)
    return intake



@transaction.atomic
def review_profile(profile: SuspectProfile, reviewer, approve: bool, notes: str = '') -> SuspectProfile:
    if profile.status not in (SuspectProfile.Status.NEEDS_REVIEW, SuspectProfile.Status.VALIDATED):
        raise PipelineError(f'Profile is already {profile.status}')
    profile.status = SuspectProfile.Status.VALIDATED if approve else SuspectProfile.Status.REJECTED
    profile.reviewed_by = reviewer
    profile.review_notes = notes
    profile.reviewed_at = timezone.now()
    profile.save()
    audit(reviewer, 'profile.reviewed', f'profile:{profile.pk}', approved=approve, notes=notes)
    return profile


def recommendations(profile: SuspectProfile) -> list[dict]:
    open_infractions = profile.person.infractions.filter(status=Infraction.Status.OPEN)
    return [recommend(i).as_dict() for i in open_infractions]


@transaction.atomic
def apply_judgment(profile, infraction, decided_by, convicted, sentence_kind,
                   amount=None, hours=None, months=None, rationale='') -> Judgment:
    """Record a human decision. Only a validated profile can be sentenced, one open infraction at a time."""
    if profile.status != SuspectProfile.Status.VALIDATED:
        raise PipelineError(f'Profile must be validated before judgment (currently {profile.status})')
    if infraction.person_id != profile.person_id:
        raise PipelineError('Infraction does not belong to the profiled person')
    if infraction.status != Infraction.Status.OPEN:
        raise PipelineError('Infraction is already closed')

    judgment = Judgment.objects.create(
        profile=profile, infraction=infraction, convicted=convicted, sentence_kind=sentence_kind,
        amount=amount, hours=hours, months=months, rationale=rationale, decided_by=decided_by,
    )
    Penalty.objects.create(
        infraction=infraction, kind=sentence_kind, amount=amount, hours=hours, months=months,
        imposed_at=timezone.now(), judgment=judgment,
    )
    infraction.convicted = convicted
    infraction.status = Infraction.Status.CLOSED
    infraction.save(update_fields=['convicted', 'status'])

    if not profile.person.infractions.filter(status=Infraction.Status.OPEN).exists():
        profile.status = SuspectProfile.Status.ADJUDICATED
        profile.save(update_fields=['status'])
    audit(decided_by, 'judgment.applied', f'infraction:{infraction.pk}',
          convicted=convicted, sentence=sentence_kind, amount=str(amount), hours=hours, months=months)
    assess_person(profile.person)  # record changed: refresh the forward-looking risk
    return judgment


class EnrollmentError(Exception):
    pass


@transaction.atomic
def enroll_person(actor, full_name, date_of_birth, photos, scenario):
    """Create a person from face photos (raw bytes) and give them a dummy record scenario.

    Only embeddings are stored, never the photos. Every photo must contain exactly one face, and
    the face must not already belong to someone enrolled (that would make matches ambiguous).
    """
    if scenario not in SCENARIOS:
        raise EnrollmentError(f'Unknown scenario {scenario!r}')
    engine = get_engine()
    embeddings = []
    for n, data in enumerate(photos, start=1):
        try:
            faces = embed_image_bytes(data, engine)
        except MediaError as exc:
            raise EnrollmentError(f'Photo {n}: {exc}') from exc
        if len(faces) != 1:
            raise EnrollmentError(f'Photo {n}: found {len(faces)} faces, need exactly 1. '
                                  'Face the camera in good light, alone in the frame.')
        embeddings.append(faces[0])

    existing = existing_identity(embeddings, engine)
    if existing:
        name = Person.objects.get(pk=existing[0]).full_name
        raise EnrollmentError(f'This face is already enrolled as {name} ({max(existing[1], 0) * 100:.0f}% similar).')

    person = Person.objects.create(full_name=full_name, date_of_birth=date_of_birth)
    FaceTemplate.objects.bulk_create([
        FaceTemplate(person=person, engine=engine.name, embedding=e.tolist(), source='webcam-enrolment')
        for e in embeddings
    ])
    create_records(person, scenario)
    audit(actor, 'person.enrolled', f'person:{person.pk}', scenario=scenario, photos=len(embeddings))
    return person


@transaction.atomic
def delete_person(actor, person: Person):
    """Erase a person, their face templates, records and profiles, and every intake whose media shows them.

    A group photo shows other people too, so it is erased whole; the other people's profiles and
    judgments are kept (they merely lose the link to the erased media).
    """
    intakes = list(Intake.objects.filter(faces__person=person).distinct())
    for intake in intakes:
        intake.media.delete(save=False)
        intake.annotated.delete(save=False)
        intake.delete()
    audit(actor, 'person.deleted', f'person:{person.pk}', name=person.full_name, intakes_erased=len(intakes))
    person.delete()
