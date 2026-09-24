# Changelog

## Unreleased
- Merged the standalone `precog` project into redqueen. Its `Person` entity is now part of `registry.Person`:
  `uuid` (unique, public id), `age_range` (derived from date of birth, or set by hand), `gender`, `total_occurrences`
  (auto-maintained from infractions). Migrations `registry/0002-0004` add the fields, backfill existing rows (unique UUIDs,
  age ranges, counts) and then enforce uniqueness; verified on a populated database.
- New `/api/persons/` (list, create, update, delete) addressed by UUID with `q` / `age_range` filters, `/api/persons/{uuid}/risk/`;
  the numeric `/api/persons/{id}/risk/` route still works. Deleting via the API erases face data and media like the web action.
- Person list/detail/enrolment/admin show age range, gender and occurrences. `__str__` added to every entity.
- Entity health tests (`redqueen/test_entities.py`): every model has rows from a full pipeline run, opens in the admin,
  passes validation, and matches its migrations. A test asserts age/gender never change the risk score.
- Django apps: `registry` (people, faces, infractions, penalties), `vision` (OpenCV YuNet/SFace
  recognition, photo + video), `cases` (intake, suspect profile, validation, judgment, audit trail),
  `precog` (three-voter risk model with minority report, COMPSTAT report), `api` (DRF + Swagger).
- `seed_dummy_data`, `redqueen_demo` and `fetch_models` management commands.
- Dummy data: John, Jane, Susan and Mark Doe plus background records.
- `web` frontend: COMPSTAT dashboard, intake upload, profile review/judgment, people, audit log; login required, permission-gated actions, uploaded media only served to authenticated users.
- `seed_dummy_data --users` creates dev logins `officer` / `judge`.
- Webcam capture (photo or 5 s video) on the intake page; webcam enrolment page with dummy record scenarios (`registry.demo`); erase-person action that also removes matching intake media. Enrolment stores face templates only, rejects photos without exactly one face and faces already enrolled.
- Multi-face recognition: every face in a photo is detected, boxed (OpenCV) and compared separately; per-face similarity %, closest registered people, and one suspect profile per identified person with a record (group photos). Video reports each person seen in >= 2 frames. `FaceMatch` model, `Intake.annotated`, migration `cases/0003`. API returns `faces` and `profiles`.
- Validation check `single_subject` replaced by `unique_in_frame`; default `opencv-sface` threshold raised 0.363 -> 0.50 after a false match at 0.386 on a 57-face photo.
- Erasing a person erases every intake showing them (incl. group photos) but keeps other people's profiles.
- 96 tests; the browser flow (webcam photo/video capture, enrol, recognise) was also driven in headless Chrome with a fake camera.
