# Revamp v2 — From Clip Finder to Drop-and-Go Shorts Studio

**Status:** proposed plan (audit + roadmap), 2026-11-09
**Implementation:** Phase 0 complete; Phase 1 core complete (single-pass renderer, progress/cancel, encoder fallback). Measured two-pass loudness and per-clip music remain refinements.
**Scope:** `Optimized-AI-ShortsGenerator` (ClipClipper)
**Related:** [REVAMP_PLAN.md](REVAMP_PLAN.md), [UPLIFT_PLAN.md](UPLIFT_PLAN.md), [EDITOR_MVP_SPEC.md](EDITOR_MVP_SPEC.md)

---

## 0. TL;DR

ClipClipper already has a genuinely good **clip-finding engine**: download → transcript →
replay/audio/chapter signals → LLM ranking → fusion → dedupe → `clips.json`. That is the hard,
differentiated part, and it should be preserved.

What it does **not** have is a product around that engine. Today it is a set of manual tools:
paste URL → wait → inspect cards → click render per clip → inspect the file in an external player
→ compile → configure OAuth → upload. Several visible defects make the output look amateur:

- face tracking silently falls back to center crop or cuts the intro because of a timebase bug;
- captions are burned at the wrong size/position from sentence-level SRT, and the word-level path
  is broken;
- every crop segment fades from black and is loudness-normalized separately;
- the app crashes on the second queue run;
- render state is lost on restart, so "Open File" and thumbnails are unreliable;
- there is no trim, caption edit, crop override, title edit, or final-short preview.

**The three bets of this revamp:**

1. **Fix correctness before adding features.** Most of the "this is broken" feeling comes from a
   small number of P0 render/lifecycle bugs, not from missing AI.
2. **Build one render engine and one correction editor.** Not an NLE. The AI makes the first 80%;
   the user fixes the last 20% in under two minutes and exports.
3. **Adopt small, permissively licensed OSS components** (YuNet, faster-whisper words, pysubs2,
   libass, PySceneDetect, ffmpeg, mpv) instead of forking a large OSS app or shipping AGPL models.

**Target experience:** paste a URL once, get 3–10 ranked vertical shorts, review them with keyboard
shortcuts, fix a cut or caption in under two minutes, export or upload — without leaving the app.

---

## 1. Honest audit

### 1.1 What already works (preserve it)

| Area | Evidence | Verdict |
|---|---|---|
| Download + cache + cookies | `shorts_generator/downloader.py` | Solid |
| Transcript (YouTube captions / faster-whisper) | `transcriber.py`, `downloader.py` | Solid, but word timestamps unused in the render path |
| Signal extraction (heatmap, chapters, audio energy, boundaries) | `signals.py` | Solid and dependency-light |
| LLM ranking + JSON repair + retries | `highlights.py`, `llm.py` | Solid mechanics |
| Fusion, peak expansion, semantic dedupe, SponsorBlock filter | `rerank.py` | Solid mechanics |
| Queue fault isolation + parallel workers | `queue.py` | Solid |
| Face swap tool | `shorts_generator/faceswap/` | Solid, separate product |
| TikTok downloader | `shorts_generator/tiktok.py` | Solid, narrow |
| UI shell, theme, console drawer, cards | `studio_app/` | Polished shell, thin product |
| Pure-logic tests | `tests/` | Useful, but no render integration tests |

### 1.2 P0 defects (verified in code)

These are the first fixes, because each one directly produces a broken or embarrassing short.

