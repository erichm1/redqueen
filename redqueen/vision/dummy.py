"""Deterministic synthetic portraits and videos for tests and demos (no real people involved)."""
import zlib

import cv2
import numpy as np


def make_portrait(name, variant=0, size=128):
    """A stylised 'face' unique to `name`. Different variants add sensor noise and exposure changes."""
    rng = np.random.default_rng(zlib.crc32(name.encode()))
    field = cv2.resize(rng.random((8, 8)), (size, size), interpolation=cv2.INTER_CUBIC) * 255
    image = cv2.cvtColor(field.astype(np.uint8), cv2.COLOR_GRAY2BGR)

    centre = (size // 2 + int(rng.integers(-10, 10)), size // 2 + int(rng.integers(-10, 10)))
    axes = (int(size * rng.uniform(0.22, 0.38)), int(size * rng.uniform(0.3, 0.45)))
    skin = tuple(int(v) for v in rng.integers(60, 230, 3))
    cv2.ellipse(image, centre, axes, 0, 0, 360, skin, -1)
    eye_gap = int(rng.integers(size // 10, size // 5))
    for dx in (-eye_gap, eye_gap):
        cv2.circle(image, (centre[0] + dx, centre[1] - axes[1] // 3), int(rng.integers(2, 6)), (20, 20, 20), -1)
    mouth = int(rng.integers(6, 20))
    cv2.line(image, (centre[0] - mouth, centre[1] + axes[1] // 2), (centre[0] + mouth, centre[1] + axes[1] // 2),
             (40, 40, 160), 2)

    if variant:
        noise_rng = np.random.default_rng(zlib.crc32(name.encode()) + variant * 7919 + 1)
        noisy = image.astype(np.float64) + noise_rng.normal(0, 6, image.shape) + noise_rng.uniform(-8, 8)
        image = np.clip(noisy, 0, 255).astype(np.uint8)
    return image


def make_group_photo(names, variant=1, size=128):
    """Portraits side by side as square tiles (the synthetic engine sees one face per tile)."""
    return np.hstack([make_portrait(name, variant, size) for name in names])


def write_group_photo(names, path, variant=1):
    cv2.imwrite(str(path), make_group_photo(names, variant))


def write_photo(name, path, variant=0):
    cv2.imwrite(str(path), make_portrait(name, variant))


def write_video(name, path, frames=30, fps=10):
    """Short clip of `name`; every frame is a fresh noisy variant."""
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'MJPG'), fps, (128, 128))
    if not writer.isOpened():
        raise RuntimeError('OpenCV could not open a video writer')
    for i in range(frames):
        writer.write(make_portrait(name, variant=i + 1))
    writer.release()
