"""Single-pass ffmpeg renderer for 9:16 shorts.

One filter graph decodes the source, splits it into EDL segments, crops/scales
each segment, concatenates video and audio, applies fades, burns captions and
normalizes loudness — then one encoder pass writes the final MP4. This replaces
the old N-segment encodes + concat-copy + caption re-encode path.
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
from dataclasses import replace
from typing import Callable, List, Optional, Tuple

from .encoder import choose_encoder, video_args
from .plan import RenderPlan

ProgressCb = Callable[[float], None]

_HDR_CHAIN = (
    "zscale=t=linear:npl=100,"
    "tonemap=hable:desat=0,"
    "zscale=t=bt709:m=bt709:p=bt709:r=tv"
)


class RenderCancelled(RuntimeError):
    """Raised when a render is cancelled by the user."""


class RenderError(RuntimeError):
    """Raised when ffmpeg fails; includes the tail of its log."""


def _filter_path(path: str) -> str:
    return path.replace("\\", "/").replace(":", "\\:").replace("'", r"\'")


def _crop_filter(crop: dict) -> str:
    return f"crop={int(crop['w'])}:{int(crop['h'])}:{int(crop['x'])}:{int(crop['y'])}"


def build_filter_graph(plan: RenderPlan) -> Tuple[str, str, Optional[str], float]:
    """Build the filter_complex string. Pure function; safe to unit test.

    Returns ``(graph, video_label, audio_label_or_None, expected_duration)``.
    """
    if not plan.segments:
        raise ValueError("render plan has no segments")
    total = plan.duration
    if total <= 0:
        raise ValueError("render plan has zero duration")

    n = len(plan.segments)
    first = plan.first_start
    w, h, fps = int(plan.width), int(plan.height), int(plan.fps)
    chains: List[str] = []

    def _rel(seg) -> Tuple[float, float]:
        return (
            max(0.0, float(seg.start) - first),
            max(0.0, float(seg.end) - first),
        )

    if n == 1:
        a, b = _rel(plan.segments[0])
        chains.append(
            f"[0:v]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS,"
            f"{_crop_filter(plan.segments[0].crop)},"
            f"scale={w}:{h}:flags=lanczos,setsar=1,fps={fps}[vbase]"
        )
    else:
        chains.append(f"[0:v]split={n}" + "".join(f"[v{i}]" for i in range(n)))
        for i, seg in enumerate(plan.segments):
            a, b = _rel(seg)
            chains.append(
                f"[v{i}]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS,"
                f"{_crop_filter(seg.crop)},"
                f"scale={w}:{h}:flags=lanczos,setsar=1,fps={fps}[vx{i}]"
            )
        chains.append(
            "".join(f"[vx{i}]" for i in range(n))
            + f"concat=n={n}:v=1:a=0[vbase]"
        )

    vlabel = "vbase"
    if plan.hdr:
        chains.append(f"[{vlabel}]{_HDR_CHAIN}[vtone]")
        vlabel = "vtone"

    if plan.fade > 0:
        fade = min(float(plan.fade), total / 2.0)
        fade_out = max(0.0, total - fade)
        chains.append(
            f"[{vlabel}]fade=t=in:st=0:d={fade:.3f},"
            f"fade=t=out:st={fade_out:.3f}:d={fade:.3f}[vfade]"
        )
        vlabel = "vfade"

    if plan.ass_path and os.path.isfile(plan.ass_path):
        chains.append(f"[{vlabel}]ass='{_filter_path(plan.ass_path)}'[vsub]")
        vlabel = "vsub"

    chains.append(f"[{vlabel}]format=yuv420p[vout]")

    alabel: Optional[str] = None
    if plan.audio:
        if n == 1:
            a, b = _rel(plan.segments[0])
            chains.append(
                f"[0:a]atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS[abase]"
            )
        else:
            chains.append(f"[0:a]asplit={n}" + "".join(f"[a{i}]" for i in range(n)))
            for i, seg in enumerate(plan.segments):
                a, b = _rel(seg)
                chains.append(
                    f"[a{i}]atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS[ax{i}]"
                )
            chains.append(
                "".join(f"[ax{i}]" for i in range(n))
                + f"concat=n={n}:v=0:a=1[abase]"
            )

        alabel = "abase"
        if plan.fade > 0:
            fade = min(float(plan.fade), total / 2.0)
            fade_out = max(0.0, total - fade)
            chains.append(
                f"[{alabel}]afade=t=in:st=0:d={fade:.3f},"
                f"afade=t=out:st={fade_out:.3f}:d={fade:.3f}[afade]"
            )
            alabel = "afade"

        chains.append(
            f"[{alabel}]loudnorm=I={plan.loudness_lufs}:"
            f"TP={plan.true_peak_db}:LRA=11[aout]"
        )
        alabel = "aout"

    return ";".join(chains), "[vout]", (f"[{alabel}]" if alabel else None), total


class _ProgressReader(threading.Thread):
    """Read ffmpeg's merged stdout/stderr without blocking the cancel loop."""

    def __init__(self, stream, total: float, callback: Optional[ProgressCb]):
        super().__init__(daemon=True)
        self._stream = stream
        self._total = max(0.001, float(total))
        self._callback = callback
        self.logs: List[str] = []

    def run(self):
        for raw in self._stream:
            line = raw.strip()
            if not line:
                continue
            if line.startswith(("out_time_us=", "out_time_ms=")):
                try:
                    seconds = float(line.split("=", 1)[1]) / 1_000_000.0
                except ValueError:
                    continue
                if self._callback:
                    try:
                        self._callback(max(0.0, min(1.0, seconds / self._total)))
                    except Exception:  # noqa: BLE001 — progress must not kill a render
                        pass
            elif line == "progress=end":
                if self._callback:
                    try:
                        self._callback(1.0)
                    except Exception:  # noqa: BLE001
                        pass
            elif not line.startswith(("progress=", "frame=", "fps=", "bitrate=",
                                      "total_size=", "speed=", "out_time=",
                                      "dup_frames=", "drop_frames=")):
                self.logs.append(line)
                if len(self.logs) > 80:
                    del self.logs[:40]