| # | Defect | Evidence | User-visible effect | Fix direction |
|---|---|---|---|---|
| 1 | **Face-crop timebase is wrong.** `sample_faces` returns absolute source timestamps; `plan_crop_segments` treats them as clip-relative; `render_shorts` adds `start` again. | `smartcrop.py:187-188`, `smartcrop.py:55-70`, `clipper.py:381-386`, `clipper.py:401` | For most clips (start > duration) the plan is discarded → center crop. For early clips the rendered window is shifted and the intro is dropped. Face tracking is effectively off. | Rebase samples to `t - start` before planning (`plan_crop_segments(samples, duration, origin=start)` or map in `render_shorts`). Add a regression test with `start=100`. |
| 2 | **Crop normalizer drops the intro and internal gaps.** It starts at the first segment, not 0, and does not fill gaps. | `clipper.py:168-195` | Short is shorter than the chosen clip, starts mid-word, captions/audio desync. Checked-in 49.3s clip vs 43.1s short is consistent with this. | Prepend `[0, first_start)` using the first x; fill each gap with the previous x; clamp to source duration. Test explicitly. |
| 3 | **Captions are oversized, near the top, and clipped.** `force_style Fontsize=80, MarginV=240` is applied to an SRT with no `PlayRes`; libass scales it against a 384×288 canvas. | `clipper.py:331-344`; checked-in `*_short_captioned.mp4` | Giant caption at the top of the frame, clipped at `y=0`, often a 7s sentence block. | Generate ASS with `PlayResX=1080, PlayResY=1920`, font 64–76, `MarginV≈360–420`, `WrapStyle`, `ScaledBorderAndShadow`; burn with `ass=`. Test caption pixels in the bottom safe zone. |
| 4 | **Word-level caption path silently returns zero cues.** `_video_assets` loads a `.words.srt` with `load_srt_file` (`text` key), then `chunk_words_to_cues` reads `w["word"]`. | `clip_card.py:210-229`, `clipper.py:270-280`, `transcriber.py:54-81` | When a word cache exists, captions disappear entirely instead of falling back. | Use `load_word_srt` or map `{"word": s["text"]}`; fall back to sentence SRT on empty. Add a test. |
| 5 | **Per-segment fade and loudnorm.** Every crop segment gets `fade=t=in:st=0` and its own `loudnorm`; parts are then concat-copied. | `clipper.py:209-222`, `clipper.py:395-414` | Black flash at every crop switch; audible level jumps; `N+1` encodes. | Fade only first/last program edges; normalize once on the final program; move to a single-pass renderer (Phase 1). |
| 6 | **Second queue run crashes.** `_clear_results` deletes `_empty` via `deleteLater`, then calls `self._empty.hide()` on the next run. | `shorts_creator_page.py:213-219` (same pattern `faceswap_page.py:396-402`) | One queue batch per app session; second Start raises `RuntimeError: Internal C++ object already deleted`. | Keep `_empty` alive and hidden; never delete it. Add worker `shutdown()`/wait before deleting cards. |
| 7 | **Render state, thumbnail, and "Open File" are inconsistent.** Paths live only in the in-memory clip dict; thumb name is reconstructed as `*_captioned.jpg`, but the renderer writes `*_short.jpg`; `_open_file` reads only `clip_path`. | `clip_card.py:349-360`, `clip_card.py:410-422`, `clipper.py:421-427` | After restart the card says "Render Short" again; "Open File" does nothing after a short render; thumbnail often missing. | Persist `short_path`/`thumb_path` in a `renders.json` sidecar (or `clips.json`), hydrate on load, use `short_path` as the open target and the renderer's returned `thumb_path`. |
| 8 | **Both tools share one queue file.** `SourcePanel` writes `output/studio_queue.json` regardless of mode and restore ignores the saved mode. | `queue_list.py:282-289`, `queue_list.py:333-352` | YouTube URLs appear in the TikTok queue and vice versa; last page wins. | One queue file per mode (`studio_queue_youtube.json`, `studio_queue_tiktok.json`) and restore by mode. |
| 9 | **The score is a relative rank, presented as a virality score.** `rank_normalize` maps the best to 1.0 and the worst to 0.0; one clip always scores 100. | `rerank.py:22-40`, `rerank.py:85-103` | A weak clip looks like a 100/100 hit; `min_score` is misleading. | Keep rank for ordering, expose separate "relative rank" and calibrated LLM confidence; display `#rank of N`; never fall back to `ranked[:1]` when `min_score` filters everything (return empty and say so). |
| 10 | **`--shorts` renders original-ratio MP4s first, then shorts.** | `main.py:102`, `pipeline.py:233-245` | Doubles render time and disk, and the intermediate files are unused. | When `shorts=True`, skip `render_clips`. On cached `clips.json`, render missing shorts only. |
| 11 | **No real progress or hard cancel.** Downloads use `noprogress`, Whisper/ffmpeg have no callbacks, per-card workers have no cancel. | `downloader.py:163`, `transcriber.py`, `clipper.py:214-235`, `clip_card.py:75-193` | Indeterminate UI; Stop waits for running work; closing the app can destroy running QThreads. | Add progress callbacks (`-progress pipe:1` for ffmpeg), determinate bars/ETA, terminate processes on cancel, wait for workers in `closeEvent`. |
| 12 | **Settings mostly freeze at import; Reload is a no-op; GUI-only values are not persisted.** | `config.py:8-19`, `shorts_creator_page.py:191-210`, `settings_panel.py:183-199` | "Applied on the next run" is false for most knobs; fade/upscale reset on restart; users must restart the app. | Read config dynamically at call time, persist GUI-only keys, repopulate controls on reload, show a restart banner only when required. |
| 13 | **Pipeline bypasses the better caption-track selector.** It uses `fetch_auto_subs` rather than `caption_tracks.choose_track`, and cache lookup does not check language. | `pipeline.py:137-143`, `downloader.py:603-647`, `caption_tracks.py:60-112` | A translated or previously cached track can become the transcript; language selection is unreliable. | Use `caption_tracks.choose_track`/`fetch_source_subs`; reject `tlang=` translations by default; cache per language. |
| 14 | **Compile can produce a non-Short.** `compile_shorts` concatenates all rendered shorts with `-c copy` and no duration/aspect validation. | `clipper.py:458-488`, `clip_card.py:550-596` | Three 60s clips become a 3-minute video that YouTube will not treat as a Short; mismatched inputs can break concat. | Upload per clip by default. If compiling, enforce ≤3 min/9:16, re-encode via concat filter, normalize audio. |
| 15 | **Music mix halves the voice.** `amix` defaults to `normalize=1`. | `clipper.py:476-481` | Dialogue drops by ~6 dB under music; no ducking, no looping. | `amix=normalize=0`, voice 1.0, music 0.15–0.25, `sidechaincompress`, `aloop`, fades, final limiter. |

### 1.3 Product gaps vs "drop and go"

