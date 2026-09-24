"""Face engines turn an image into zero or more face embeddings (L2-normalised vectors)."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import lru_cache

import cv2
import numpy as np
from django.conf import settings


class EngineError(Exception):
    pass


@dataclass
class Face:
    box: tuple[int, int, int, int]  # x, y, width, height in image pixels
    embedding: np.ndarray  # L2-normalised


class FaceEngine(ABC):
    name: str
    default_threshold: float  # cosine similarity needed to call two embeddings the same person

    @abstractmethod
    def detect(self, image: np.ndarray) -> list[Face]:
        """Return every face found in a BGR image, with its bounding box and embedding."""

    def embed(self, image: np.ndarray) -> list[np.ndarray]:
        return [face.embedding for face in self.detect(image)]


class OpenCVSFaceEngine(FaceEngine):
    """YuNet face detection + SFace recognition (ONNX models, run through OpenCV's DNN module).

    Models live in REDQUEEN['MODEL_DIR']; fetch them with `manage.py fetch_models`.
    """

    name = 'opencv-sface'
    # OpenCV documents 0.363 for SFace, but on a 57-person group photo a different person scored 0.386
    # against an enrolled face, so the default is deliberately stricter. Calibrate on your own data.
    default_threshold = 0.50
    detector_file = 'face_detection_yunet_2023mar.onnx'
    recognizer_file = 'face_recognition_sface_2021dec.onnx'

    def __init__(self, model_dir):
        detector_path = model_dir / self.detector_file
        recognizer_path = model_dir / self.recognizer_file
        missing = [p.name for p in (detector_path, recognizer_path) if not p.exists()]
        if missing:
            raise EngineError(f'Missing model files {missing} in {model_dir}; run `manage.py fetch_models`.')
        self._detector = cv2.FaceDetectorYN.create(str(detector_path), '', (320, 320), score_threshold=0.8)
        self._recognizer = cv2.FaceRecognizerSF.create(str(recognizer_path), '')

    def detect(self, image):
        height, width = image.shape[:2]
        self._detector.setInputSize((width, height))
        _, rows = self._detector.detect(image)
        if rows is None:
            return []
        faces = []
        for row in rows:
            aligned = self._recognizer.alignCrop(image, row)
            vector = self._recognizer.feature(aligned).flatten().astype(np.float64)
            x, y, w, h = (int(round(v)) for v in row[:4])
            x, y = max(x, 0), max(y, 0)
            faces.append(Face((x, y, min(w, width - x), min(h, height - y)), vector / np.linalg.norm(vector)))
        return faces


class SyntheticEngine(FaceEngine):
    """Test double for the dummy portraits (vision.dummy): no real detection happens.

    A square image is one 'face'. An image whose width is a whole multiple of its height
    (vision.dummy.make_group_photo) is a row of square tiles, one 'face' per tile.
    """

    name = 'synthetic'
    default_threshold = 0.8

    def detect(self, image):
        height, width = image.shape[:2]
        tiles = width // height if height and width % height == 0 else 1
        tile_width = width // tiles
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
        faces = []
        for n in range(tiles):
            tile = gray[:, n * tile_width:(n + 1) * tile_width]
            vector = cv2.resize(tile, (16, 16), interpolation=cv2.INTER_AREA).astype(np.float64).flatten()
            vector -= vector.mean()
            norm = np.linalg.norm(vector)
            if norm < 1e-6:
                continue  # blank tile: no face
            faces.append(Face((n * tile_width, 0, tile_width, height), vector / norm))
        return faces


@lru_cache(maxsize=None)
def _build(name, model_dir):
    if name == SyntheticEngine.name:
        return SyntheticEngine()
    if name == OpenCVSFaceEngine.name:
        return OpenCVSFaceEngine(model_dir)
    raise EngineError(f'Unknown vision engine {name!r}')


def get_engine(name=None) -> FaceEngine:
    config = settings.REDQUEEN
    return _build(name or config['VISION_ENGINE'], config['MODEL_DIR'])
