"""Unit tests for the face-swap engine — pure math only, no models/network."""
from pathlib import Path

import numpy as np
import pytest

from shorts_generator.faceswap import models, pipeline, scrfd


class TestScrfdDecode:
    def _head(self, dim, stride, scores, bboxes, kps):
        return {"scores": scores, "bboxes": bboxes, "kps": kps, "dim": dim, "stride": stride}

    def test_decode_single_face(self):
        dim, stride = 2, 4
        cells = dim * dim
        # cell-major layout: index = cell * 2 + anchor
        scores = np.zeros((cells * 2, 1), dtype=np.float32)
        bboxes = np.zeros((cells * 2, 4), dtype=np.float32)
        kps = np.zeros((cells * 2, 10), dtype=np.float32)
        idx = 0 * 2 + 0  # anchor 0, cell 0 -> center (0, 0)
        scores[idx, 0] = 0.9
        bboxes[idx] = [1.0, 2.0, 3.0, 4.0]  # stride units -> *4 pixels
        kps[idx] = [1, 1, 2, 2, 3, 3, 4, 4, 5, 5]

        faces = scrfd.decode_predictions([self._head(dim, stride, scores, bboxes, kps)])
        assert len(faces) == 1
        face = faces[0]
        np.testing.assert_allclose(face["bbox"], [0.0, 0.0, 12.0, 16.0], atol=1e-4)
        expected_kps = [[4, 4], [8, 8], [12, 12], [16, 16], [20, 20]]
        np.testing.assert_allclose(face["kps"], expected_kps, atol=1e-4)

    def test_decode_anchor_one(self):
        dim, stride = 2, 4
        cells = dim * dim
        scores = np.zeros((cells * 2, 1), dtype=np.float32)
        bboxes = np.zeros((cells * 2, 4), dtype=np.float32)
        kps = np.zeros((cells * 2, 10), dtype=np.float32)
        idx = 3 * 2 + 1  # anchor 1, cell 3 -> center (4, 4)
        scores[idx, 0] = 0.9
        bboxes[idx] = [0.5, 1.0, 0.5, 1.0]  # *4 = [2, 4, 2, 4]
        faces = scrfd.decode_predictions([self._head(dim, stride, scores, bboxes, kps)])
        assert len(faces) == 1
        np.testing.assert_allclose(faces[0]["bbox"], [2.0, 0.0, 6.0, 8.0], atol=1e-4)

    def test_decode_multi_head(self):
        dim, stride = 2, 4
        cells = dim * dim
        empty = np.zeros((cells * 2, 1), dtype=np.float32)
        empty_b = np.zeros((cells * 2, 4), dtype=np.float32)
        empty_k = np.zeros((cells * 2, 10), dtype=np.float32)
        head1 = self._head(dim, stride, empty, empty_b, empty_k)
        scores2 = np.zeros((cells * 2, 1), dtype=np.float32)
        scores2[1 * 2 + 0, 0] = 0.95  # anchor 0, cell 1 -> center (4, 0)
        head2 = self._head(dim, stride, scores2, empty_b, empty_k)
        faces = scrfd.decode_predictions([head1, head2])
        assert len(faces) == 1
        np.testing.assert_allclose(faces[0]["bbox"], [4.0, 0.0, 4.0, 0.0], atol=1e-4)

    def test_decode_low_confidence_dropped(self):
        dim, stride = 2, 4
        cells = dim * dim
        scores = np.zeros((cells * 2, 1), dtype=np.float32)
        scores[:, 0] = 0.01
        faces = scrfd.decode_predictions([
            self._head(dim, stride, scores, np.zeros((cells * 2, 4)), np.zeros((cells * 2, 10))),
        ])
        assert faces == []


