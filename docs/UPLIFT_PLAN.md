# Uplift Plan — From "LLM Guesses" to a Signal-Fused Clip Ranker

Goal: make clip selection measurably better **without changing the product shape**.
Same CLI, same `output/<video_id>/clips.json`, same pipeline stages. What changes is
*how clips are chosen*: the LLM stops being the sole judge and becomes one feature
among several measurable signals.

No GPUs, no model training. Everything below runs on CPU with deps we already ship
(yt-dlp, faster-whisper → numpy, ffmpeg) — plus nothing else in Phase 1.

---

## 1. Honest diagnosis of the current system

Pipeline today: `download → transcribe → LLM single-shot → time-overlap dedupe →
boundary snap → min-score → top-N`.

| # | Weakness | Evidence in code | Consequence |
|---|---|---|---|
| W1 | **LLM is the only scorer.** Score 0–100 comes from one generation, temperature 0.7 (OpenAI path) | `highlights.py: call_highlight_api`, `llm.py: temperature=0.7` | Scores are noisy and non-reproducible; same video can rank clips differently across runs |
| W2 | **Zero audience data.** YouTube publishes the "Most Replayed" heatmap; we ignore it | `downloader.py` fetches info dict but only keeps id/title/duration in `meta.json` | We guess what viewers replay when YouTube will just tell us |
| W3 | **Chunk scores aren't calibrated.** Long videos are split into 20-min chunks; each chunk's LLM invents its own 0–100 scale | `get_highlights`: chunk results merged by raw score | A mediocre chunk's "92" beats a great chunk's "88"; top-N is biased by chunk luck |
| W4 | **Dedupe is time-only.** >50% time overlap suppresses; the same story retold at minute 5 and minute 40 both survive | `dedupe_highlights` | Near-duplicate clips in output |
| W5 | **Tone is invisible.** Laughter, shouting, dramatic pauses — none of it reaches the ranker | transcript-only prompt | Misses "you had to hear it" moments; over-ranks dry text that reads well |
| W6 | **Chapters ignored.** Creator-authored chapter titles ("the mistake that cost me everything") are strong priors | info dict `chapters` discarded | Free editorial signal wasted |
| W7 | **LLM gets no hints.** The prompt contains only the transcript | `HIGHLIGHT_SYSTEM_PROMPT` | The one expensive call we make is under-informed |

Verified feasibility (2026-07-17, yt-dlp 2026.07.04):

- `extract_info(download=False)` returns `heatmap`: 100 points of
  `{start_time, end_time, value ∈ [0,1]}` — the exact graph YouTube renders over
  the seek bar. **No scraping, no new dependency.**
- Same call returns `chapters`: `[{start_time, end_time, title}]` when the video has them.
- **Both are None on low-view videos** (confirmed on our test video). Every design
  below must degrade gracefully to transcript+audio only.

---

## 2. Target architecture

```
download ──► signals.py ──────────────┐  (heatmap + chapters, cached in meta.json)
    │                                 │
transcribe ─► audio_energy (RMS/pause)│  (numpy over ffmpeg PCM — no new deps)
    │                                 │
    ├─► candidates (semantic bounds) ─┤
    │                                 ▼
    └─► LLM scoring (hint-enriched) ─► rerank.py: weighted fusion ─► dedupe (time+text)
                                                     │
                                          boundary snap → min-score → top-N
                                                     │
                                        clips.json (+ per-clip signal breakdown)
```

Two new modules, three edited ones. Nothing else moves.

| File | Change |
|---|---|
| `shorts_generator/signals.py` | **new** — heatmap, chapters, audio energy, candidate windows |
| `shorts_generator/rerank.py` | **new** — weighted fusion, semantic dedupe |
| `shorts_generator/downloader.py` | persist `heatmap`/`chapters` into `meta.json`; backfill probe for cached videos |
| `shorts_generator/highlights.py` | accept `hints` (chapters, peaks) into prompt; rank-normalize per chunk |
| `shorts_generator/pipeline.py` | wire signals → rerank between `get_highlights` and payload build |

---

## 3. The six upgrades

### 3.1 Replay-peak integration (highest ROI)

**Get the data.** In `download_youtube` we already call `extract_info`. Persist
`heatmap` and `chapters` into the existing `meta.json` sidecar. For videos cached
before this change, do **one** lightweight `extract_info(download=False)` probe and
write the result (including explicit `"heatmap": null` so we never re-probe).

**Use the data twice:**

