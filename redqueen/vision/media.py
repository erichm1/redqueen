"""Load photos and videos as BGR frames."""
import cv2
from django.conf import settings

PHOTO_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.webp'}
VIDEO_EXTENSIONS = {'.mp4', '.avi', '.mov', '.mkv', '.webm'}


class MediaError(Exception):
    pass


def infer_media_type(filename):
    ext = '.' + filename.lower().rsplit('.', 1)[-1] if '.' in filename else ''
    if ext in PHOTO_EXTENSIONS:
        return 'photo'
    if ext in VIDEO_EXTENSIONS:
        return 'video'
    raise MediaError(f'Unsupported media type: {filename!r}')


def _fit(image):
    longest = max(image.shape[:2])
    limit = settings.REDQUEEN['MAX_IMAGE_SIDE']
    if longest <= limit:
        return image
    scale = limit / longest
    return cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)


def load_frames(path, media_type):
    """Return a list of frames (one for a photo, sampled frames for a video)."""
    path = str(path)
    if media_type == 'photo':
        image = cv2.imread(path)
        if image is None:
            raise MediaError(f'Could not decode image {path!r}')
        return [_fit(image)]

    config = settings.REDQUEEN
    capture = cv2.VideoCapture(path)
    if not capture.isOpened():
        raise MediaError(f'Could not open video {path!r}')
    frames, index = [], 0
    try:
        while len(frames) < config['VIDEO_MAX_FRAMES']:
            ok, frame = capture.read()
            if not ok:
                break
            if index % config['VIDEO_FRAME_STRIDE'] == 0:
                frames.append(_fit(frame))
            index += 1
    finally:
        capture.release()
    if not frames:
        raise MediaError(f'No frames could be read from {path!r}')
    return frames