| Missing capability | Why it matters | Target phase |
|---|---|---|
| One-click "Make Shorts" (analysis → render top N → manifest) | The current flow has 4+ manual steps after analysis | 2 |
| Multi-select and cross-video batch export | Users cannot render clips 1 and 3 only, or all videos at once | 2 |
| Manual trim / multi-segment EDL | AI boundaries are good, not perfect; every correction needs an external editor | 4 |
| Final-short preview | Preview plays the source, not the rendered 9:16 result | 4 |
| Caption text/timing/style editing | Misheard names and bad line breaks are the most common fix | 4 |
| Crop override / reframe modes | Face crop fails on multi-person, gameplay, and vertical sources | 3–4 |
| Hook/title/description editing + AI variants | Publishing is currently source-title + `#shorts` | 5 |
| Project persistence / autosave / crash recovery | Renders and edits vanish on restart | 2 |
| Progress, ETA, retry, hard cancel | Long videos feel hung; failures require re-adding URLs | 0–2 |
| Publish metadata, privacy, scheduling | Public-by-default upload with minimal metadata is risky | 5 |
| TikTok/Reels export path | The product name is Shorts, but distribution is multi-platform | 5 |

### 1.4 What the user actually experiences today

1. Paste URL, press Start. Download/transcribe/rank runs with an indeterminate spinner.
2. Cards appear. Score badges show 100/50/0 because the score is relative.
3. Click "Render Short 9:16" per clip. The renderer may center-crop (face bug), drop the intro
   (normalizer), and burn a giant top caption (PlayRes).
4. Open the file externally to see the result. The in-app preview shows the source video.
5. Compile or upload. The app restarts lose all render state; a second batch may crash.

**The engine is not the problem. The last mile is.**

---

## 2. Product target

### 2.1 The loop

```
Paste URL / drop file
        ↓
Analyze once (download, transcript, signals, ranking)
        ↓
Review 3–10 ranked shorts (9:16 preview, score, hook, reason)
        ↓
Correct quickly (trim, caption, crop, title) — optional
        ↓
Export selected / upload / schedule
```

**Time targets (mid-range laptop, CPU):**

| Stage | Target |
|---|---|
| 60 min video → ranked candidates | < 10 min with YouTube captions; < 20 min with Whisper `small` |
| Candidates → first rendered 60s short | < 90 s |
| Review + one correction + re-render | < 2 min |
| Batch export 5 shorts | < 8 min |
| Second run (cached source/transcript) | < 60 s to candidates |

### 2.2 Principles

1. **AI first draft, human last mile.** Do not ask the user to build a timeline from scratch.
2. **Correction editor, not an NLE.** Single video track + captions + optional music. No
   multi-track compositing, keyframes, colour grading, B-roll, or voice cloning in MVP.
3. **One render path.** CLI and GUI call the same `RenderPlan` engine. No duplicated ffmpeg logic.
4. **Deterministic, resumable, cancellable.** The same plan produces the same file; progress is
   visible; cancel is immediate; state survives restart.
5. **Local-first and honest.** No hidden cloud upload; clear model/license downloads; no fake scores.
6. **Permissive dependencies.** Base install stays torch-free; heavy extras are optional.

---

## 3. Target architecture

### 3.1 Module layout

```
shorts_generator/
  pipeline.py            analysis only: download → transcript → signals → rank → clips.json
  queue.py               batch analysis (unchanged contract)
  storage/
    project_store.py     SQLite project/clip/render state + autosave
  render/
    plan.py              ClipRecipe → RenderPlan (EDL, crop, captions, audio)
    ffmpeg.py            single-pass render, progress, cancel, encoder detection
    captions.py          ASS generation, style presets, line breaking
    thumbnail.py         cover frames, 1080×1920, text overlay
    encoder.py           h264_nvenc/qsv/amf/videotoolbox/libx264 detection
  reframe/
    detector.py          YuNet (OpenCV) + optional SFace re-ID
    tracker.py           IoU/EMA/One-Euro, hysteresis, scene resets
    planner.py           crop tracks (x, y, scale), multi-face policy, fallbacks
  publish/
    youtube.py           per-clip upload, metadata, thumbnail, SRT, publishAt
    tiktok.py            export preset + draft upload (Direct Post later)
studio_app/
  pages/                 home, shorts creator, tiktok, faceswap, settings
  editor/
    timeline.py          single-track EDL widget (segments, captions, audio)
    preview.py           mpv/libmpv preview (QMediaPlayer fallback)
    caption_editor.py    cue list, inline edit, retime, style
    crop_editor.py       mode selector + overlay
  services/
    render_service.py    Qt worker around render/render_plan
    publish_service.py   OAuth, upload queue
    preflight.py         ffmpeg/ffprobe/yt-dlp/API/model checks
```

### 3.2 Data model

`clips.json` remains the analysis contract. Add an optional `recipe` block so old files still work:

```json
{
  "rank": 1,
  "title": "The one mistake that cost me $50K",
  "start_time": 124.3,
  "end_time": 187.6,
  "recipe": {
    "segments": [{"src_in": 124.3, "src_out": 187.6}],
    "framing": {"mode": "auto", "crop_tracks": [], "manual_x": null},
    "captions": {"mode": "burn", "style_id": "bold_pop", "cues": []},
    "audio": {"source_gain": 1.0, "music_path": null, "music_gain": 0.18, "ducking": true},
    "overlays": []
  },
  "renders": [
    {"preset": "1080p", "path": "..._short.mp4", "thumb": "..._short.jpg", "created_at": "..."}
  ]
}
```

If `recipe` is absent, the renderer derives a single segment from `start_time`/`end_time` and an
automatic crop/caption plan. This keeps the CLI and old outputs working. Full schema and editor UX:
[EDITOR_MVP_SPEC.md](EDITOR_MVP_SPEC.md).