class TestAffine:
    def test_identity_mapping(self):
        kps = np.array([[0, 0], [1, 0], [0.5, 1], [0, 2], [1, 2]], dtype=np.float32)
        matrix = pipeline.estimate_affine(kps, kps)
        assert matrix is not None
        np.testing.assert_allclose(matrix, [[1, 0, 0], [0, 1, 0]], atol=1e-3)

    def test_shifted_mapping(self):
        src = np.array([[0, 0], [1, 0], [0.5, 1], [0, 2], [1, 2]], dtype=np.float32)
        dst = src + np.array([10.0, -5.0])
        matrix = pipeline.estimate_affine(src, dst)
        assert matrix is not None
        np.testing.assert_allclose(matrix, [[1, 0, 10], [0, 1, -5]], atol=1e-3)

    def test_degenerate_returns_none(self):
        pts = np.array([[0, 0], [0, 0], [0, 0], [0, 0], [0, 0]], dtype=np.float32)
        assert pipeline.estimate_affine(pts, pts) is None


class TestMaskAndBlend:
    def test_mask_shape_and_range(self):
        mask = pipeline.swap_mask()
        assert mask.shape == (128, 128, 1)
        assert mask.min() >= 0.0 and mask.max() <= 1.0
        assert mask[64, 64, 0] == pytest.approx(1.0, abs=0.01)

    def test_paste_back_identical_patch_keeps_frame(self):
        frame = np.full((64, 64, 3), 120, dtype=np.uint8)
        patch = np.full((64, 64, 3), 120, dtype=np.uint8)
        identity = np.array([[1, 0, 0], [0, 1, 0]], dtype=np.float32)
        out = pipeline.paste_back(frame, patch, patch, identity)
        np.testing.assert_array_equal(out, frame)

    def test_paste_back_changes_frame_in_mask_region(self):
        frame = np.full((128, 128, 3), 120, dtype=np.uint8)
        patch = np.full((128, 128, 3), 255, dtype=np.uint8)
        identity = np.array([[1, 0, 0], [0, 1, 0]], dtype=np.float32)
        out = pipeline.paste_back(frame, patch, np.zeros((128, 128, 3), np.uint8), identity)
        assert out.dtype == np.uint8
        assert out.shape == frame.shape
        # the central face region must have been replaced (masked + warped)
        center = out[48:80, 48:80].astype(np.int16)
        assert center.mean() > 150

    def test_paste_back_uses_diff_feathering(self):
        """The fake_diff channel must actually drive the blend (was dead code):
        an identical patch over an identical crop leaves the frame untouched,
        even where the white warp mask claims full coverage."""
        frame = np.full((128, 128, 3), 120, dtype=np.uint8)
        patch = np.full((128, 128, 3), 120, dtype=np.uint8)  # same as frame
        identity = np.array([[1, 0, 0], [0, 1, 0]], dtype=np.float32)
        out = pipeline.paste_back(frame, patch, frame, identity)
        np.testing.assert_array_equal(out, frame)

    def test_paste_back_similar_patch_gives_soft_edges(self):
        """A patch that is mostly identical to the frame (only nose differs)
        must blend smoothly: far-from-mask pixels stay original, so the
        transition is feathered rather than a hard blob."""
        frame = np.full((128, 128, 3), 0, dtype=np.uint8)
        patch = np.full((128, 128, 3), 0, dtype=np.uint8)
        patch[60:68, 60:68] = 255  # small difference at the nose
        target = np.zeros_like(frame)
        identity = np.array([[1, 0, 0], [0, 1, 0]], dtype=np.float32)
        out = pipeline.paste_back(frame, patch, target, identity)
        assert out[10, 10].tolist() == [0, 0, 0]  # outside the mask
        assert out[64, 64][0] >= 240  # inside the diff blob (blurred peak)

    def test_project_latent_preserves_shape_and_norm(self):
        rng = np.random.default_rng(0)
        emb = rng.standard_normal(512).astype(np.float32)
        emb /= np.linalg.norm(emb)
        emap = rng.standard_normal((512, 512)).astype(np.float32)
        latent = pipeline.project_latent(emb, emap)
        assert latent.shape == (1, 512)
        assert latent.dtype == np.float32
        assert np.linalg.norm(latent) == pytest.approx(1.0, abs=1e-3)