def _terminate(proc: subprocess.Popen) -> None:
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        try:
            proc.kill()
            proc.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            pass


def _render_once(
    plan: RenderPlan,
    progress_cb: Optional[ProgressCb],
    cancel_event: Optional[threading.Event],
    timeout: Optional[float],
) -> str:
    if cancel_event is not None and cancel_event.is_set():
        raise RenderCancelled("render cancelled")
    graph, vlabel, alabel, total = build_filter_graph(plan)
    os.makedirs(os.path.dirname(plan.output) or ".", exist_ok=True)
    part = plan.output + ".part.mp4"
    encoder = choose_encoder(plan.encoder)

    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{plan.first_start:.3f}",
        "-i", plan.source,
        "-filter_complex", graph,
        "-map", vlabel,
    ]
    if alabel:
        cmd += [
            "-map", alabel,
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        ]
    else:
        cmd += ["-an"]
    cmd += video_args(encoder, plan.crf)
    cmd += [
        "-max_muxing_queue_size", "2048",
        "-movflags", "+faststart",
        "-map_metadata", "-1",
        "-progress", "pipe:1", "-nostats",
        part,
    ]

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError as e:
        raise RenderError("ffmpeg not found on PATH") from e

    reader = _ProgressReader(proc.stdout, total, progress_cb)
    reader.start()
    started = time.monotonic()
    cancelled = False
    timed_out = False
    try:
        while proc.poll() is None:
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                _terminate(proc)
                break
            if timeout is not None and time.monotonic() - started > timeout:
                timed_out = True
                _terminate(proc)
                break
            time.sleep(0.15)
    finally:
        reader.join(timeout=5)
        if proc.poll() is None:
            _terminate(proc)

    if cancelled:
        _remove(part)
        raise RenderCancelled("render cancelled")
    if timed_out:
        _remove(part)
        raise RenderError(f"render timed out after {timeout:.0f}s")

    if proc.returncode != 0:
        tail = "\n".join(reader.logs[-20:]) or "ffmpeg failed"
        _remove(part)
        raise RenderError(tail)
    if not os.path.isfile(part):
        raise RenderError("ffmpeg completed but produced no output")

    os.replace(part, plan.output)
    if progress_cb:
        try:
            progress_cb(1.0)
        except Exception:  # noqa: BLE001
            pass
    return plan.output


def _remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def render_plan(
    plan: RenderPlan,
    progress_cb: Optional[ProgressCb] = None,
    cancel_event: Optional[threading.Event] = None,
    timeout: Optional[float] = None,
    _retry_encoder: bool = True,
    _retry_hdr: bool = True,
    _retry_audio: bool = True,
) -> str:
    """Render a plan, falling back from hardware/HDR/audio when needed."""
    try:
        return _render_once(plan, progress_cb, cancel_event, timeout)
    except RenderCancelled:
        raise
    except RenderError as e:
        message = str(e).lower()
        if _retry_encoder and plan.encoder != "libx264":
            print(f"[render] {choose_encoder(plan.encoder)} failed; retrying with libx264", flush=True)
            if progress_cb:
                progress_cb(0.0)
            return render_plan(
                replace(plan, encoder="libx264"),
                progress_cb, cancel_event, timeout,
                _retry_encoder=False, _retry_hdr=_retry_hdr, _retry_audio=_retry_audio,
            )
        if _retry_hdr and plan.hdr and any(
            token in message for token in ("zscale", "tonemap", "no such filter", "error initializing")
        ):
            print("[render] HDR tonemap failed; retrying without tonemapping", flush=True)
            if progress_cb:
                progress_cb(0.0)
            return render_plan(
                replace(plan, hdr=False),
                progress_cb, cancel_event, timeout,
                _retry_encoder=False, _retry_hdr=False, _retry_audio=_retry_audio,
            )
        if _retry_audio and plan.audio and any(
            token in message for token in ("audio", "stream specifier", "matches no streams")
        ):
            print("[render] audio graph failed; retrying without audio", flush=True)
            if progress_cb:
                progress_cb(0.0)
            return render_plan(
                replace(plan, audio=False),
                progress_cb, cancel_event, timeout,
                _retry_encoder=False, _retry_hdr=False, _retry_audio=False,
            )
        raise
