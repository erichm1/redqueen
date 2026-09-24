import urllib.request

from django.conf import settings
from django.core.management.base import BaseCommand

from vision.engines import OpenCVSFaceEngine

BASE = 'https://github.com/opencv/opencv_zoo/raw/main/models'
MODELS = {
    OpenCVSFaceEngine.detector_file: f'{BASE}/face_detection_yunet/{OpenCVSFaceEngine.detector_file}',
    OpenCVSFaceEngine.recognizer_file: f'{BASE}/face_recognition_sface/{OpenCVSFaceEngine.recognizer_file}',
}


class Command(BaseCommand):
    help = 'Download the YuNet / SFace ONNX models used by the opencv-sface engine.'

    def handle(self, *args, **options):
        model_dir = settings.REDQUEEN['MODEL_DIR']
        model_dir.mkdir(exist_ok=True)
        for filename, url in MODELS.items():
            target = model_dir / filename
            if target.exists():
                self.stdout.write(f'{filename}: already present')
                continue
            self.stdout.write(f'{filename}: downloading')
            urllib.request.urlretrieve(url, target)
        self.stdout.write(self.style.SUCCESS('Models ready'))