class TestFaces:
    def test_largest_face(self):
        small = {"bbox": np.array([0, 0, 10, 10])}
        big = {"bbox": np.array([0, 0, 40, 40])}
        assert pipeline.largest_face([small, big]) is big
        assert pipeline.largest_face([]) is None


class TestFaceTracker:
    def test_first_detection_used_as_is(self):
        tr = pipeline.FaceTracker()
        kps = np.array([[1, 2], [3, 4], [5, 6], [7, 8], [9, 10]], np.float32)
        assert tr.update(kps, (64, 64)) is not None
        np.testing.assert_allclose(tr._smooth, kps)

    def test_heavy_smoothing_when_still(self):
        tr = pipeline.FaceTracker(smooth_min=0.35, smooth_gain=0.0)
        kps = np.array([[0, 0], [10, 0], [5, 10], [0, 20], [10, 20]], np.float32)
        tr.update(kps, (64, 64))
        # sub-pixel jitter on a still face is strongly suppressed (alpha=0.35)
        tr.update(kps + 1.0, (64, 64))
        assert np.abs(tr._smooth - kps).max() == pytest.approx(0.35, abs=1e-3)

    def test_near_1to1_on_fast_motion(self):
        tr = pipeline.FaceTracker(smooth_min=0.35, smooth_gain=0.12)
        kps = np.array([[0, 0], [10, 0], [5, 10], [0, 20], [10, 20]], np.float32)
        tr.update(kps, (64, 64))
        # big jump => alpha -> 1.0 => smooth follows almost exactly
        tr.update(kps + 10.0, (64, 64))
        assert np.abs(tr._smooth - (kps + 10.0)).max() == pytest.approx(0.0, abs=1.0)

    def test_default_still_face_alpha(self):
        tr = pipeline.FaceTracker()
        kps = np.array([[0, 0], [10, 0], [5, 10], [0, 20], [10, 20]], np.float32)
        tr.update(kps, (64, 64))
        tr.update(kps, (64, 64))  # no motion at all
        assert tr.smooth_min <= 0.4  # still uses heavy smoothing

    def test_decays_on_miss_then_skips(self):
        tr = pipeline.FaceTracker(stale_limit=2)
        kps = np.array([[0, 0], [10, 0], [5, 10], [0, 20], [10, 20]], np.float32)
        tr.update(kps, (64, 64))
        assert tr.update(None, (64, 64)) is not None  # stale 1
        assert tr.update(None, (64, 64)) is not None  # stale 2 (limit)
        assert tr.update(None, (64, 64)) is None      # stale 3 -> skip

    def test_recovers_after_misses(self):
        tr = pipeline.FaceTracker(stale_limit=1)
        kps = np.array([[0, 0], [10, 0], [5, 10], [0, 20], [10, 20]], np.float32)
        tr.update(None, (64, 64))  # miss before any detection
        assert tr.update(None, (64, 64)) is None      # still nothing to reuse
        got = tr.update(kps, (64, 64))
        np.testing.assert_allclose(got, kps)

    def test_clips_off_frame_landmarks(self):
        tr = pipeline.FaceTracker()
        kps = np.array([[-5, 3], [100, 4], [5, 6], [7, 8], [9, 1000]], np.float32)
        got = tr.update(kps, (64, 64))
        assert got.min() >= 0.0
        assert got.max() <= 64.0


class TestModels:
    def test_model_dir_env_override(self, monkeypatch):
        monkeypatch.setenv("FACESWAP_MODELS_DIR", "C:/tmp/fsw")
        assert models.model_dir() == Path("C:/tmp/fsw")

    def test_model_dir_default(self, monkeypatch):
        monkeypatch.delenv("FACESWAP_MODELS_DIR", raising=False)
        assert models.model_dir().name == "faceswap"

    def test_is_available_false_when_missing(self, monkeypatch, tmp_path):
        monkeypatch.setenv("FACESWAP_MODELS_DIR", str(tmp_path))
        assert not models.is_available()
