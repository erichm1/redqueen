import cv2
import numpy as np
from django.test import SimpleTestCase

from redqueen.testing import DummyWorldTestCase
from registry.models import Person

from .annotate import draw, fit_label
from .dummy import make_group_photo, make_portrait
from .engines import Face, SyntheticEngine
from .matching import FaceResult, Gallery, classify, identify_frames
from .service import recognize

NAMES = ['John Doe', 'Jane Doe', 'Susan Doe', 'Mark Doe']


class SyntheticEngineTests(SimpleTestCase):
    engine = SyntheticEngine()

    def embed(self, name, variant=0):
        return self.engine.embed(make_portrait(name, variant))[0]

    def test_same_person_is_similar_and_different_people_are_not(self):
        for name in NAMES:
            self.assertGreater(self.embed(name) @ self.embed(name, 3), 0.95)
        for a in NAMES:
            for b in NAMES:
                if a != b:
                    self.assertLess(self.embed(a) @ self.embed(b, 1), 0.5)

    def test_blank_image_has_no_face(self):
        self.assertEqual(self.engine.detect(np.zeros((64, 64, 3), np.uint8)), [])

    def test_group_photo_yields_one_face_with_a_box_per_tile(self):
        faces = self.engine.detect(make_group_photo(NAMES))
        self.assertEqual([f.box for f in faces], [(0, 0, 128, 128), (128, 0, 128, 128),
                                                  (256, 0, 128, 128), (384, 0, 128, 128)])


def face(vector, x=0):
    vector = np.asarray(vector, dtype=float)
    return Face((x, 0, 10, 10), vector / np.linalg.norm(vector))


GALLERY = Gallery([(1, np.array([1.0, 0.0, 0.0])), (2, np.array([0.0, 1.0, 0.0])), (3, np.array([0.0, 0.0, 1.0]))])


class MatchingTests(SimpleTestCase):
    def test_classify_reports_similarity_and_closest_people(self):
        result = classify(np.array([1.0, 0.0, 0.0]), GALLERY, threshold=0.5, margin=0.05)
        self.assertEqual((result.status, result.person_id, result.score), ('matched', 1, 1.0))
        self.assertEqual(len(result.candidates), 3)

    def test_below_threshold_is_unknown_but_still_reports_the_closest(self):
        result = classify(np.array([1.0, 1.0, 1.0]) / 3 ** .5, GALLERY, threshold=0.9, margin=0.05)
        self.assertEqual((result.status, result.person_id), ('no_match', None))
        self.assertIsNotNone(result.candidate_id)
        self.assertAlmostEqual(result.score, 3 ** -.5)

    def test_ambiguous_when_two_people_are_equally_close(self):
        twins = Gallery([(1, np.array([1.0, 0.0])), (2, np.array([1.0, 0.0]))])
        self.assertEqual(classify(np.array([1.0, 0.0]), twins, 0.5, 0.05).status, 'ambiguous')

    def test_empty_gallery(self):
        self.assertEqual(classify(np.array([1.0]), Gallery([]), 0.5, 0.05).status, 'no_match')

    def test_photo_gives_one_result_per_face_left_to_right(self):
        faces = [face([0, 1, 0], x=200), face([1, 0, 0], x=10), face([1, 1, 1], x=100)]
        results, index, detected = identify_frames([faces], GALLERY, 0.9, 0.05)
        self.assertEqual((index, detected), (0, 3))
        self.assertEqual([r.box[0] for r in results], [10, 100, 200])
        self.assertEqual([r.status for r in results], ['matched', 'no_match', 'matched'])
        self.assertEqual([r.person_id for r in results], [1, None, 2])

    def test_video_person_needs_min_support_frames(self):
        frames = [[face([1, 0, 0])], [face([0, 0, 1])], [face([0, 0, 1])]]
        results, _, _ = identify_frames(frames, GALLERY, 0.9, 0.05, min_support=2)
        self.assertEqual([r.person_id for r in results if r.status == 'matched'], [3])
        self.assertEqual(next(r for r in results if r.status == 'matched').support, 2)

    def test_video_people_absent_from_the_annotated_frame_are_still_reported(self):
        frames = [[face([1, 0, 0]), face([0, 1, 0], x=50)], [face([1, 0, 0])], [face([0, 1, 0], x=50)],
                  [face([1, 0, 0]), face([0, 1, 0], x=50)]]
        results, rep, _ = identify_frames(frames, GALLERY, 0.9, 0.05, min_support=2)
        self.assertEqual(sorted(r.person_id for r in results if r.status == 'matched'), [1, 2])
        self.assertEqual(rep, 0)  # first frame with both people

    def test_no_faces(self):
        self.assertEqual(identify_frames([[]], GALLERY, 0.5, 0.05), ([], 0, 0))