### 3.3 Render contract

**Input:** source path, EDL segments, crop plan per segment, caption cues + style, audio mix.

**Output:** MP4, 1080×1920 (or capped to avoid upscale), 30/60 fps, H.264 `yuv420p`,
AAC 48 kHz stereo 192 kbps, integrated loudness ≈ −14 LUFS, `+faststart`.

**One final encode.** The renderer builds a single `filter_complex`:

```
video: split=N → trim/setpts → crop/scale/fps → concat
audio: asplit=N → atrim/asetpts → concat
       → loudnorm (once) → optional music ducking
       → ass=captions.ass
       → one libx264/hardware encode
```

This removes per-segment fades/loudnorm, concat-copy incompatibilities, and second-generation
caption compression. If a filter graph with many segments becomes unwieldy, the fallback is
per-segment parts with **identical** encode settings + concat filter + one global audio/caption
pass — never concat-copy across heterogeneous inputs.

**Preview uses the same ASS file, crop parameters, canvas, and fps as the final render.** Preview
at 540p for speed; final at 1080p.

---

## 4. OSS decisions

Research date: 2026-11-09. Licenses move; verify the exact commit/model card before shipping.
This section is a decision aid, not legal advice.

### 4.1 Adopt now

| Area | Component | License | Why | Integration |
|---|---|---|---|---|
| Face detection | **OpenCV YuNet** (`cv2.FaceDetectorYN`) | MIT (model), Apache-2.0 (OpenCV) | Much better than Haar; landmarks; CPU; Windows; ~ms/frame; no torch | Replace `smartcrop.sample_faces`; download model on first use |
| Face re-ID | **OpenCV SFace** (optional) | Apache-2.0 | Keeps the same person across detections/cuts | Embedding distance + Hungarian assignment |
| Tracking | Simple IoU/EMA or **`trackers`** / `cv2.TrackerVit` | MIT/Apache-2.0 | Stable identity, fewer switches | Small tracker module; optional extra |
| Word timestamps | **faster-whisper** `word_timestamps=True` + **Silero VAD** | MIT / MIT | Already in stack; enables tight captions and speech-aware cuts | Pipeline asks for words once; cache `.words.json` |
| Caption model | **pysubs2** | MIT | ASS/SRT/VTT read/write; styles; robust | Build ASS from cues; no hand-rolled escaping |
| Caption render | **libass via ffmpeg** | ISC | Fast, reliable, karaoke/`\k` support, same renderer in mpv | Bundle ffmpeg with libass; test `ass` filter |
| Scene cuts | **PySceneDetect** (`scenedetect-headless`) | BSD-3-Clause | Reset tracking, avoid cuts mid-shot, better thumbnails | Optional extra; cache shot list |
| Audio | **ffmpeg loudnorm / silencedetect / sidechaincompress / alimiter** | LGPL/GPL build dependent | Built-in; no Python dependency; correct EBU R128 | Two-pass loudnorm; ducking for music |
| Preview (editor) | **mpv/libmpv** with an **LGPL build** | GPLv2+ default; LGPLv2.1+ with `-Dgpl=false` | Frame-accurate seek/step, ASS rendering, hardware decode | `MpvRenderContext` in `QOpenGLWidget`; QMediaPlayer fallback |
| Thumbnails | **Pillow** | MIT-CMU | Cover frames, text overlays, 1080×1920 export | Optional extra; only used by thumbnail path |
| Line breaking | **uniseg** | MIT | Unicode-aware caption wrapping | Tiny optional dep |
| Project state | **SQLite** (stdlib) | Public domain | Durable projects/renders/publish jobs | `storage/project_store.py` |

### 4.2 Evaluate (do not block the MVP)

| Component | License | Use | Trigger to adopt |
|---|---|---|---|
| **LR-ASD** / TalkNet-ASD | MIT (verify weights) | Active-speaker selection in multi-face footage | Golden set shows >1 wrong-speaker switch per clip |
| **WhisperX** | BSD-2-Clause | Forced alignment + diarization | Caption word timing MAE too high with faster-whisper alone |
| **pyannote community-1** | MIT code / CC-BY-4.0 model | Speaker turns as a prior for crop and split-screen | Podcast/interview content is a target segment |
| **shot-detection ONNX / TransNetV2** | Apache-2.0 / MIT | Learned shot boundaries | PySceneDetect misses gradual transitions in the golden set |
| **Zencastr laughter ONNX** | MIT | Laughter as a ranking signal | Audio signal is too noisy or misses obvious moments |
| **auto-editor CLI** | Unlicense repo / open-core binary | Power-user rough cut / silence removal | Users ask for transcript-based jump cuts; review binary terms |
| **GHOST / RestoreFormer++** | Apache-2.0 / Apache-2.0 | Face-swap model/restoration alternatives | Commercial distribution requires leaving inswapper |
| **Qwen3-ASR / Parakeet TDT v3** | Apache-2.0 / CC-BY-4.0 | Word timestamps for more languages | Language coverage becomes a priority |

### 4.3 Avoid

