# redqueen
component of precog initiative

RedQueen is now the single project: it absorbed the former standalone `precog` Django project
(`~/projects/precog`, which was a skeleton with one real model). Only this repository needs to be used.

### Where each precog app lives now
| precog app | In redqueen | Status |
|---|---|---|
| `persons` (`Person`: uuid, age_range, gender, total_occurrences) | `registry.Person` (same fields, merged with name/date of birth) | migrated; `/api/persons/{uuid}/`, admin, web pages |
| `crimes` | `registry.Infraction` + `registry.Penalty` | already implemented |
| `suspects` | `cases.SuspectProfile` / `cases.FaceMatch` / `cases.Judgment` | already implemented |
| `locations` | `Infraction.precinct` (used by COMPSTAT hot spots and deployment) | already implemented |
| `analytics` | `precog.compstat` (the redqueen app named `precog`) | already implemented |
| `ml` | `precog.risk` (three-precog risk model) | already implemented |
| `core` | project settings, `redqueen/testing.py`, audit trail (`cases.AuditEvent`) | already implemented |

Precog's `persons.Person` had `age_range` and `gender` only for description. They are kept that way: they are stored,
shown and filterable, but never used by the risk model (a test enforces this). `total_occurrences` is kept equal to the
person's number of infractions automatically. The `uuid` is the person's public ID in the API; the numeric id remains
the internal key.

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
| `/intakes/`, `/intakes/{id}/` | An intake is a full **incident record**: *Incident record* (date, weekday, time, hour, precinct, place, coordinates with a map link, who submitted it and when), *Individuals involved* (each identified person once, with photo, ID, age range, gender, faces, similarity, occurrence count and profile; plus how many faces stayed unidentified), *Occurrences related to this intake* (every infraction on record for those individuals, grouped by person, each with date, time, hour, category, severity, precinct, place, status and penalties), then the boxed image and the per-face table with similarity %. Media (original and boxed) is served only to logged-in users |
| `/profiles/`, `/profiles/{id}/` | The full dossier: subject card with the registered photos and identity data (ID, DOB/age, age range, gender, occurrences); **match evidence** (the intake face cropped next to the registered photo, similarity %, threshold, other candidates); validation checks and review; risk with the three precogs and any minority report; record summary (fines, service hours, probation/prison, pending/defaulted); complete live record with the frozen record from identification; sentence recommendations and judgment form; other appearances and profiles of the person; audit trail (needs `cases.view_auditevent`) |
| `/people/`, `/people/{id}/` | Search people; record and risk per person |
| `/people/enroll/` | Enrol a face from the webcam (needs `registry.add_person`) with a dummy record scenario; erase on the person page (`registry.delete_person`) |
| `/audit/` | Audit trail (needs `cases.view_auditevent`) |
| `/portal/` | The **hellgate**: after a successful sign-in you pass through a demonic portal for 5 seconds ("Accessing...", a progress bar, and a **fire-vortex shader** (three.js, a spiral of flames into a black abyss with rising embers) inside an SVG stone gate with glowing cracks and rotating runes; in the last 0.9 s the gate grows until it fills the screen), then the home page (or the page you originally asked for) opens. The delay is `REDQUEEN['PORTAL_DELAY_SECONDS']`; it is purely visual, since you are already signed in. Only same-site destinations are honoured, so `?next=` cannot bounce you to another site. CSS-only portal plus the SVG gate (`redqueen/web/gate_art.py`) as the fallback without WebGL; reduced motion keeps the wait but drops the motion |
| `/account/` | **My profile** for the signed-in user (click your username in the top bar). Modelled on the user account screen of `callum_freight_hub`: breadcrumb, an Account card (username, first/last name, email, active/staff/superuser, last login, member since), Groups, Permissions (granted first), an "About access levels" card, plus what you can do in RedQueen and your recent activity. You can edit your name and email; access is granted by an administrator and is read-only here. `Change password` is on the same page |

`officer` can view and submit intakes. `judge` can also review profiles, apply judgments, enrol and erase people, and read the audit log.

## Webcam demo
Emulate the full system with your own face (real `opencv-sface` engine, so run `fetch_models` first):

1. `python manage.py seed_dummy_data --users && python manage.py runserver`, sign in as `judge`.
2. **People → Enroll person**: the form has the same fields as a profile's Subject card (name, date of birth, age range, gender, plus the ID, occurrences, registration time and template count it fills in). Enter a dummy name, pick a dummy record scenario (clean / minor / escalating / de-escalating) and see its record previewed,
   *Start camera*, take 2–5 photos with slightly different head angles, *Enroll*. The face embedding is stored plus a cropped image of the face (never the full photo), which is shown as the registered photo. Set `STORE_ENROLMENT_PHOTOS` to `False` in `REDQUEEN` settings to keep only the numeric template.
