"""Frame-by-frame face swap for single-person videos.

Flow per frame: detect the largest face (SCRFD det_10g) -> align a 128x128
crop -> run inswapper_128 with the reference embedding -> blend via a
soft ellipse mask -> paste back. Frames stream into ffmpeg (rawvideo pipe)
so the output keeps the original audio, fps, and resolution.

The pure-math helpers (``estimate_affine``, ``swap_mask``, ``paste_back``)
have no model dependency and are unit-tested; the ONNX sessions are created
lazily so importing this module never requires models or onnxruntime.
"""
import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from . import models
from .scrfd import decode_predictions

DET_SIZE = 640
CROP_SIZE = 128
EMBED_SIZE = 112
CONF_THRESHOLD = 0.5
STALE_LIMIT = 6      # keep the last landmarks for N frames after a detection miss
# Adaptive EMA smoothing of per-frame detections: while the detected face
# barely moves (sub-pixel detection noise) the landmarks are heavily smoothed
# to kill flicker; when it moves a lot the previous frame's landmarks are
# trusted almost 1:1 so a fast head-turn never lags the paste behind the face.
SMOOTH_MIN = 0.35    # alpha when the face is completely still
SMOOTH_GAIN = 0.12   # extra alpha per px of inter-detection motion (clamped)

# ArcFace 5-point template at 112x112 (left eye, right eye, nose,
# left mouth corner, right mouth corner). For 128x128 crops insightface
# shifts the template 8 px in x (see face_align.estimate_norm).
_ARCFACE_112 = np.array(
    [
        [38.2946, 51.6963],
        [73.5318, 51.5014],
        [56.0252, 71.7366],
        [41.5493, 92.3655],
        [70.7299, 92.2041],
    ],
    dtype=np.float32,
)
ARCFACE_DST = (_ARCFACE_112 + np.array([8.0, 0.0])) * (CROP_SIZE / EMBED_SIZE)


class FaceSwapError(RuntimeError):
    """Raised for user-facing face-swap failures (no face, bad input...)."""


class FaceTracker:
    """Per-frame landmark tracker: adaptive EMA smoothing, decays on misses.

    Detection every frame removes the classic reuse drift that made the
    swapped face detach/ghost between re-detections (up to 100+ px on moving
    heads). The EMA adapts to motion — heavy smoothing on a still face kills
    detection flicker, near-1:1 tracking on fast motion prevents lag. When a
    frame has no face, the last landmark is kept for up to ``stale_limit``
    frames (then the swap is skipped rather than misapplied).

    Pure numpy — unit-tested without models.
    """

    def __init__(self, stale_limit: int = STALE_LIMIT,
                 smooth_min: float = SMOOTH_MIN, smooth_gain: float = SMOOTH_GAIN):
        self.stale_limit = stale_limit
        self.smooth_min = smooth_min
        self.smooth_gain = smooth_gain
        self._smooth: Optional[np.ndarray] = None
        self._prev_det: Optional[np.ndarray] = None
        self._stale = 0

    def update(self, kps: Optional[np.ndarray], frame_wh) -> Optional[np.ndarray]:
        """Feed one frame's detection (or None); returns landmarks to use."""
        if kps is None:
            self._stale += 1
            if self._smooth is None or self._stale > self.stale_limit:
                return None
            return self._smooth.copy()

        kps = np.asarray(kps, dtype=np.float32)
        kps = np.clip(kps, 0, frame_wh)
        if self._smooth is None:
            self._smooth = kps.copy()
        else:
            if self._prev_det is not None:
                motion = float(np.abs(kps - self._prev_det).max())
                alpha = min(self.smooth_min + self.smooth_gain * motion, 1.0)
            else:
                alpha = 1.0
            self._smooth = alpha * kps + (1.0 - alpha) * self._smooth
        self._prev_det = kps.copy()
        self._stale = 0
        return self._smooth.copy()

    def reset(self):
        self._smooth = None
        self._prev_det = None
        self._stale = 0