| Component | Reason |
|---|---|
| **Ultralytics YOLO (v8/v11/26)** | AGPL-3.0 code and weights; commercial license required |
| **FaceFusion** | OpenRAIL-AS plus many non-commercial assets; do not bundle |
| **inswapper for commercial use** | Model weights are non-commercial; decide license vs GHOST |
| **CodeFormer / GPEN / madmom models / PyIQA / Rescript** | Non-commercial or unclear licenses |
| **SubsAI / whisper-timestamped** | GPL-3.0 / AGPL-3.0 in a distributed app |
| **stable-ts as a new dependency** | Archived May 2026; vendor a pinned copy only if needed |
| **Remotion without a license** | Free only for individuals/small teams; embedding/automation needs a paid license |
| **Etro / Concat / HotClip / tscaps** | GPL/AGPL or commercial restrictions |
| **Full-app forks (AutoClip, OpenShorts, Concat, OpenCut)** | Wrong stack, hidden licenses, and still no editor; reuse patterns only |

### 4.4 Reference patterns worth porting (not forking)

| Project | License | What to reuse |
|---|---|---|
| **OpenShorts** | MIT core; avoid `cloud/`, Remotion/YOLO | `recut.py` EDL semantics: ordered segments, word snapping, virtual transcript, per-segment re-encode + concat |
| **AutoClip (`zhouxiaoka/autoclip`)** | MIT | Pipeline stages, scoring prompts, collections/publish-kit concept |
| **ClipsAI** | MIT | TextTiling boundary detection as an LLM-free fallback |
| **FunClip** | MIT | Transcript/speaker selection UX, multi-segment clipping |
| **LosslessCut** | GPL-2.0 | Segment/export UX and ffmpeg command log (reference only) |
| **Cutroom** | MIT | Minimal timeline interactions (trim/split/ripple/markers), Electron reference |

---

## 5. Roadmap

Ship in this order. Each phase is independently testable and leaves the app usable.
Effort assumes one focused developer; UI work can run in parallel with render work.

### Phase 0 — Correctness + reliability (3–5 days)

**Status: implemented 2026-11-09.** The P0 fixes below are in the working tree, with
unit/regression tests; the ffmpeg integration test is included but skips when
`ffmpeg`/`ffprobe` are not on PATH. A manual smoke render (captioned and
multi-segment) produced a 540×960 9:16 MP4 with 48 kHz stereo audio and a
thumbnail.

**Goal:** no more visibly broken shorts; the app survives a second batch.

| Task | Files | Acceptance |
|---|---|---|
| Rebase face samples to clip-relative; add origin parameter | `smartcrop.py`, `clipper.py` | Unit test: `start=100` produces a plan covering `0..duration`; face crop is not discarded |
| Fix crop tiling: prepend intro, fill gaps, clamp to source duration | `clipper.py` | Test: first segment start 2.0 → output starts at 0; no missing audio; short duration ≈ requested (±100 ms) |
| Center the crop on the face, not the face-at-edge formula | `smartcrop.py` | Test: `seg_x=0.1/0.5/0.9` places the face within ~5% of crop center |
| Clamp `start`/`end` to media duration; enforce min/max clip length after snap | `clipper.py`, `highlights.py`, `rerank.py` | No caption/audio past EOF; no clip > `MAX_CLIP_SECONDS` after snap |
| Word-caption path: use `load_word_srt`; fall back to sentence cues | `clip_card.py`, `clipper.py` | Test: `.words.srt` produces non-empty cues; missing words → sentence fallback |
| Generate/burn ASS with 1080×1920 PlayRes and bottom safe zone | `clipper.py`, `captions.py` | Caption pixels in bottom 20–75% band, not clipped; style respects `CAPTION_*` |
| Fade only the first/last program segment; normalize audio once | `clipper.py` | No black flash or level jump at crop switches |
| Keep `_empty` alive; add `shutdown()`/wait for card workers | `shorts_creator_page.py`, `faceswap_page.py`, `clip_card.py`, `main_window.py` | Two consecutive batches work; closing during a render does not crash |
| Persist `short_path`/`thumb_path`; fix Open File and thumbnail lookup | `clip_card.py`, new `renders.json` or `clips.json` update | Restart restores "Short ✓", thumbnail, and Open File |
| Queue files per mode; restore mode; fix Settings reload/restart banner | `queue_list.py`, `settings_panel.py` | YouTube and TikTok queues stay separate; reload repopulates controls |
| Skip original-ratio render when `--shorts`; render missing shorts on cached runs | `main.py`, `pipeline.py` | `--shorts` does one render per short; cached clips render correctly |
| Use `caption_tracks.choose_track`; reject translations by default | `pipeline.py`, `downloader.py` | Language test: requested `en` never reuses `ne`; no `tlang=` track by default |

**Exit gate:** a 60s short rendered from a clip at 30+ minutes has correct duration, face-aware crop,
readable bottom captions, no black flashes, and no A/V drift. Second queue run works.

### Phase 1 — Render engine v2 (5–7 days)

**Status: core implemented 2026-11-09.** `shorts_generator/render/` now builds one
filter graph (trim → crop/scale → concat → fade → ASS → format; audio concat →
fade → loudnorm) and one encoder pass, with progress/cancel and hardware-encoder
fallback. A measured two-pass loudness pass and per-clip music ducking remain
follow-ups.

**Goal:** one render path, one final encode, progress/cancel, predictable quality.

