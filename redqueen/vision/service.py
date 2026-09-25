"""High level computer-vision operations: recognise every face in a photo or video, embed uploads."""
from dataclasses import dataclass

import cv2
import numpy as np
from django.conf import settings

from registry.models import FaceTemplate

from .engines import get_engine
from .matching import FaceResult, Gallery, classify, identify_frames
from .media import MediaError, load_frames


@dataclass
class Recognition:
    faces_detected: int
    results: list[FaceResult]
    frame: np.ndarray | None  # the frame the boxes refer to (unannotated)
    threshold: float


def threshold_for(engine):
    return settings.REDQUEEN['MATCH_THRESHOLD'] or engine.default_threshold


def load_gallery(engine):
    return Gallery([(t.person_id, np.asarray(t.embedding))
                    for t in FaceTemplate.objects.filter(engine=engine.name)])


def detect_image_bytes(data, engine=None):
    """(image, faces) for an in-memory encoded image (e.g. an upload), without touching disk."""
    image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise MediaError('Could not decode image')
    return image, (engine or get_engine()).detect(image)


def embed_image_bytes(data, engine=None):
    return [face.embedding for face in detect_image_bytes(data, engine)[1]]


def existing_identity(embeddings, engine):
    """The first already-enrolled person any of these embeddings matches, as (person_id, similarity)."""
    gallery, threshold = load_gallery(engine), threshold_for(engine)
    for embedding in embeddings:
        result = classify(embedding, gallery, threshold, settings.REDQUEEN['MATCH_MARGIN'])
        if result.status == 'matched':
            return result.person_id, result.score
    return None


def recognize(path, media_type) -> Recognition:
    config = settings.REDQUEEN
    engine = get_engine()
    threshold = threshold_for(engine)
    frames = load_frames(path, media_type)
    detections = [engine.detect(frame) for frame in frames]
    results, index, faces_detected = identify_frames(
        detections, load_gallery(engine), threshold, config['MATCH_MARGIN'],
        config['VIDEO_MIN_SUPPORT'] if media_type == 'video' else 1)
    return Recognition(faces_detected, results, frames[index] if frames else None, threshold)
