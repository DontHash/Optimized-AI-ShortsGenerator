# Editor MVP Spec — The Correction Editor

**Status:** proposed, companion to [REVAMP_V2_PLAN.md](REVAMP_V2_PLAN.md)
**Goal:** fix an AI-generated short in under two minutes and export it, without leaving ClipClipper.

---

## 1. Product principle

**This is a correction editor, not a creation NLE.**

The analysis pipeline already finds the moment, sets boundaries, picks a crop, and writes captions.
The editor exists to fix the last 20%:

- the cut starts a word too early;
- a name was misheard in the captions;
- the crop follows the wrong person;
- the hook/title is weak;
- the music is too loud.

Every feature must pass one test: **does this help the user fix a bad clip and post it faster?**
If it only helps build a video from scratch, it is out of scope for the MVP.

---

## 2. UX flow

```
┌────────────┐     ┌────────────┐     ┌────────────┐     ┌────────────┐
│ Home/Queue │ ──▶ │   Review   │ ──▶ │   Editor   │ ──▶ │   Export   │
│ paste URL  │     │ pick clips │     │ fix & preview│    │ render/post│
└────────────┘     └────────────┘     └────────────┘     └────────────┘
```

- **Home/Queue:** add URL(s)/file, choose preset, watch progress, open review.
- **Review:** 3–10 candidates, 9:16 autoplay, score/hook/reason, accept/reject, open editor.
- **Editor:** one clip, single-track timeline, caption/crop/title corrections, live preview.
- **Export:** per-clip render with progress, then open folder or upload/schedule.

The user can skip the Editor entirely: **"Export as-is"** uses the AI plan and renders immediately.

---

## 3. Screens

### 3.1 Home / Queue

**Purpose:** start work and see status without watching a console.

| Element | Behavior |
|---|---|
| URL input | Accepts YouTube URLs, `youtu.be`, playlist URLs, `urls.txt` drop |
| File drop | Local video is allowed as a future path; YouTube is the MVP input |
| Preset | YouTube Shorts / TikTok / Reels / Generic 9:16 |
| Candidate count | 3 / 5 / 10 |
| Start button | Starts analysis; disabled while running; shows stage and ETA |
| Project cards | Thumbnail, source title, status, candidate count, last updated |
| Row actions | Open, Retry, Cancel, Delete, Open folder |
| Preflight banner | Missing ffmpeg/API key/model → actionable message before starting |

**Stage labels:** Downloading → Transcribing → Signals → Ranking → Ready.
Per-stage progress and elapsed/total time. A "Details" expander shows the last log lines, not the
whole console.

### 3.2 Review

**Layout:**

```
┌──────────────────────────────────────────────────────────────────────┐
│ Source title · 42:13 · 6 candidates · [Re-analyze] [Make all]        │
├──────────────────┬───────────────────────────────┬───────────────────┤
│ Candidate cards  │        9:16 player            │ Why this clip     │
│ ┌──────────────┐ │  ┌─────────────────────────┐  │ Score: #1 of 6    │
│ │ #1 thumb 92  │ │  │                         │  │ Hook: "..."       │
│ │ hook...      │ │  │      vertical video     │  │ Reason: ...       │
│ └──────────────┘ │  │                         │  │ ─────────────     │
│ ┌──────────────┐ │  └─────────────────────────┘  │ [Open editor]     │
│ │ #2 thumb 78  │ │  [play] [loop hook] [cc]      │ [Regenerate cut]  │
│ └──────────────┘ │  00:00 ─────●────── 00:48     │ [Reject]          │
├──────────────────┴───────────────────────────────┴───────────────────┤
│ [Export selected] [Export all] [Compile]                             │
└──────────────────────────────────────────────────────────────────────┘
```

**Interactions:**

- Click card → load 9:16 preview (rendered short if available, otherwise a fast draft preview).
- **Space** play/pause; **J/K/L** reverse/pause/forward; **←/→** ±5s; **, / .** frame step.
- **A/D** previous/next candidate; **X** reject; **Enter** open editor; **Esc** back.
- **Loop hook** replays the first 3 seconds; **CC** toggles caption overlay.
- **Export as-is** renders the AI plan without opening the editor.
- **Regenerate cut** reruns boundary selection for this clip only (no full re-analysis).
- **Regenerate hook/title** asks the LLM for 3 variants; user picks one.
- Multi-select checkboxes; **Export selected** respects selection and order.
- Rejected cards collapse into a "Rejected (3)" section, restorable.