| Task | Files | Acceptance |
|---|---|---|
| Introduce `RenderPlan` / `ClipRecipe` | new `render/plan.py` | Old `clips.json` derives a plan; editor and CLI use the same object |
| Single-pass `filter_complex` renderer | new `render/ffmpeg.py` | One encode; no per-segment loudnorm; concat in-graph |
| Global loudnorm + 48 kHz stereo + faststart | `render/ffmpeg.py` | Output ≈ −14 LUFS, −1.5 dBTP; `ffprobe` confirms 48 kHz |
| Caption ASS generation and burn in the same pass | `render/ffmpeg.py`, `captions.py` | Word/sentence cues, no clipped lines, safe-zone test |
| Thumbnail from the final short, 1080×1920 | `clipper.py` | Thumbnail is vertical, matches the short |
| Encoder detection and fallback | `render/encoder.py` | NVENC/QSV/AMF used when available; libx264 fallback |
| Progress + cancel + timeout | `render/ffmpeg.py`, workers | Determinate progress; cancel terminates ffmpeg; no orphan parts |
| Render integration tests | `tests/` | Generated testsrc fixture: duration, fps, resolution, audio sample rate, caption bbox, A/V sync |
| Music mix: ducking, loop, limiter | `render/ffmpeg.py` | Follow-up; compile music path already uses `amix=normalize=0` + limiter |

**Exit gate:** 10-clip golden set renders cleanly on CPU and (if available) NVENC; no regressions in
duration/sync; caption safe-zone test passes.

### Phase 2 — Drop-and-go orchestration + project state (5–7 days)

**Goal:** one button, visible progress, state that survives restart.

| Task | Files | Acceptance |
|---|---|---|
| "Make Shorts" action: analyze → auto-render top N → manifest | `shorts_creator_page.py`, `queue.py`, `render_service.py` | One click produces N ready shorts and a manifest |
| Per-clip selection + cross-video batch export | `clip_card.py`, `shorts_creator_page.py` | Render clips 1 and 3 only; export all videos |
| Project store (SQLite): videos, clips, renders, publish jobs | new `storage/project_store.py` | Restart restores cards, renders, thumbnails, settings |
| Autosave + crash recovery | `project_store.py`, `app.py` | Kill/restart mid-edit restores the last saved state |
| Progress/ETA for download/transcribe/render/compile/upload | workers, `downloader.py`, `transcriber.py` | Determinate progress; ETA; cancel works |
| Preflight checks | new `services/preflight.py` | Missing ffmpeg/API key/model shows an actionable dialog before work starts |
| Multi-select + retry failed items | cards, queue | Failed videos/clips can be retried without re-adding URLs |
| Honest score presentation | `clip_card.py`, `rerank.py` | UI says "relative rank" or shows calibrated LLM score; single clip is not automatically 100 |
| Fix thread-safe log pipe | `_logpipe.py` | Parallel videos do not lose/interleave lines |

**Exit gate:** paste URL → press once → review rendered shorts → close app → reopen → state intact.

### Phase 3 — Reframe v2 (7–10 days)

**Goal:** face tracking that actually works on real content, including multi-person and faceless.

| Task | Files | Acceptance |
|---|---|---|
| YuNet detector + model cache | `reframe/detector.py` | Detects faces at 2–4 fps on 480px frames; logs fallback; no Haar |
| Tracker + One-Euro/EMA smoothing | `reframe/tracker.py` | Identity stable across detections; no per-frame jitter |
| Crop planner with x, y, scale, padding, headroom | `reframe/planner.py` | Faces stay inside safe area; dynamic zoom on wide shots |
| Multi-face policy: hysteresis, min shot length, split/wide fallback | `reframe/planner.py` | No rapid speaker ping-pong; two-person content uses split or wide when needed |
| Scene-cut reset with PySceneDetect | `reframe/planner.py` | Tracking resets at cuts; no wrong-person carry-over |
| Faceless/gameplay fallback: saliency/motion + wide layout | `reframe/planner.py` | Center-crop is no longer the only option; HUD/action preserved where possible |
| Cache face tracks per source | `reframe/` + project store | Re-render does not re-analyze the whole source |
| Golden-set metrics | `tests/` + `eval/` | Face-on-screen %, identity switches, jitter, crop misses measured |

**Exit gate:** on a 20-clip golden set (talking head, podcast, gameplay, vertical, HDR), face-aware
crop is used by default and beats center crop in a blind side-by-side review.

### Phase 4 — Correction editor MVP (10–15 days)

**Goal:** fix a cut, caption, crop, or title in under two minutes without leaving the app.
Full spec: [EDITOR_MVP_SPEC.md](EDITOR_MVP_SPEC.md).

| Task | Files | Acceptance |
|---|---|---|
| mpv/libmpv preview (LGPL build) + QMediaPlayer fallback | `editor/preview.py` | Frame-accurate seek/step; ASS preview; <200 ms seek on a proxy |
| Single-track EDL timeline | `editor/timeline.py` | Trim, split, delete, reorder, snap to frames/words; undo/redo |
| Caption editor | `editor/caption_editor.py` | Click word to seek; inline edit; retime/nudge; split/merge; style presets |
| Crop mode selector + manual offset | `editor/crop_editor.py` | Auto/track/center/split/blur/manual; preview overlay |
| Hook/title editor + AI variants | `editor/`, `llm.py` | Edit title/hook; generate 3 variants; persists |
| Render preview 540p vs final 1080p | `render_service.py` | Preview matches final within 1 frame; same ASS/crop |
| Project persistence + autosave | `storage/project_store.py` | Close/reopen restores edits; crash recovery |

**Exit gate:** a user can take an AI clip, trim 2 seconds off the start, fix a caption, change the
crop to "wide", edit the hook, and export 1080p — in under two minutes.

