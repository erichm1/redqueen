# redqueen
component of precog initiative

Photo/video in → face recognition → record lookup → suspect profile → validation →
conviction (optional) / sentence → forward-looking risk, reported COMPSTAT-style.
All included data is dummy data (John, Jane, Susan and Mark Doe).

## Quick start

```bash
source env/bin/activate
cd redqueen
python manage.py migrate
python manage.py fetch_models          # YuNet + SFace ONNX models (~38 MB, gitignored)
python manage.py seed_dummy_data --users   # dummy people, records, portraits, a short video, dev logins
python manage.py redqueen_demo         # runs the whole pipeline on the dummy media (CLI)
python manage.py test
REDQUEEN_VISION_ENGINE=synthetic python manage.py runserver
```

Then open http://127.0.0.1:8000/ (use `localhost` or `127.0.0.1`: browsers only allow camera access on those or HTTPS) and sign in as `officer` or `judge` (password `redqueen-demo`, dev only).
To use your own webcam, run the server **without** `REDQUEEN_VISION_ENGINE=synthetic` (see [Webcam demo](#webcam-demo)).
Use `REDQUEEN_VISION_ENGINE=synthetic` to try the dummy portraits in `redqueen/media/dummy/`
(`john.png`, `mark.avi`, `stranger.png`, and `group.png`, a five-person group photo); the default `opencv-sface` engine is for real photos.

## Frontend
Server-rendered Django pages (`web` app, no build step), same session login as the API.

| Page | Purpose |
|---|---|
| `/` | COMPSTAT dashboard: incidents, hot spots, deployment split, high-risk watchlist (7/28/90/365-day windows) |
| `/intake/new/` | Upload a photo or video and run the pipeline |
| `/intakes/`, `/intakes/{id}/` | Boxed image, faces table with similarity %, one suspect profile per identified person; media (original and boxed) is served only to logged-in users |
| `/profiles/`, `/profiles/{id}/` | Validation checks, risk with the three precogs and any minority report, record timeline, sentence recommendations, review and judgment forms |
| `/people/`, `/people/{id}/` | Search people; record and risk per person |
| `/people/enroll/` | Enrol a face from the webcam (needs `registry.add_person`) with a dummy record scenario; erase on the person page (`registry.delete_person`) |
| `/audit/` | Audit trail (needs `cases.view_auditevent`) |

`officer` can view and submit intakes. `judge` can also review profiles, apply judgments, enrol and erase people, and read the audit log.

## Webcam demo
Emulate the full system with your own face (real `opencv-sface` engine, so run `fetch_models` first):

1. `python manage.py seed_dummy_data --users && python manage.py runserver`, sign in as `judge`.
2. **People → Enroll person**: enter a dummy name, pick a dummy record scenario (clean / minor / escalating / de-escalating),
   *Start camera*, take 2–5 photos with slightly different head angles, *Enroll*. Only the face template is stored, not the photos.
3. **New intake**: *Start camera*, then *Take photo* or *Record 5 s video*, then *Run pipeline*. You should be
   identified, get a suspect profile (if your scenario has a record) and a risk outlook.
4. If the identity checks fail (poor light, angle) the profile lands in **needs review**: approve it as `judge` to continue,
   then apply a judgment and watch the risk refresh on your person page and the COMPSTAT dashboard.
5. When done, **People → your name → Erase person & face data** removes the templates, records, profiles and the intake media
   that matched you.

Tips: face the camera, good front lighting, one person in frame. Unmatched faces, or two similar enrolled people, end as
*no match* / *ambiguous* rather than a guess. Video is sampled every 10th frame and needs the same person in at least 2 frames.

## Login banner
The sign-in page shows `redqueen/web/static/web/banner.svg` (original artwork). To use your own image, save it as
`redqueen/web/static/web/banner.jpg` (or `.png` / `.webp`, wide, roughly 960×300); it is picked up automatically, no code change.
Only use artwork you have the rights to, especially if the repository is shared or public.

## Similarity percentages, boxes and group photos
- Every intake page shows the photo with an OpenCV box on each face (`#n Name 87%`; red = identified with a record,
  green = identified with none, amber = ambiguous, grey = unknown) and a table with one row per face: registered person,
  similarity %, a meter with the acceptance threshold marked, the next closest person, and the closest registered people.
- **Similarity % = cosine similarity of the two face embeddings × 100.** It says how alike the model finds the intake
  face and the registered face. It is *not* the probability that the identification is right; the accuracy of a
  threshold has to be measured on your own labelled data.
- Photos: all faces are identified independently, left to right. Videos: each person seen in ≥ 2 sampled frames is
  reported once (mean similarity); one representative frame is boxed.
- A person's profile is validated automatically only when their similarity clears the threshold by a further margin, they
  are clearly ahead of the next person, and they matched exactly one face in the media (a second face matching the same
  person sends the profile to human review).
- The person page lists every appearance with its similarity. Erasing a person also erases every intake whose media shows
  them; other people's profiles and judgments from a shared group photo are kept.
- Real-engine check (OpenCV's public 57-person class photo, three faces enrolled): all 57 faces were boxed, the three were
  identified at 100% (same photo) and 89-96% (70% size, darker copy), and the highest unrelated face was 38.6%. That
  score exceeded SFace's stock threshold (36.3%), so the default is now 50%. Set `MATCH_THRESHOLD` after calibrating.

## Pipeline

| Step | Code | Notes |
|---|---|---|
| Ingest photo/video | `api.views.IntakeViewSet`, `vision.media` | videos are sampled every N frames |
| Detect + recognise | `vision.engines`, `vision.matching`, `vision.annotate` | `opencv-sface` (YuNet detects **every** face; SFace embeds each). Each face gets a box, a similarity %, and its closest registered people. A match needs the threshold plus a margin over the runner-up; for video, agreement across frames |
| Check records | `cases.services.process_intake` | per identified person: no record → identified but **no profile**. In a group photo every identified person with a record gets their own profile |
| Suspect profile + validation | `cases.services` | snapshot of the record plus automated checks. Any failing check → `needs_review` for a human |
| Conviction / sentence | `cases.sentencing`, `cases.services.apply_judgment` | guideline **recommendation**; applying it is a separate step by a user with `cases.adjudicate`, only on a validated profile |
| Risk | `precog.risk` | only for people with a conviction or a fine; refreshed after every judgment |
| COMPSTAT | `precog.compstat` | intelligence, tactics, deployment, follow-up |

### Minority Report
Three "precogs" score the record independently: **agatha** (severity-weighted frequency/recency),
**arthur** (severity trajectory: more or less severe), **dashiell** (sanction compliance and reoffending).
The mean is the risk score; any precog that disagrees with the consensus level is stored as the
**minority report**.

### Guardrails built in
- Risk uses record history only. Face embeddings, appearance and demographics never enter it.
- The output is labelled advisory; nothing is sentenced automatically. Review and judgment need
  explicit Django permissions (`cases.review_profile`, `cases.adjudicate`).
- Every identification, review and judgment is written to the append-only `AuditEvent` table.
- Embeddings are only compared within the same engine.

## API (authenticated)
- `POST /api/intakes/` multipart `media`, `precinct` → runs the pipeline, returns intake + profile
- `GET /api/profiles/`, `GET /api/profiles/{id}/`
- `POST /api/profiles/{id}/review/` `{approve, notes}`
- `POST /api/profiles/{id}/judgment/` `{infraction, convicted, sentence_kind, amount|hours|months, rationale}`
- `GET /api/persons/{id}/risk/[?refresh=1]`
- `GET /api/compstat/?days=28`

## Before real use
- The thresholds (`REDQUEEN` in settings) are placeholders and must be calibrated on data that
  reflects the population, with error rates checked per demographic group. Face recognition is
  known to be less accurate for some groups.
- The sentencing table is illustrative, not law.
- Only the dummy-portrait path is covered by tests; `opencv-sface` is smoke-tested for loading and
  for returning no faces on non-face images, but has not been evaluated on real photos.
- `synthetic` (the test engine) must never be used on real people.