**Card content:** rank badge, relative rank (`#2 of 6`), calibrated LLM confidence (not a fake
100), duration, hook, one-line reason, thumbnail, render status.

### 3.3 Editor

**Layout:**

```
┌──────────────────────────────────────────────────────────────────────────┐
│ ← Review   "The one mistake that cost me $50K"        [Preview] [Export] │
├───────────────────────────────────────────┬──────────────────────────────┤
│                                           │ Inspector                    │
│           9:16 PREVIEW                    │ ┌──────┬───────┬──────┬─────┐ │
│      ┌──────────────────────┐             │ │ Cut  │ Capt. │Crop  │Audio│ │
│      │                      │             │ └──────┴───────┴──────┴─────┘ │
│      │   video + overlays   │             │ Start   00:02:04.3  [-][+]   │
│      │   safe-zone guides   │             │ End     00:03:07.6  [-][+]   │
│      └──────────────────────┘             │ Duration 63.3s              │
│                                           │ Reframe  [Auto ▾]            │
│  [◀◀] [▶] [▶▶]   00:01:12 / 00:01:03      │ Captions [word-by-word ▾]    │
├───────────────────────────────────────────┤ Style    [Bold Pop ▾]        │
│ TIMELINE                                  │ Music    [ none ] [browse]   │
│ ruler  0:00   0:15   0:30   0:45   1:00   │                              │
│ video  ███████████████████████████████    │ [Reset to AI cut]            │
│ captions  ▂▂ ▂▂▂ ▂▂ ▂▂▂ ▂▂ ▂▂▂ ▂▂        │                              │
│ audio  ▁▂▅▇▅▂▁▁▂▅▇▅▂▁▁▂▅▇▅▂▁▁▂             │                              │
└───────────────────────────────────────────┴──────────────────────────────┘
```

**Preview:**

- 9:16 canvas at the final aspect; safe-zone guides (top 6%, bottom 20%, sides 5%) toggleable.
- Captions rendered from the same ASS file used for export.
- Crop window overlay when the Crop tab is active; draggable horizontally/vertically.
- Playback uses a **short-GOP 720p proxy** for responsive scrubbing; final export uses the source.
- **Preview quality** toggle: Draft (540p) / Final (1080p render). Draft is the default.

**Timeline:**

- **One video/EDL row:** ordered segments; drag edges to trim; drag body to reorder; `S` split at
  playhead; `Delete` ripple-delete; `M` marker.
- **One caption row:** cue blocks; click to seek; drag edges to retime; double-click to edit text.
- **One audio row:** waveform; source gain; optional music track.
- Playhead, ruler, zoom (`Ctrl+wheel`), scroll, snapping toggle (frames / words / playhead).
- Undo/redo (`Ctrl+Z` / `Ctrl+Y`), autosave every 5s, "Revert to AI cut".

**Inspector tabs:**

#### Cut

| Control | Behavior |
|---|---|
| Start / End | Editable timecode + nudge buttons; frame-snapped |
| Duration | Live; warns above 3 min (Shorts limit) |
| Segments | List of EDL segments; add from source, split, delete, reorder |
| Snap | Frames / words / playhead / off |
| Reframe | Auto / Track speaker / Center / Split / Blur background / Manual |
| Reset to AI cut | Restores the original boundaries and crop plan |

#### Captions

| Control | Behavior |
|---|---|
| Mode | Burn-in / Soft subtitle track / None |
| Style | Preset cards: Clean, Bold Pop, Karaoke, Boxed, Custom |
| Cue list | Text, start/end, duration; click to seek |
| Inline edit | Double-click a cue or word; `Enter` commit, `Esc` cancel |
| Nudge | `Alt+←/→` ±50 ms; `Alt+Shift+←/→` ±10 ms |
| Split / Merge | At playhead / selected cues |
| Auto-paginate | Max 2 lines, max characters, max duration; insert `\N` |
| Revert captions | Restore the AI transcript cues |
| Import / Export | SRT / ASS / VTT |
| Word highlight | Toggle karaoke highlight; pick accent color |