# ------------------------------------------------------------------ helpers -
def estimate_affine(source_kps: np.ndarray, target_kps: np.ndarray) -> Optional[np.ndarray]:
    """Similarity transform mapping source landmarks -> target landmarks.

    Returns a 2x3 affine matrix or None when the points are degenerate.
    """
    import cv2

    source_kps = np.asarray(source_kps, dtype=np.float32)
    target_kps = np.asarray(target_kps, dtype=np.float32)
    if source_kps.shape != (5, 2) or target_kps.shape != (5, 2):
        return None
    matrix, _ = cv2.estimateAffinePartial2D(source_kps, target_kps, method=cv2.LMEDS)
    if matrix is None or not np.isfinite(matrix).all() or np.allclose(matrix, 0.0):
        matrix, _ = cv2.estimateAffine2D(source_kps, target_kps)
    if matrix is None or not np.isfinite(matrix).all() or np.allclose(matrix, 0.0):
        return None
    return matrix.astype(np.float32)


def swap_mask(size: int = CROP_SIZE, blur: float = 5.0, padding: int = 8) -> np.ndarray:
    """Soft (128x128, 1) mask covering the face, feathered at the edges."""
    import cv2

    mask = np.zeros((size, size), dtype=np.float32)
    center = (size // 2, size // 2)
    axes = (size // 2 - padding, size // 2 - padding - 4)
    cv2.ellipse(mask, center, axes, 0, 0, 360, 1.0, -1)
    blurred = cv2.GaussianBlur(mask, (0, 0), blur)
    return blurred[..., None]


def paste_back(frame: np.ndarray, patch: np.ndarray, target_crop: np.ndarray,
               affine_inv: np.ndarray) -> np.ndarray:
    """Blend `patch` back onto `frame` using a difference-driven feathered mask.

    Mirrors insightface's INSwapper paste: the mask is eroded/dilated from the
    white warp region and blurred; the swap is then feathered against the
    original frame with a soft-diff term (two-stage blend) so hair and glasses
    boundaries blend naturally instead of showing a hard ellipse seam. A light
    unsharp pass restores the sharpness inswapper softens.
    """
    import cv2

    h, w = frame.shape[:2]
    bgr_fake = cv2.warpAffine(patch, affine_inv, (w, h), borderValue=0.0)
    img_white = np.full(target_crop.shape[:2], 255.0, dtype=np.float32)
    img_white = cv2.warpAffine(img_white, affine_inv, (w, h), borderValue=0.0)
    fake_diff = np.abs(patch.astype(np.float32) - target_crop.astype(np.float32)).mean(axis=2)
    fake_diff = cv2.warpAffine(fake_diff, affine_inv, (w, h), borderValue=0.0)

    img_white[img_white > 20] = 255.0
    fake_diff[fake_diff < 10] = 0.0
    fake_diff[fake_diff >= 10] = 255.0
    img_mask = img_white

    mask_h_inds, mask_w_inds = np.where(img_mask == 255)
    mask_h = int(mask_h_inds.max()) - int(mask_h_inds.min())
    mask_w = int(mask_w_inds.max()) - int(mask_w_inds.min())
    mask_size = int(np.sqrt(mask_h * mask_w))
    k = max(mask_size // 10, 10)
    kernel = np.ones((k, k), np.uint8)
    img_mask = cv2.erode(img_mask, kernel, iterations=1)
    kernel = np.ones((2, 2), np.uint8)
    fake_diff = cv2.dilate(fake_diff, kernel, iterations=1)
    k = max(mask_size // 20, 5)
    blur_size = tuple(2 * i + 1 for i in (k, k))
    img_mask = cv2.GaussianBlur(img_mask, blur_size, 0)
    fake_diff = cv2.GaussianBlur(fake_diff, (11, 11), 0)

    img_mask = (img_mask / 255.0).astype(np.float32)[..., None]
    fake_diff = (fake_diff / 255.0).astype(np.float32)[..., None]

    # stage 1: feather the swapped face over the frame wherever it differs
    # from the original (keeps hair/glasses/background intact at the boundary)
    feathered = fake_diff * bgr_fake + (1.0 - fake_diff) * frame.astype(np.float32)
    # stage 2: the eroded face blob fully covers the swap core, soft at its edge
    blend = img_mask * feathered + (1.0 - img_mask) * frame.astype(np.float32)

    # subtle unsharp inside the face region — inswapper tends to soften faces
    if mask_size >= 64:
        sigma = max(mask_size / 200.0, 0.8)
        blurred = cv2.GaussianBlur(blend, (0, 0), sigma)
        sharp = blend + 0.45 * (blend - blurred)
        blend = img_mask * sharp + (1.0 - img_mask) * blend

    return np.clip(blend, 0, 255).astype(np.uint8)


# ------------------------------------------------------------------ model glue -
def _providers(device: str) -> list:
    """Execution-provider chain for a device choice.

    GPU support: CUDA (onnxruntime-gpu) or DirectML (onnxruntime-directml,
    any Windows DirectX-12 GPU — no CUDA toolkit needed). Auto picks the best
    available GPU provider, falling back to CPU.
    """
    from onnxruntime import get_available_providers

    available = get_available_providers()
    chain = []
    for name in ("CUDAExecutionProvider", "DmlExecutionProvider"):
        if name in available:
            chain.append(name)
    chain.append("CPUExecutionProvider")

    if device == "cpu":
        return ["CPUExecutionProvider"]
    if device == "gpu":
        gpu_chain = [p for p in chain if p != "CPUExecutionProvider"]
        if not gpu_chain:
            raise FaceSwapError(
                "No GPU provider found — install onnxruntime-gpu (CUDA) or "
                "onnxruntime-directml (Windows), or use --device cpu."
            )
        return gpu_chain + ["CPUExecutionProvider"]
    return chain  # auto


def _open_sessions(device: str, progress_cb=None) -> dict:
    from onnxruntime import InferenceSession

    paths = models.ensure_models(progress_cb=progress_cb)
    providers = _providers(device)
    return {
        "det": InferenceSession(str(paths["det_10g.onnx"]), providers=providers),
        "embed": InferenceSession(str(paths["w600k_r50.onnx"]), providers=providers),
        "swap": InferenceSession(str(paths["inswapper_128.onnx"]), providers=providers),
    }


def _blob(rgb: np.ndarray, size: int) -> np.ndarray:
    import cv2

    return cv2.dnn.blobFromImage(rgb, 1.0 / 128.0, (size, size), (127.5,) * 3, swapRB=False)


def detect_faces(session, frame_rgb: np.ndarray) -> list:
    """Largest-first list of {"bbox": (4,), "kps": (5, 2)} in frame pixels."""
    h, w = frame_rgb.shape[:2]
    blob = _blob(frame_rgb, DET_SIZE)
    outputs = session.run(None, {session.get_inputs()[0].name: blob})
    names = [o.name for o in session.get_outputs()]

    def pick(name: str, fallback: int):
        if name in names:
            return outputs[names.index(name)]
        return outputs[fallback]

    # multi-stride FPN (det_10g): 9 outputs ordered [scores x3, bboxes x3, kps x3]
    if len(outputs) == 9:
        heads = []
        for head in range(3):
            scores = outputs[head]
            cells = scores.shape[0] // 2
            dim = int(round(cells ** 0.5))
            stride = DET_SIZE // dim
            heads.append({
                "scores": scores,
                "bboxes": outputs[head + 3],
                "kps": outputs[head + 6],
                "dim": dim,
                "stride": stride,
            })
        faces = decode_predictions(heads, conf_threshold=CONF_THRESHOLD)
    else:
        # single-head fallback: (1, dim, dim, ch) outputs
        scores = pick("score", 2)
        dim = scores.shape[1]
        stride = DET_SIZE // dim
        heads = [{
            "scores": np.asarray(scores).reshape(-1, 2),
            "bboxes": np.asarray(pick("bbox", 0)).reshape(-1, 4),
            "kps": np.asarray(pick("kps", 1)).reshape(-1, 10),
            "dim": dim,
            "stride": stride,
        }]
        faces = decode_predictions(heads, conf_threshold=CONF_THRESHOLD)

    scale_x, scale_y = w / DET_SIZE, h / DET_SIZE
    for face in faces:
        face["bbox"][0::2] *= scale_x
        face["bbox"][1::2] *= scale_y
        face["kps"][:, 0] *= scale_x
        face["kps"][:, 1] *= scale_y
        face["kps"] = np.clip(face["kps"], 0, [w, h])
    return faces


def largest_face(faces: list) -> Optional[dict]:
    if not faces:
        return None
    return max(faces, key=lambda f: (f["bbox"][2] - f["bbox"][0]) * (f["bbox"][3] - f["bbox"][1]))


def compute_embedding(session, frame_rgb: np.ndarray, kps: np.ndarray) -> np.ndarray:
    """ArcFace embedding of the face aligned by its 5 landmarks (L2-normalized)."""
    import cv2

    affine = estimate_affine(kps, _ARCFACE_112)
    if affine is None:
        raise FaceSwapError("Could not align the reference face.")
    crop = cv2.warpAffine(frame_rgb, affine, (EMBED_SIZE, EMBED_SIZE), borderMode=cv2.BORDER_REFLECT)
    blob = _blob(crop, EMBED_SIZE)
    embedding = session.run(None, {session.get_inputs()[0].name: blob})[0]
    embedding = embedding.reshape(-1).astype(np.float32)
    norm = float(np.linalg.norm(embedding))
    if norm > 0:
        embedding = embedding / norm
    return embedding


def load_emap(model_path) -> np.ndarray:
    """The inswapper latent-projection matrix (last graph initializer).

    The swap model was trained to consume arcface embeddings projected through
    this learned matrix (a style-space mapping) — feeding the raw embedding
    makes the model ignore the source and reconstruct the target instead.
    """
    import onnx
    from onnx import numpy_helper

    graph = onnx.load(str(model_path)).graph
    return numpy_helper.to_array(graph.initializer[-1])


def project_latent(source_embedding: np.ndarray, emap: np.ndarray) -> np.ndarray:
    """Project a normed arcface embedding into the inswapper latent space."""
    latent = source_embedding.reshape(1, -1) @ emap
    norm = float(np.linalg.norm(latent))
    return (latent / norm if norm > 0 else latent).astype(np.float32)


def swap_face(session, frame_rgb: np.ndarray, kps: np.ndarray, latent: np.ndarray) -> np.ndarray:
    """Swap the face at `kps` (5, 2) in `frame_rgb` using the projected latent."""
    import cv2

    affine = estimate_affine(kps, ARCFACE_DST)
    if affine is None:
        return frame_rgb
    crop = cv2.warpAffine(frame_rgb, affine, (CROP_SIZE, CROP_SIZE), borderValue=0.0)
    # inswapper_128 expects raw pixels scaled to 0..1 (mean=0, std=255),
    # unlike the (x-127.5)/128 prep used by the detection/embedding models
    blob = (crop.astype(np.float32) / 255.0).transpose(2, 0, 1)[None]
    output = session.run(
        None,
        {"target": blob, "source": latent.reshape(1, -1).astype(np.float32)},
    )[0]
    # inswapper_128 emits float tensors in 0..1; NHWC (128, 128, 3) or NCHW (3, 128, 128)
    frame_out = output[0]
    if frame_out.shape == (3, CROP_SIZE, CROP_SIZE):
        frame_out = frame_out.transpose(1, 2, 0)
    swapped = np.clip(frame_out * 255.0, 0, 255).astype(np.uint8)

    inverse = cv2.invertAffineTransform(affine)
    return paste_back(frame_rgb, swapped, crop, inverse)


def _ffmpeg() -> str:
    binary = shutil.which("ffmpeg")
    if not binary:
        raise FaceSwapError("ffmpeg not found on PATH — required to encode the output.")
    return binary


# ------------------------------------------------------------------ engine -
def swap_video(
    video_path: str,
    ref_image_path: str,
    out_path: str,
    device: str = "auto",
    progress_cb: Optional[Callable[[int, int], None]] = None,
    frame_cb: Optional[Callable[[np.ndarray], None]] = None,
    is_cancelled: Optional[Callable[[], bool]] = None,
) -> dict:
    """Swap the reference face into a single-person video.

    Returns {"out_path", "frames", "width", "height", "fps", "seconds"}.
    """
    import cv2

    video_path = os.fspath(video_path)
    ref_path = os.fspath(ref_image_path)
    if not os.path.isfile(video_path):
        raise FaceSwapError(f"Video file not found: {video_path}")
    if not os.path.isfile(ref_path):
        raise FaceSwapError(f"Reference image not found: {ref_path}")

    sessions = _open_sessions(device)
    emap = load_emap(models.model_dir() / "inswapper_128.onnx")

    ref = cv2.imread(ref_path, cv2.IMREAD_COLOR)
    if ref is None:
        raise FaceSwapError(f"Could not read reference image: {ref_path}")
    ref_rgb = cv2.cvtColor(ref, cv2.COLOR_BGR2RGB)
    face = largest_face(detect_faces(sessions["det"], ref_rgb))
    if face is None:
        raise FaceSwapError("No face found in the reference image — use a clear, front-facing photo.")
    source_embedding = compute_embedding(sessions["embed"], ref_rgb, face["kps"])
    latent = project_latent(source_embedding, emap)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise FaceSwapError(f"Could not open video: {video_path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = _ffmpeg()
    cmd = [
        ffmpeg, "-y", "-loglevel", "error", "-nostats",
        "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{width}x{height}", "-r", f"{fps:.6f}",
        "-i", "pipe:0",
        "-i", video_path,
        "-map", "0:v:0", "-map", "1:a?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "160k",
        "-shortest",
        out_path,
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    if proc.stdin is None:
        raise FaceSwapError("Could not open the ffmpeg pipe.")

    def cancelled() -> bool:
        return bool(is_cancelled and is_cancelled())

    try:
        index = 0
        swapped_frames = 0
        tracker = FaceTracker()
        while True:
            if cancelled():
                break
            ok, frame = cap.read()
            if not ok or frame is None:
                break
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            # Detect each frame: SCRFD is cheap (the swap dominates), and
            # frozen landmarks drift catastrophically between detections.
            # The tracker EMA-smooths detections for a stable, flicker-free
            # paste and decays gracefully on missed frames.
            face = largest_face(detect_faces(sessions["det"], frame_rgb))
            kps = tracker.update(face["kps"] if face is not None else None, (width, height))
            if kps is not None:
                frame_rgb = swap_face(sessions["swap"], frame_rgb, kps, latent)
                swapped_frames += 1
            if frame_cb and index % 12 == 0:
                frame_cb(frame_rgb)
            out = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
            proc.stdin.write(out.tobytes())
            index += 1
            if progress_cb:
                progress_cb(index, total)
    except BrokenPipeError as e:
        raise FaceSwapError(f"ffmpeg failed to consume frames: {e}") from e
    finally:
        cap.release()
        try:
            proc.stdin.close()
        except BrokenPipeError:
            pass
        proc.wait()

    if cancelled():
        Path(out_path).unlink(missing_ok=True)
        raise FaceSwapError("Cancelled.")

    if not os.path.isfile(out_path) or os.path.getsize(out_path) == 0:
        raise FaceSwapError("ffmpeg produced no output — check the video codec.")

    return {
        "out_path": os.path.abspath(out_path),
        "frames": index,
        "swapped_frames": swapped_frames,
        "width": width,
        "height": height,
        "fps": fps,
        "seconds": index / fps if fps else 0.0,
    }
