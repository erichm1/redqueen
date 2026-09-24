"""Draw the recognition result on the image with OpenCV: one box + label per face."""
import cv2

# BGR
COLOURS = {
    'suspect': (75, 50, 229),   # matched, has a record
    'clear': (122, 185, 63),    # matched, nothing on record
    'ambiguous': (43, 167, 224),
    'unknown': (160, 160, 160),
}


def label_for(number, result, names):
    pct = f'{max(result.score, 0) * 100:.0f}%' if result.score is not None else '-'
    if result.status == 'matched':
        return f'#{number} {names.get(result.person_id, "?")} {pct}'
    return f'#{number} {"ambiguous" if result.status == "ambiguous" else "unknown"} ({pct})'


def fit_label(number, result, names, box_width, font_scale_max, font_scale_min=0.32):
    """Largest label (full text, else compact `#n 87%`) that fits inside the box width."""
    compact = f'#{number} {max(result.score, 0) * 100:.0f}%' if result.score is not None else f'#{number}'
    for text in (label_for(number, result, names), compact):
        scale = font_scale_max
        while scale > font_scale_min:
            if cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 1)[0][0] + 6 <= box_width:
                return text, scale
            scale -= 0.04
    return compact, font_scale_min


def draw(frame, results, names, with_record):
    """Return a copy of `frame` with every located face boxed and labelled.

    names: person_id -> name. with_record: set of person_ids that have a record on file.
    Faces are numbered in the order of `results`, matching the table shown next to the image.
    """
    image = frame.copy()
    scale = max(image.shape[:2]) / 1000
    thickness = max(2, round(2 * scale))
    font_scale_max = max(0.5, 0.6 * scale)
    for number, result in enumerate(results, start=1):
        if result.box is None:
            continue
        x, y, w, h = result.box
        kind = ('suspect' if result.person_id in with_record else 'clear') if result.status == 'matched' \
            else 'ambiguous' if result.status == 'ambiguous' else 'unknown'
        colour = COLOURS[kind]
        cv2.rectangle(image, (x, y), (x + w, y + h), colour, thickness)

        text, font_scale = fit_label(number, result, names, w, font_scale_max)
        (tw, th), baseline = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, font_scale, 1)
        top = y - th - baseline - 4
        if top < 0:  # no room above the box: put the label inside it
            top = y + 2
        left = min(x, max(image.shape[1] - tw - 6, 0))
        cv2.rectangle(image, (left, top), (left + tw + 6, top + th + baseline + 4), colour, -1)
        cv2.putText(image, text, (left + 3, top + th + 1), cv2.FONT_HERSHEY_SIMPLEX, font_scale,
                    (255, 255, 255), 1, cv2.LINE_AA)
    return image


def encode_jpeg(image, quality=90):
    ok, buffer = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise ValueError('Could not encode annotated image')
    return buffer.tobytes()
