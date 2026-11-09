"""Local face-swap engine — single-person videos, reference-image driven.

Swap a face from a photo into any single-person video entirely on your
machine (ONNX Runtime + OpenCV + ffmpeg; nothing is uploaded). Models are
downloaded once into ``models/faceswap/`` on first use.

CLI::

    python -m shorts_generator.faceswap video.mp4 face.jpg -o out.mp4 --device auto
    clipclipper-faceswap video.mp4 face.jpg -o out.mp4
"""
import argparse
import os
import sys

from .models import ensure_models, model_dir
from .pipeline import FaceSwapError, swap_video

__all__ = ["FaceSwapError", "ensure_models", "model_dir", "swap_video"]


def _model_progress(label: str, done: int, total: int) -> None:
    if total:
        pct = int(100 * done / total)
        print(f"  [model] {label}  {pct}%", file=sys.stderr, flush=True)
    else:
        print(f"  [model] {label} …", file=sys.stderr, flush=True)


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Swap a reference face into a single-person video (local ONNX).",
    )
    parser.add_argument("video", help="input video file")
    parser.add_argument("face", help="reference image with the face to use")
    parser.add_argument("-o", "--output", default=None,
                        help="output path (default: <video dir>/<stem>_swapped.mp4)")
    parser.add_argument("--device", choices=["auto", "cpu", "gpu"],
                        default=os.getenv("FACESWAP_DEVICE", "auto"))
    parser.add_argument("--force-models", action="store_true",
                        help="re-download the ONNX models even if present")
    args = parser.parse_args(argv)

    try:
        ensure_models(_model_progress, force=args.force_models)
        out = args.output or os.path.join(
            os.path.dirname(os.path.abspath(args.video)),
            os.path.splitext(os.path.basename(args.video))[0] + "_swapped.mp4",
        )
        result = swap_video(args.video, args.face, out, device=args.device,
                            progress_cb=lambda i, n: print(
                                f"\r  frame {i}/{n or '?'}", end="", file=sys.stderr, flush=True))
        print()
        print(f"OK  {result['out_path']}")
        print(f"    {result['frames']} frames ({result['swapped_frames']} swapped) "
              f"{result['width']}x{result['height']} @ {result['fps']:.1f}fps")
        return 0
    except FaceSwapError as e:
        print(f"FAIL  {e}", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001 — CLI must surface any failure cleanly
        print(f"FAIL  {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