#### Crop

| Control | Behavior |
|---|---|
| Mode | Auto / Track / Center / Split / Blur / Manual |
| X / Y offset | Manual pan; reset button |
| Zoom | 100–200%; clamp to source bounds |
| Safe area | Show face/head padding overlay; rule-of-thirds toggle |
| Subject lock | "Follow the largest face" vs "Follow the active speaker" (if diarization is enabled) |

#### Audio

| Control | Behavior |
|---|---|
| Source gain | −12 to +6 dB |
| Music | File picker; gain; loop; fade in/out |
| Ducking | Toggle; sidechain under speech |
| Normalize | Target −14 LUFS; true peak −1.5 dBTP |
| Mute source | For music-only or B-roll segments |

#### Title / Hook (can live with Cut or its own small tab)

| Control | Behavior |
|---|---|
| Hook text | First-3-seconds overlay/title; editable |
| Upload title | Defaults to clip title; character counter |
| Description / hashtags | Editable; AI variants button |
| Overlay | Show/hide, position (top/bottom), duration |

### 3.4 Export

| Element | Behavior |
|---|---|
| Selected clips | List with status: queued / rendering / done / failed |
| Preset | YouTube Shorts / TikTok / Reels / Generic; 1080×1920, 30/60 fps |
| Quality | Standard / High; hardware encoder auto |
| Captions | Burn / soft / none (matches editor) |
| Output folder | Per-project default; open after export |
| Actions | Export selected, cancel, retry failed, open folder |
| Publish | YouTube upload/schedule; TikTok export/draft; copy upload kit |

**Progress:** per-clip determinate progress with stage (preparing → rendering → captions →
thumbnail → done), elapsed, ETA, cancel. On failure: error message and retry, not a silent stop.

---

## 4. Data model

### 4.1 Clip recipe (portable JSON)

```json
{
  "schema_version": 1,
  "clip_id": "clip_01J...",
  "video_id": "dQw4w9WgXcQ",
  "title": "The one mistake that cost me $50K",
  "hook": "This one decision cost me everything.",
  "score": {"relative": 0.92, "llm": 88, "rank": 1, "of": 6},
  "reason": "Strong hook, complete story, emotional payoff.",
  "recipe": {
    "segments": [
      {"src_in": 124.30, "src_out": 157.60},
      {"src_in": 159.10, "src_out": 187.60}
    ],
    "framing": {
      "mode": "auto",
      "crop_tracks": [
        {"start": 0.0, "end": 12.4, "x": 0.42, "y": 0.5, "zoom": 1.0},
        {"start": 12.4, "end": 33.3, "x": 0.58, "y": 0.5, "zoom": 1.15}
      ],
      "manual": {"x": 0.5, "y": 0.5, "zoom": 1.0}
    },
    "captions": {
      "mode": "burn",
      "style_id": "bold_pop",
      "cues": [
        {"start": 0.0, "end": 1.9, "text": "This one decision", "words": [0, 1, 2]},
        {"start": 1.9, "end": 3.6, "text": "cost me everything", "words": [3, 4, 5]}
      ]
    },
    "audio": {
      "source_gain": 1.0,
      "music_path": null,
      "music_gain": 0.18,
      "ducking": true,
      "normalize_lufs": -14.0
    },
    "overlays": [
      {"type": "hook", "text": "Wait for it…", "start": 0.0, "end": 2.5, "position": "top"}
    ]
  },
  "renders": [
    {
      "preset": "youtube_shorts_1080p",
      "path": "D:/exports/dQw4w9WgXcQ/1_the-one-mistake_short.mp4",
      "thumb": "D:/exports/dQw4w9WgXcQ/1_the-one-mistake_short.jpg",
      "created_at": "2026-11-09T14:22:31Z",
      "duration": 63.3,
      "status": "done"
    }
  ],
  "publish": {
    "youtube": {"video_id": null, "privacy": "private", "publish_at": null},
    "tiktok": {"status": "not_uploaded"}
  }
}
```

**Backward compatibility:** if `recipe` is missing, derive:

```text
segments = [{src_in: start_time, src_out: end_time}]
framing  = {mode: "auto"}
captions = {mode: "burn", style_id: "bold_pop", cues: generated from transcript}
audio    = {source_gain: 1.0, ducking: true}
```

