# Changelog

## Unreleased
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
- 74 tests; the browser flow (webcam photo/video capture, enrol, recognise) was also driven in headless Chrome with a fake camera.