class AnnotateTests(SimpleTestCase):
    def test_boxes_are_drawn_only_where_faces_are(self):
        frame = np.full((200, 400, 3), 40, np.uint8)
        result = FaceResult('matched', box=(50, 60, 100, 100), person_id=1, score=0.87)
        image = draw(frame, [result], {1: 'John Doe'}, with_record={1})
        self.assertEqual(image.shape, frame.shape)
        self.assertFalse(np.array_equal(image, frame))
        self.assertTrue(np.array_equal(image[:, 200:], frame[:, 200:]))   # far from the box: untouched
        self.assertTrue(np.array_equal(frame, np.full((200, 400, 3), 40, np.uint8)))  # input not modified
        self.assertEqual(tuple(image[110, 50]), (75, 50, 229))            # box edge in the "suspect" colour

    def test_faces_without_a_box_are_skipped(self):
        frame = np.zeros((50, 50, 3), np.uint8)
        self.assertTrue(np.array_equal(draw(frame, [FaceResult('matched', person_id=1, score=.9)], {1: 'A'}, set()), frame))

    def test_label_shrinks_to_compact_form_on_tiny_boxes(self):
        result = FaceResult('matched', person_id=1, score=0.87)
        text, _ = fit_label(2, result, {1: 'A Very Long Name Indeed'}, box_width=45, font_scale_max=1.0)
        self.assertEqual(text, '#2 87%')
        text, _ = fit_label(2, result, {1: 'Jo'}, box_width=400, font_scale_max=1.0)
        self.assertEqual(text, '#2 Jo 87%')


class RecognizeTests(DummyWorldTestCase):
    def test_photo_of_each_enrolled_person_is_identified_with_a_percentage(self):
        for name in NAMES:
            recognition = recognize(self.probes / f'{name.split()[0].lower()}.png', 'photo')
            (result,) = recognition.results
            self.assertEqual(result.status, 'matched', name)
            self.assertEqual(result.person_id, Person.objects.get(full_name=name).pk)
            self.assertGreater(result.score, 0.9)
            self.assertEqual(result.box, (0, 0, 128, 128))
        self.assertEqual(recognition.threshold, 0.8)

    def test_group_photo_identifies_everyone_and_leaves_the_stranger_unknown(self):
        recognition = recognize(self.probes / 'group.png', 'photo')
        self.assertEqual(recognition.faces_detected, 5)
        people = {p.full_name: p.pk for p in Person.objects.all()}
        self.assertEqual([r.person_id for r in recognition.results],
                         [people['John Doe'], people['Susan Doe'], None, people['Jane Doe'], people['Mark Doe']])
        stranger = recognition.results[2]
        self.assertEqual(stranger.status, 'no_match')
        self.assertLess(stranger.score, 0.5)
        self.assertEqual([r.box[0] for r in recognition.results], [0, 128, 256, 384, 512])

    def test_video_is_identified_across_frames(self):
        recognition = recognize(self.probes / 'john.avi', 'video')
        (result,) = [r for r in recognition.results if r.status == 'matched']
        self.assertGreaterEqual(result.support, 2)
        self.assertIsNotNone(recognition.frame)

    def test_stranger_is_not_matched(self):
        (result,) = recognize(self.probes / 'stranger.png', 'photo').results
        self.assertEqual((result.status, result.person_id), ('no_match', None))


class VideoContainerTests(DummyWorldTestCase):
    def test_webm_recordings_like_a_browser_makes_can_be_read(self):
        from .media import load_frames
        path = self.probes / 'browser.webm'
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'VP80'), 10, (128, 128))
        if not writer.isOpened():
            self.skipTest('this OpenCV build cannot write VP8 webm')
        for i in range(30):
            writer.write(make_portrait('John Doe', i + 1))
        writer.release()
        self.assertGreaterEqual(len(load_frames(path, 'video')), 3)
        matched = [r for r in recognize(path, 'video').results if r.status == 'matched']
        self.assertEqual([r.person_id for r in matched], [Person.objects.get(full_name='John Doe').pk])
