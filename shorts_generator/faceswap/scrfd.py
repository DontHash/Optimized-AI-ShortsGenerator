"""SCRFD face-detection output decoding — pure numpy, no ONNX dependency.

`decode_predictions` turns raw SCRFD (buffalo_l ``det_10g.onnx``) network
outputs into absolute bounding boxes + 5-point landmarks in the network's
input space. The ONNX session itself is glued in pipeline.py so this module
stays unit-testable without models.

Model layout (verified against det_10g.onnx + Haar cascade ground truth):
- 3 detection heads (strides 8 / 16 / 32), 2 anchors per grid cell
- score is a flat ``(cells * 2, 1)`` column, **cell-major** with interleaved
  anchors (index = cell * 2 + anchor)
- bbox/kps distances are in **stride units** — multiply by stride for pixels

Landmark order follows the SCRFD convention: left eye, right eye, nose,
left mouth corner, right mouth corner.
"""
from typing import Dict, List, Sequence

import numpy as np

Face = Dict[str, np.ndarray]  # {"bbox": (4,) x1y1x2y2, "kps": (5, 2)}


def distance2bbox(points: np.ndarray, distance: np.ndarray) -> np.ndarray:
    """points: (N, 2) anchor centers (pixels); distance: (N, 4) -> x1y1x2y2."""
    x1 = points[:, 0] - distance[:, 0]
    y1 = points[:, 1] - distance[:, 1]
    x2 = points[:, 0] + distance[:, 2]
    y2 = points[:, 1] + distance[:, 3]
    return np.stack([x1, y1, x2, y2], axis=-1)


def distance2kps(points: np.ndarray, distance: np.ndarray) -> np.ndarray:
    """points: (N, 2) anchor centers; distance: (N, 10) -> (N, 5, 2) landmarks."""
    kps = np.empty((points.shape[0], 5, 2), dtype=np.float32)
    for i in range(5):
        kps[:, i, 0] = points[:, 0] + distance[:, i * 2]
        kps[:, i, 1] = points[:, 1] + distance[:, i * 2 + 1]
    return kps


def _decode_head(
    scores: np.ndarray,
    bboxes: np.ndarray,
    kps: np.ndarray,
    dim: int,
    stride: int,
    conf_threshold: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Decode one head into (boxes (N, 4), landmarks (N, 5, 2), face_scores (N,))."""
    face_scores = np.asarray(scores).reshape(-1, 1)[:, 0]
    keep = np.argwhere(face_scores > conf_threshold).reshape(-1)
    if keep.size == 0:
        return np.empty((0, 4)), np.empty((0, 5, 2)), np.empty((0,))

    cell = keep // 2  # cell-major layout: index = cell * 2 + anchor
    x = (cell % dim) * stride
    y = (cell // dim) * stride
    centers = np.stack([x, y], axis=-1).astype(np.float32)

    boxes = distance2bbox(centers, np.asarray(bboxes)[keep] * stride)
    landmarks = distance2kps(centers, np.asarray(kps)[keep] * stride)
    return boxes, landmarks, face_scores[keep]


def decode_predictions(
    heads: Sequence[Dict[str, np.ndarray]],
    conf_threshold: float = 0.5,
    nms_threshold: float = 0.4,
) -> List[Face]:
    """Decode SCRFD FPN heads into faces in network-input pixel space.

    Each head is {"scores", "bboxes", "kps", "dim", "stride"} as emitted by
    the ONNX session (anchors-major flat arrays, distances in stride units).
    """
    boxes_all: list[np.ndarray] = []
    kps_all: list[np.ndarray] = []
    scores_all: list[np.ndarray] = []

    for head in heads:
        boxes, landmarks, face_scores = _decode_head(
            head["scores"], head["bboxes"], head["kps"],
            int(head["dim"]), int(head["stride"]), conf_threshold,
        )
        boxes_all.append(boxes)
        kps_all.append(landmarks)
        scores_all.append(face_scores)

    boxes = np.vstack(boxes_all) if boxes_all else np.empty((0, 4))
    landmarks = np.vstack(kps_all) if kps_all else np.empty((0, 5, 2))
    face_scores = np.concatenate(scores_all) if scores_all else np.empty((0,))
    if boxes.shape[0] == 0:
        return []

    # clamp to the input space, then non-max suppression
    boxes[:, 0::2] = np.clip(boxes[:, 0::2], 0, None)
    boxes[:, 1::2] = np.clip(boxes[:, 1::2], 0, None)

    indices: np.ndarray = np.arange(len(boxes))
    try:
        import cv2

        xywh = np.stack(
            [boxes[:, 0], boxes[:, 1], boxes[:, 2] - boxes[:, 0], boxes[:, 3] - boxes[:, 1]],
            axis=-1,
        )
        nms = cv2.dnn.NMSBoxes(
            xywh.tolist(), face_scores.tolist(), conf_threshold, nms_threshold
        )
        indices = np.asarray(nms, dtype=np.int64).reshape(-1)
    except Exception:  # noqa: BLE001 — no cv2? keep everything above threshold
        pass

    return [
        {"bbox": boxes[i].copy(), "kps": landmarks[i].copy()}
        for i in indices
    ]