### Phase 5 — Publish + metadata (5–7 days)

**Goal:** publish a single short safely, with real metadata.

| Task | Files | Acceptance |
|---|---|---|
| Per-clip YouTube upload | `publish/youtube.py` | Upload one selected short; progress; retry/backoff |
| Metadata editor + AI title/description/hashtags | `editor`, `publish/youtube.py` | Clip title/hook feeds upload; description/tags editable |
| Privacy + `publishAt` + category + made-for-kids | `publish/youtube.py` | Default private/unlisted; schedule works; no public-by-default |
| Thumbnail + SRT upload | `publish/youtube.py` | Custom 9:16 thumbnail and captions attach |
| TikTok export preset + draft upload | `publish/tiktok.py` | Valid 9:16 MP4; draft/inbox upload; Direct Post later, after audit |
| Upload kit (title, description, hashtags) | `clip_card.py` | Copy/paste block matches the selected platform |
| Compile guardrails (if kept) | `clipper.py` | ≤3 min, 9:16, re-encoded, normalized; otherwise disabled |
| OAuth token in OS keyring | `publish/` | No plaintext token; clear account switch |

**Exit gate:** upload a private test Short with title, description, tags, thumbnail, and captions;
schedule it; verify in YouTube Studio.

### Phase 6 — Differentiators (ongoing, only after the loop is fast)

- Silero VAD cut planning + filler-word removal (reviewable, one undo).
- PySceneDetect-driven thumbnails and cut avoidance.
- Laughter/applause signals; replay-holdout calibration.
- Diarization/active-speaker crop (LR-ASD) for podcasts.
- Multi-language captions + translation.
- Beat-synced music and per-clip music (not only compile).
- Face-swap quality: YuNet alignment, BiSeNet/XSeg masks, LAB colour transfer, restoration,
  temporal smoothing; resolve the inswapper commercial license or switch to GHOST.
- Template packs/brand kits, batch scheduling, analytics.
- Optional auto-editor-style transcript rough cut.

---

## 6. What not to do

1. **Do not fork AutoClip, OpenShorts, Concat, or OpenCut.** They are apps, not libraries; they bring
   React/Tauri/Rust stacks, Remotion/YOLO licensing, and still lack the correction editor.
2. **Do not switch to a web UI now.** Stay PySide6; embed mpv for precise preview. Revisit only if
   you need Remotion-style template rendering, a web/mobile client, or a React team.
3. **Do not build a multi-track NLE.** No keyframes, colour grading, transitions, B-roll, or voice
   cloning in the MVP. Every feature must pass: "does this help fix a bad clip and post faster?"
4. **Do not adopt AGPL models** (Ultralytics YOLO), non-commercial weights (inswapper for commercial),
   or GPL/AGPL editors (Etro, Concat, HotClip, tscaps) without a deliberate license decision.
5. **Do not use `-c copy` for final short exports.** It snaps to keyframes, producing wrong in/out
   points. Re-encode segment-accurately; use stream copy only for verified-identical concat parts.
6. **Do not add another signal before the render is correct.** Ranking is already reasonable; the
   visible quality problem is the last mile.

---

## 7. Verification and metrics

### 7.1 Golden set

Build a 20-clip set covering:

- single talking head (indoor/outdoor, glasses, profile);
- two-person podcast/interview;
- gameplay/faceless;
- vertical phone source (9:16 and taller);
- 4K HDR (PQ/HLG);
- 24/25/29.97/30/60 fps;
- quiet speech, loud laughter, music-heavy;
- clips starting at 0, 5, 30, and 60+ minutes;
- age-restricted/cookie-required source (download path);
- very long source (90+ min).

Store expected metadata (source duration, chosen start/end) and render assertions. Never commit
the media; generate synthetic clips for CI with ffmpeg `testsrc2`/`sine`.

### 7.2 Gates

| Metric | Target |
|---|---|
| Render success rate | > 99% on golden set |
| Duration error | < 100 ms vs requested |
| A/V/caption sync | < 1 frame |
| Caption safe-zone violations | 0 |
| Face-on-screen (talking-head subset) | > 90% |
| Identity switches per clip | < 1 |
| Black flashes / level jumps at crop switches | 0 |
| Second queue run / close-during-render | No crash |
| Restart restores renders | 100% |
| URL → first short (60 min source, captions available) | < 10 min |
| Edit → export (60s clip) | < 2 min |
| Batch export 5 clips | < 8 min |
| Human preference vs current build | ≥ 70% on 20 blind pairs |

### 7.3 Test strategy

1. **Unit tests** for crop math, duration clamping, caption chunking, ASS timestamps, EDL mapping,
   score presentation.
2. **ffmpeg integration tests** using a generated 5–10s `testsrc2` + `sine` fixture: probe output,
   assert duration/fps/resolution/audio/caption bbox/A-V sync.
3. **Regression tests for each P0 bug** in §1.2. These should fail before the fix and pass after.
4. **Snapshot tests** for ASS output (cue count, no overlaps, safe-zone margins).
5. **Golden-set eval** (manual + scripted) before each release; compare blind A/B against the
   previous build.
6. **Crash/restart tests** for workers, second batch, close-during-render, queue restore.

---

## 8. Risks and licensing