3. **New intake**: *Start camera*, then *Take photo* or *Record 5 s video*, then *Run pipeline*. You should be
   identified, get a suspect profile (if your scenario has a record) and a risk outlook.
4. If the identity checks fail (poor light, angle) the profile lands in **needs review**: approve it as `judge` to continue,
   then apply a judgment and watch the risk refresh on your person page and the COMPSTAT dashboard.
5. When done, **People → your name → Erase person & face data** removes the templates, records, profiles and the intake media
   that matched you.

Tips: face the camera, good front lighting, one person in frame. Unmatched faces, or two similar enrolled people, end as
*no match* / *ambiguous* rather than a guess. Video is sampled every 10th frame and needs the same person in at least 2 frames.

## Login banner
The **RED QUEEN** wordmark (sign-in banner and top bar) is blood red (`--blood` in `style.css`) with a slowly breathing red glow.

The logo is an original **3D model** of a devil-queen fighter (horns, wings, tail, red battle dress; not the film's design) in a martial-arts guard stance.
It is built procedurally in three.js (`redqueen/web/static/web/queen3d.js`) with physically based materials (clear-coated horns, satin dress, gold metal),
studio reflections, soft shadows and rim lighting. On the sign-in page she is a live WebGL scene: knees flex and the torso bobs, the guard arms sway,
wings, dress, tail and hair move. She holds a heart-topped scepter in her lead hand and sweeps it round so its tip draws a glowing circle on the floor (a lap every 3 s; the arm follows with two-bone IK). The circle lies on the floor in front of her feet and she leans forward from the hips to reach it, so the scepter never passes between her legs. Inside the circle a blood-red **RQ**, in the same font as the RED QUEEN wordmark, is written progressively as the tip goes around, on the same 3 s clock. She turns with the mouse, blinks now and then, and **closes her eyes while you type your password** (real eyelids sliding down, a lash line when shut; they open again when you leave the field). The 2D fallback closes its lids on the same signal. Motion stops for `prefers-reduced-motion`
(one still frame), and without WebGL the page falls back to the 2D artwork. three.js (MIT) is vendored under `static/web/vendor/three/`, so nothing loads from a CDN.

- The round badge in the top bar (`logo.png`) and the favicon (`favicon.png`) are renders of the same model. To regenerate them after changing the model:
  `pip install playwright && python web/art/render_logo.py` (uses the system Google Chrome; it is a dev tool, not a runtime dependency).
- That script also exports `web/art/queen.glb`, a glTF binary. To keep working on the character in **Blender**: File > Import > glTF 2.0.
- `web/test_scene3d.py` parses the scene's constants from `queen3d.js` and checks, for every degree of the lap, that the scepter stays clear of both legs, the tip stays ahead of her feet, and the arm can reach the grip.
- The 2D fallback art is generated by `web/art/build_queen.py` into `logo.svg`, `queen.svg`, `banner.svg`, `queen-fx.css` and the template `web/_queen_stage.html`;
  a test fails if those committed files are stale.
Only use artwork you have the rights to, especially if the repository is shared or public.

## Incident records: when, where, who, which occurrences
- **When:** `captured_at` is when the photo/video was taken (defaults to now, editable, never in the future); it is separate from when it was
  submitted. Date, time and hour are shown in the server time zone, which is UTC unless you set e.g. `REDQUEEN_TIME_ZONE=America/Sao_Paulo`.
  The intake list is ordered by capture time.
- **Where:** precinct, a place/address, and optional latitude/longitude (the form can fill them from the browser's location).
- **Who:** every distinct person identified in the media, plus a count of unidentified faces.
- **Which occurrences:** when an intake is processed, every occurrence (infraction) on record for the identified people is linked to it
  (`Intake.related_occurrences`). Occurrences now carry their own `location`, alongside precinct and time.
- The API returns the same: `captured_at`, `date`, `time`, `hour`, `precinct`, `location`, `latitude`, `longitude`, `individuals` and `occurrences`.

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
- `POST /api/intakes/` multipart `media`, `captured_at`, `precinct`, `location`, `latitude`, `longitude` → runs the pipeline, returns the incident record (individuals, related occurrences, faces, profiles)
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