1. *Hint (pre-LLM):* top-5 peak windows injected into the prompt —
   `"Audience replay peaks (from YouTube analytics): 02:04–02:33, 15:10–15:45, …
   Moments overlapping these deserve close attention."*
2. *Feature (post-LLM):* `replay_score(clip) = mean(heatmap value over clip window)`,
   rank-normalized within the video.

**Ship the graph.** Write the raw 100 points to `output/<video_id>/heatmap.json`
(the exact data a future UI needs to draw the seek-bar graph) and print a cheap
CLI sparkline per video so you can *see* the peaks today:

```
replay  ▂▁▁▃▇█▅▂▁▁▂▃▂▁▁▁▄▆▃▂▁▁▁▂▅▇▄▂▁▁  (peaks: 02:04, 15:10, 31:22)
```

**Fallback:** heatmap absent → feature weight redistributes (see 3.3), hint line
omitted. Zero behavior change for small videos.

### 3.2 Audio-energy scoring

No librosa, no new deps. faster-whisper already pulls in numpy; ffmpeg is already
required.

```
ffmpeg -i source.mp4 -ac 1 -ar 16000 -f s16le -   →   numpy int16 buffer
```

Per 1-second window compute:

- **RMS loudness** → smoothed, rank-normalized → "energy" curve
- **Spikes**: windows > μ + 2σ (laughter, shouting, applause proxies)
- **Dramatic pauses**: ≥1.5s near-silence immediately followed by a spike —
  the classic "…and then everything changed" setup

`audio_score(clip)` = 0.6·mean energy + 0.4·spike/pause bonus in window.
Cache the curve as `output/<video_id>/audio_energy.json` (computed once per video,
~seconds of CPU). Feed the top spike times into the LLM hint block as well.

### 3.3 Weighted reranker (the piece that ties it together)

Every feature is **rank-normalized to [0,1] within the video** (rank / n), which
kills both the LLM chunk-calibration problem (W3) and cross-signal scale mismatch.

```
final = w_llm·llm + w_replay·replay + w_audio·audio + w_chapter·chapter
defaults:  0.45      0.25            0.20             0.10
```

**Missing-signal rule:** absent signals drop out and remaining weights renormalize
to sum 1. A no-heatmap, no-chapter video scores on `0.69·llm + 0.31·audio` — never
on made-up zeros that would silently punish small channels.

Weights are env-tunable (`RERANK_WEIGHTS=llm:0.45,replay:0.25,audio:0.20,chapter:0.10`),
not a config framework — one env var, parsed in `config.py`.

**Transparency:** each clip in `clips.json` gains a `signals` block:

```json
"signals": {
  "llm": 0.91, "replay": 0.80, "audio": 0.55, "chapter": 1.0,
  "final_score": 78.4, "signals_present": ["llm","replay","audio","chapter"]
}
```

`score` stays (now the fused score, same 0–100 range) so the output contract and
`--min-score` keep working unchanged.

### 3.4 Candidate generation from semantic boundaries

Today the LLM free-picks windows from raw text. Cheap structure helps it and gives
the reranker aligned units:

- **Pause boundaries:** gaps ≥ 1.0s between segments (already in the transcript, free)
- **Topic shifts:** Jaccard similarity of content-word sets between adjacent 30s
  blocks; local minima = topic boundary. Pure Python, zero deps.
- **Signal peaks:** replay peaks and audio spikes contribute boundary points.

These become a `Natural clip boundaries near: 02:04, 05:30, …` hint in the prompt,
and boundary snapping prefers them over bare segment edges. The LLM still chooses
the moments — it just stops cutting mid-thought and stops hallucinating windows
that straddle two topics.

*(Deliberately not doing sentence-transformers embeddings in Phase 1: +2GB of
torch for a marginal gain over Jaccard on this task. Revisit only if topic
detection measurably underperforms — the interface stays the same.)*

### 3.5 Transcript similarity dedupe

Keep the existing time-overlap pass, then add: for any two kept clips, compute
Jaccard similarity of their `transcript_excerpt` content words. **> 0.6 → drop the
lower-scoring one.** Catches the "same story retold in the recap" duplicate that
time overlap can never see. ~15 lines, zero deps.

### 3.6 Chapter-aware boost

When chapters exist:

- Inject titles+times into the LLM hint block (creator-curated table of contents).
- `chapter_score(clip) = 1` if its chapter title matches interest patterns
  (`mistake|truth|secret|why|how i|nobody|wrong|confession|fight|exposed|reveal|worst|best`…),
  else 0.5; no chapters → signal absent (weight redistributes).

### 3.7 Context-aware peak expansion (setup → peak → payoff)

A peak is the *payoff*; on its own it confuses viewers who never saw the setup.
Whenever a clip's window overlaps a replay peak or an audio spike, expand it so the
audience gets the context that *led* to the moment — don't just cut the explosion,
cut the fuse.

**Lead-in (start expansion):**

1. Take the earliest peak inside the clip window.
2. Walk **backwards at least `PEAK_LEAD_SECONDS` (default 5s)** from the peak start.
3. Keep walking back to the nearest *setup boundary* — the first of:
   a pause boundary (≥1.0s gap), a sentence start, or a tone-shift onset
   (the point where the audio-energy curve starts rising toward the spike —
   walk back from the spike until energy falls to its rolling baseline).
4. Hard cap the total lookback at `PEAK_LEAD_MAX_SECONDS` (default 20s) so we
   never drag in an unrelated prior topic.

The point of step 3: a blind "minus 5 seconds" starts clips mid-word and
mid-thought. Five seconds is the *minimum* context; the sentence/tone boundary is
the *actual* cut point. That is what makes the lead-in feel intentional
(foreshadowing) instead of accidental.

**Tail (end expansion):** extend the end by `PEAK_TAIL_SECONDS` (default 5s),
then snap forward to the sentence end as usual — the reaction/laughter after a
peak is part of the payoff and routinely gets guillotined by exact cuts.

**Where it lives:** one pass in `rerank.py` after fusion, before the existing
boundary snap (which then just polishes edges as today). Duration guard: if
expansion pushes a clip past 180s, trim the *tail* first, never the lead-in —
context beats trailing reaction.

**Env knobs:** `PEAK_LEAD_SECONDS=5`, `PEAK_LEAD_MAX_SECONDS=20`,
`PEAK_TAIL_SECONDS=5`. Clips with no overlapping peak are untouched — the
LLM already chose their hook line as the opener, and padding those would
*bury* the hook 5 seconds in, hurting scroll-stop. Expansion is peak-anchored
by design, not global.

---

## 4. What explicitly does NOT change

- CLI: all flags work identically (`--num-clips`, `--min-score`, `--render`, `--force`…)
- `clips.json` schema: only **adds** the `signals` block and `heatmap.json` sidecar
- Captions module, queue, downloader quality policy: untouched
- No new Python dependencies in Phase 1
- LLM call count: unchanged (hints ride along in the existing prompt)

---

## 5. How we know it actually improved (no "code without improvement")

1. **Replay-holdout validation** — the built-in ground truth. On videos *with* a
   heatmap, run the pipeline **with replay weight forced to 0** and measure how well
   the picks land on real replay peaks (mean heatmap value of chosen windows vs.
   random-window baseline). If audio/semantic/chapter signals push this number up
   versus the LLM-only pipeline, they are genuinely finding what audiences rewatch —
   proven against data the ranker never saw. Script: `eval/replay_holdout.py`,
   runnable on any 10–20 public URLs, CPU-only, no labels needed.
2. **Stability check** — run the same video 3×; measure clip-set overlap. Fused
   ranking must be strictly more stable than today's LLM-only ranking (it will be:
   3 of 4 signals are deterministic).
3. **Duplicate rate** — count near-duplicate pairs (excerpt Jaccard > 0.6) in top-5
   across a test set, before vs. after 3.5. Target: zero.
4. **Eyeball file** — `signals` block per clip makes every ranking decision
   auditable: *why* did clip 2 beat clip 3 (replay 0.9 vs audio-only 0.4)?

Acceptance bar: (1) improves vs LLM-only, (2) improves, (3) hits zero — otherwise
the offending signal's weight goes to 0 by default and we say so.

---

## 6. Build order (each step ships alone and is testable alone)

| Step | What | Size | Depends on |
|---|---|---|---|
| 1 | `signals.py`: heatmap+chapters fetch/cache; `heatmap.json`; CLI sparkline | S | — |
| 2 | `rerank.py`: rank-normalize + weighted fusion + missing-signal rule; `signals` block in clips.json | M | 1 |
| 3 | LLM hints: peaks + chapters + boundaries into prompt | S | 1 |
| 4 | Audio energy in `signals.py` (ffmpeg→numpy RMS/spike/pause) + weight in fusion | M | 2 |
| 5 | Context-aware peak expansion (3.7: lead-in to setup boundary + tail pad) | M | 2, 4 |
| 6 | Transcript-similarity dedupe | S | — |
| 7 | Semantic boundary candidates + snap preference | M | — |
| 8 | `eval/replay_holdout.py` + stability script | S | 2 |

Steps 1–3 are one sitting and already deliver the two biggest wins (real audience
data + calibrated fusion). 4–8 are independent after that.

---

## 7. Later (out of scope now, noted so we don't re-litigate)

- Sentence-embedding topic model (only if Jaccard proves too coarse)
- Laughter/applause audio classifier (only if RMS spikes prove too noisy)
- Visual features (scene cuts, face count) — needs the render path, wait for UI
- SponsorBlock segment exclusion — cheap, do alongside UI work
- UI: seek-bar heatmap graph + clip markers — `heatmap.json` from Step 1 is exactly
  the data contract it needs