### 4.2 SQLite schema (project store)

```sql
CREATE TABLE projects (
  id TEXT PRIMARY KEY,
  source_url TEXT,
  source_path TEXT,
  proxy_path TEXT,
  waveform_path TEXT,
  title TEXT,
  duration REAL,
  fps REAL,
  width INTEGER,
  height INTEGER,
  status TEXT,
  created_at TEXT,
  updated_at TEXT
);

CREATE TABLE clips (
  id TEXT PRIMARY KEY,
  project_id TEXT REFERENCES projects(id),
  rank INTEGER,
  title TEXT,
  hook TEXT,
  score_json TEXT,
  reason TEXT,
  recipe_json TEXT,
  status TEXT,
  created_at TEXT,
  updated_at TEXT
);

CREATE TABLE renders (
  id TEXT PRIMARY KEY,
  clip_id TEXT REFERENCES clips(id),
  preset TEXT,
  path TEXT,
  thumb TEXT,
  status TEXT,
  progress REAL,
  error TEXT,
  created_at TEXT
);

CREATE TABLE publish_jobs (
  id TEXT PRIMARY KEY,
  clip_id TEXT REFERENCES clips(id),
  platform TEXT,
  platform_id TEXT,
  status TEXT,
  scheduled_at TEXT,
  error TEXT
);

CREATE TABLE settings (
  key TEXT PRIMARY KEY,
  value_json TEXT
);
```

Store media outside the DB. Use content hashes for cache keys and clean proxies on project delete.

---

## 5. Render contract

### 5.1 Input

```python
@dataclass
class RenderPlan:
    source: str
    output: str
    segments: list[Segment]          # src_in, src_out
    crop_tracks: list[CropTrack]     # start, end, x, y, zoom (clip-relative)
    captions: CaptionPlan            # cues, style, mode
    audio: AudioPlan                 # gain, music, ducking, target_lufs
    canvas: Canvas                   # 1080x1920, fps, crf, encoder
    overlays: list[Overlay]
```

### 5.2 Output

- Container: MP4, `+faststart`, metadata scrubbed.
- Video: H.264 `yuv420p`, 1080×1920 (or capped to avoid >3× upscale), 30/60 fps.
- Audio: AAC, 48 kHz, stereo, 192 kbps, ≈ −14 LUFS, true peak ≤ −1.5 dBTP.
- Captions: burned ASS (libass) or a soft `mov_text` track; never both by accident.
- Duration: sum of segments; no dropped intro/gaps; clamped to source.

### 5.3 Filter graph (single final encode)

```
[0:v] split=N
  → trim=start=…:end=…, setpts=PTS-STARTPTS,
    crop=w:h:x:y, scale=W:H, fps=FPS      (per segment)
  → concat=n=N:v=1:a=0 [v]

[0:a] asplit=N
  → atrim=start=…:end=…, asetpts=PTS-STARTPTS (per segment)
  → concat=n=N:v=0:a=1 [a]

[a] → loudnorm / music sidechain / alimiter [aout]
[v] → ass=captions.ass → format=yuv420p [vout]

-map [vout] -map [aout]
-c:v libx264 (or h264_nvenc/qsv/amf/videotoolbox) -crf 20 -preset fast
-c:a aac -b:a 192k -ar 48000 -ac 2 -movflags +faststart
```

- Fade in only the first program edge, fade out only the last.
- If captions are disabled, omit the `ass` filter (no extra encode).
- If N is very large, chunk the filter graph but keep identical encode settings; concat with the
  concat **filter**, not stream copy, unless inputs are verified identical.

### 5.4 Preview

- mpv/libmpv with `hr-seek=yes`, `keep-open=yes`, `pause=yes`, `hwdec=auto-safe`.
- `sub-add` the exact ASS file used for export; `sub-ass-override=force`.
- 720p short-GOP proxy for the source; final render uses the original.
- On Windows, `MpvRenderContext` in `QOpenGLWidget`; `QMediaPlayer` fallback if packaging fails.
- Preview must use the same canvas, crop parameters, ASS file, fps, and safe-zone coordinates as
  the final render. Verify a few frames (SSIM/hash) in tests.

---

## 6. Keyboard map