| Risk | Impact | Mitigation |
|---|---|---|
| **Scope creep into an NLE** | Delays the core loop by months | Enforce the correction-editor scope; no multi-track/keyframes/B-roll in MVP |
| **FFmpeg GPL/libx264** | Distribution obligations | Ship an LGPL-compatible ffmpeg build where possible; use hardware encoders or obtain appropriate licenses; legal review before distribution |
| **mpv GPL default** | Distribution obligations | Ship an LGPL libmpv build (`-Dgpl=false`), dynamic link, notices, test packaging |
| **Qt/PySide6 LGPL** | Relinking obligations | Dynamic linking, notices, comply with LGPL; commercial license if needed |
| **yt-dlp ToS / cookies** | Platform and privacy risk | User-provided cookies, local-only, clear warning, no credential storage in plaintext |
| **YouTube API verification/quota** | Upload limits | Build for 100 uploads/day; verify OAuth app; request audit if needed; default private |
| **TikTok audit** | Direct Post unavailable | Export/draft first; Direct Post only after audit; no scheduling promise without a worker |
| **inswapper weights** | Commercial use unclear | Treat face swap as personal-use until licensed; evaluate GHOST for commercial |
| **Model downloads/size** | First-run friction | Download on demand with SHA256, cache in `%LOCALAPPDATA%`, show license/size, allow offline reuse |
| **CPU render time** | Users wait | YouTube captions first, hardware encode detection, 540p preview, render queue, progress/ETA |
| **LLM cost/rate limits** | Free-tier friction | One call per video already; add provider fallback, preflight, and clear error messages |
| **Security** | Command/ASS injection, SSRF | Argv lists only (no `shell=True`), validate URLs, escape ASS text, localhost OAuth callback, keyring |

---

## Appendix A — File-level change map

| File | Phase | Change |
|---|---|---|
| `shorts_generator/smartcrop.py` | 0, 3 | Rebase timestamps, center crop, replace Haar with YuNet/tracker/planner |
| `shorts_generator/clipper.py` | 0, 1 | Fix tiling/captions/fades; thin wrapper over `render/`; keep legacy API |
| `shorts_generator/captions.py` | 0, 1 | Improve ASS timestamps/escaping; becomes `render/captions.py` backend |
| `shorts_generator/transcriber.py` | 0 | Word timestamps, cache, model reuse, VAD option |
| `shorts_generator/pipeline.py` | 0, 2 | Caption-track selection, clamp boundaries, skip double render, emit recipe/renders |
| `shorts_generator/queue.py` | 2 | Progress callbacks, retry, per-item status |
| `shorts_generator/config.py` | 0, 2 | Dynamic reads or reload; validate values; add new knobs |
| `studio_app/shorts_creator_page.py` | 0, 2 | Keep empty state, Make Shorts, batch/select, progress |
| `studio_app/clip_card.py` | 0, 2 | Fix thumb/open file, persist renders, selection, job status |
| `studio_app/queue_list.py` | 0 | Per-mode queue files, URL validation, mode restore |
| `studio_app/settings_panel.py` | 0 | Reload controls, persist GUI-only keys, restart banner |
| `studio_app/preview.py` | 4 | Replace/extend with mpv preview; source + rendered short |
| `studio_app/editor/*` | 4 | New timeline, caption editor, crop editor |
| `shorts_generator/render/*` | 1 | New RenderPlan, ffmpeg, captions, thumbnail, encoder |
| `shorts_generator/reframe/*` | 3 | New detector, tracker, planner |
| `shorts_generator/storage/*` | 2 | New project store |
| `shorts_generator/publish/*` | 5 | New YouTube/TikTok publish services |
| `docs/EDITOR_MVP_SPEC.md` | 4 | Editor contract (this plan's companion) |
| `README.md` | 0, 5 | Remove overclaims; document the real workflow and limits |

---

## Appendix B — Research sources

Primary references used for the OSS decisions (verify licenses/versions at adoption time):

- OpenCV Zoo / YuNet / SFace — https://github.com/opencv/opencv_zoo
- faster-whisper — https://github.com/SYSTRAN/faster-whisper
- Silero VAD — https://github.com/snakers4/silero-vad
- pysubs2 — https://github.com/tkarabela/pysubs2
- libass — https://github.com/libass/libass
- PySceneDetect — https://github.com/Breakthrough/PySceneDetect
- mpv / libmpv — https://github.com/mpv-player/mpv, https://github.com/jaseg/python-mpv
- WhisperX — https://github.com/m-bain/whisperX
- pyannote-audio — https://github.com/pyannote/pyannote-audio
- LR-ASD — https://github.com/Junhua-Liao/LR-ASD
- Auto-Editor — https://github.com/WyattBlue/auto-editor
- OpenShorts — https://github.com/mutonby/openshorts (MIT core; avoid `cloud/`, Remotion/YOLO)
- AutoClip — https://github.com/zhouxiaoka/autoclip
- ClipsAI — https://github.com/ClipsAI/clipsai
- FunClip — https://github.com/modelscope/FunClip
- YouTube Data API quota — https://developers.google.com/youtube/v3/determine_quota_cost
- YouTube upload — https://developers.google.com/youtube/v3/docs/videos/insert
- TikTok Content Posting API — https://developers.tiktok.com/docs/en/content-posting-api-get-started

**License caution:** summaries above are not legal advice. Check the exact repository `LICENSE`,
model card, and any third-party notices at the commit you ship. AGPL/GPL contamination and
non-commercial model weights are the two traps most likely to bite a distributed desktop app.
