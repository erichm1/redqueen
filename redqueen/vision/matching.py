"""Identify every face in a photo (or the people seen across a video) against the enrolled gallery.

Similarity is the cosine similarity between face embeddings (1.0 = identical direction). It is a
distance measure, not the probability that a match is correct; the threshold that separates
"same person" from "different person" must be calibrated per engine.
"""
from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np

TOP_CANDIDATES = 3


@dataclass
class FaceResult:
    status: str  # matched | ambiguous | no_match
    frame_index: int = 0
    box: tuple[int, int, int, int] | None = None  # None: seen in the video but not in the annotated frame
    person_id: int | None = None  # accepted identity
    candidate_id: int | None = None  # closest enrolled person, even if not accepted
    score: float | None = None  # similarity to the closest enrolled person
    runner_up_score: float | None = None  # similarity to the second closest person
    support: int = 1  # frames this identity was seen in (video)
    candidates: list[tuple[int, float]] = field(default_factory=list)  # top (person_id, similarity)


class Gallery:
    def __init__(self, entries):
        """entries: [(person_id, embedding)]"""
        self.ids = np.array([person_id for person_id, _ in entries])
        self.matrix = np.vstack([vector for _, vector in entries]) if entries else np.zeros((0, 0))

    def __bool__(self):
        return len(self.ids) > 0

    def rank(self, embedding):
        """[(person_id, best similarity over that person's templates)], best first."""
        best = defaultdict(lambda: -1.0)
        for person_id, similarity in zip(self.ids, self.matrix @ embedding):
            best[int(person_id)] = max(best[int(person_id)], float(similarity))
        return sorted(best.items(), key=lambda item: item[1], reverse=True)


def classify(embedding, gallery, threshold, margin) -> FaceResult:
    ranked = gallery.rank(embedding) if gallery else []
    if not ranked:
        return FaceResult('no_match')
    (top_id, top), runner_up = ranked[0], (ranked[1][1] if len(ranked) > 1 else -1.0)
    result = FaceResult('no_match', candidate_id=top_id, score=top, runner_up_score=runner_up,
                        candidates=ranked[:TOP_CANDIDATES])
    if top >= threshold:
        if top - runner_up >= margin:
            result.status, result.person_id = 'matched', top_id
        else:
            result.status = 'ambiguous'
    return result


def identify_frames(frames, gallery, threshold, margin, min_support=1):
    """frames: list (one per frame) of lists of engine Faces.

    Returns (results, annotated_frame_index, faces_detected).
    - One frame (a photo): one result per face, left to right.
    - Several frames (a video): each person seen in >= min_support frames gets a single result
      (mean similarity); the rest is reported from the most informative frame, which is the one
      that gets annotated.
    """
    faces_detected = max((len(f) for f in frames), default=0)
    classified = [[(face, classify(face.embedding, gallery, threshold, margin)) for face in frame]
                  for frame in frames]

    def place(face, result, index):
        result.box, result.frame_index = face.box, index
        return result

    if len(frames) == 1:
        results = [place(f, r, 0) for f, r in classified[0]]
        return sorted(results, key=lambda r: r.box[0]), 0, faces_detected

    seen = defaultdict(list)  # person_id -> [(frame_index, face, result)]
    for index, frame in enumerate(classified):
        for face, result in frame:
            if result.status == 'matched':
                seen[result.person_id].append((index, face, result))
    eligible = {pid for pid, hits in seen.items() if len({i for i, _, _ in hits}) >= min_support}

    def frame_value(index):
        return sum(r.score for _, r in classified[index] if r.status == 'matched' and r.person_id in eligible)

    rep = max(range(len(frames)), key=lambda i: (frame_value(i), len(classified[i])), default=0)

    results, placed = [], set()
    for face, result in classified[rep]:
        if result.status == 'matched' and result.person_id not in eligible:
            result.status, result.person_id = 'no_match', None  # seen too briefly to trust
        if result.status == 'matched':
            hits = seen[result.person_id]
            result.score = float(np.mean([r.score for _, _, r in hits]))
            result.support = len({i for i, _, _ in hits})
            placed.add(result.person_id)
        results.append(place(face, result, rep))
    results.sort(key=lambda r: r.box[0])

    for pid in sorted(eligible - placed):  # identified in the video, but not in the annotated frame
        hits = seen[pid]
        _, _, best = max(hits, key=lambda h: h[2].score)
        results.append(FaceResult(
            'matched', frame_index=best.frame_index, box=None, person_id=pid, candidate_id=pid,
            score=float(np.mean([r.score for _, _, r in hits])), runner_up_score=best.runner_up_score,
            support=len({i for i, _, _ in hits}), candidates=best.candidates))
    return results, rep, faces_detected