| Key | Action |
|---|---|
| `Space` | Play / pause |
| `J` / `K` / `L` | Reverse / pause / forward |
| `←` / `→` | ±5 s |
| `,` / `.` | Frame step back / forward |
| `A` / `D` | Previous / next candidate |
| `S` | Split at playhead |
| `Delete` | Ripple-delete selection |
| `M` | Add marker |
| `X` | Reject candidate |
| `Enter` | Open editor |
| `Esc` | Back / close dialog |
| `Ctrl+Z` / `Ctrl+Y` | Undo / redo |
| `Ctrl+S` | Save now |
| `Ctrl+E` | Export selected |
| `Ctrl+Space` | Toggle caption preview |
| `Alt+←/→` | Caption nudge ±50 ms |
| `Alt+Shift+←/→` | Caption nudge ±10 ms |
| `Ctrl+wheel` | Zoom timeline |

---

## 7. Acceptance criteria

1. Paste a 45–90 min YouTube URL; candidates appear in ≤10 min on CPU (captions available),
   with stage progress and cancel.
2. Scrub a 60 min source with <200 ms seek latency using the 720p proxy.
3. Trim in/out is frame-accurate; exported clip matches preview within 1 frame.
4. Multi-segment clip up to 12 segments / 180 s; reorder and export correctly.
5. Caption edit appears in preview within 100 ms; export burns the same text/style.
6. Caption text is always inside the safe zone, not clipped, with no overlapping cues.
7. Batch export 5 clips with per-clip progress, cancel, and retry.
8. Close/reopen the app; project and edits restore; crash recovery restores the last autosave.
9. YouTube upload + `publishAt` succeeds on a test channel; TikTok export/draft produces a valid
   9:16 MP4 under 4 GB/10 min.
10. A user can take an AI clip, trim 2 s, fix one caption, change the crop, and export — in under
    two minutes.

---

## 8. Milestones

| Milestone | Scope | Done when |
|---|---|---|
| **M1 — Preview spike** | mpv embed, precise seek, ASS overlay, proxy/waveform | 60 min source scrubs <200 ms; frame step works |
| **M2 — Timeline v1** | single-track EDL, trim/split/delete/reorder, snapping, undo | 2-segment clip exports correctly |
| **M3 — Caption editor** | cue list, inline edit, retime, split/merge, styles, SRT/ASS | Edit one caption; export matches preview |
| **M4 — Crop editor** | mode selector, manual offset, safe-zone overlay | Change crop; export matches preview |
| **M5 — Projects** | SQLite store, autosave, crash recovery, render state | Restart restores everything |
| **M6 — Export/publish** | batch export, YouTube upload/schedule, TikTok draft | 5 clips exported; one private upload live |

---

## 9. Out of scope for the MVP

- Multi-track video compositing.
- Transitions, keyframes, colour grading, speed ramps.
- B-roll/stock footage, AI avatars, voice cloning, dubbing.
- Team collaboration, comments, brand kits.
- Mobile app.
- Full Descript-style ripple transcript editing (defer; add deletion-based cuts later).
- Direct TikTok public posting before an audit.
- Instagram/Reels upload (use export until a supported Graph API path is chosen).

---

## 10. Open decisions

1. **Preview stack:** commit to an LGPL libmpv build, or start with `QMediaPlayer` and accept
   keyframe-level seek until M1? Recommendation: spike mpv first; it is the one dependency that
   determines whether the editor feels professional.
2. **Project store:** SQLite (recommended for queries/recovery) vs JSON sidecars (simpler to diff).
   Recommendation: SQLite for state, JSON export for portability.
3. **Music:** per-clip music in MVP or only in compile? Recommendation: per-clip gain/ducking in
   MVP; a music library is out of scope.
4. **Score display:** show "relative rank" only, or blend with calibrated LLM confidence?
   Recommendation: show both, label them honestly, and never present a single clip as 100/100.
5. **TikTok:** export/draft only for v1. Direct Post requires an audit and a cloud scheduler for
   future posts; do not promise scheduling in the desktop app.

---

*This spec is deliberately smaller than a generic video editor. The product bet is a faster
review-and-correction loop than cloud clip tools, with local-first processing and a one-click
YouTube path — not a CapCut clone.*
