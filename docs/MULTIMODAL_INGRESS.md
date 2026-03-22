# Multimodal Ingress Foundation

> **Unified-Subject Architecture**: This module is owned by the **runtime shell**
> (`DesktopPresenceRuntime`) and provides *continuous host perception* — the ambient
> sensory layer of the subject on a Windows device.
>
> **Two multimodal paths — do not conflate**:
>
> | Path | Owner | Module | Lifetime | Purpose |
> |---|---|---|---|---|
> | **Continuous host perception** | Runtime shell | `core/multimodal/` (this doc) | Background loop | Ambient Windows environment awareness |
> | **Request-bound fusion** | Subject core (OpenClawd) | `core/perception/multimodal_bus.py` | Per-request | Caller-attached images/audio for a single request |
>
> See [`docs/UNIFIED_SUBJECT_ARCHITECTURE.md`](UNIFIED_SUBJECT_ARCHITECTURE.md) §4.

`core/multimodal/` provides the low-level multimodal perception pipeline for
Galaxy.  It ingests microphone audio and WebRTC camera video, extracts
lightweight state features, and merges everything into a single
**PerceptionFrame** stream that downstream reasoning layers consume.

The `DesktopPresenceRuntime` shell starts this pipeline via
`_try_start_ingest_bus()` during initialisation.  The `PerceptionFrame`
stream represents the subject's *continuous sensory awareness* of the
Windows host device — independent of any individual request.

---

## Architecture

```
Microphone ──► AudioIngestPipeline ──► AudioState ──┐
                                                     ├──► MultimodalIngressBus ──► PerceptionFrame
WebRTC Cam ──► VideoIngestPipeline ──► VideoState ──┤
                                                     │
System API ──► SystemSignals ────────────────────────┘
```

---

## Modules

| Module | Description |
|--------|-------------|
| `signal_quality.py` | `SignalQuality` / `QualityFlag` metadata |
| `vad.py` | Lightweight energy-based Voice Activity Detection |
| `audio_features.py` | `AudioState` feature extraction |
| `audio_ingest.py` | Microphone capture pipeline |
| `video_features.py` | `VideoState` feature extraction |
| `webrtc_session.py` | WebRTC peer-connection management |
| `video_ingest.py` | Camera ingest pipeline |
| `perception_frame.py` | `PerceptionFrame` unified snapshot |
| `ingress_bus.py` | `MultimodalIngressBus` — merges all signals |

---

## PerceptionFrame Schema (version 1)

```json
{
  "schema_version": 1,
  "frame_id": 42,
  "timestamp": 1234567.89,
  "wall_clock": 1711000000.0,
  "overall_quality": 0.85,
  "active_modalities": ["audio", "video"],

  "audio_quality": {
    "flag": "ok",
    "freshness_ms": 45.2,
    "confidence": 1.0,
    "message": null
  },
  "audio": {
    "energy": 0.12,
    "speaking_ratio": 0.71,
    "pause_density": 0.08,
    "noise_level": 0.23,
    "audio_freshness_ms": 45.2,
    "is_speaking": true
  },

  "video_quality": {
    "flag": "ok",
    "freshness_ms": 102.3,
    "confidence": 1.0,
    "message": null
  },
  "video": {
    "motion_level": 0.34,
    "scene_change_rate": 0.5,
    "face_presence": null,
    "video_freshness_ms": 102.3
  },

  "system_quality": {
    "flag": "missing",
    "freshness_ms": null,
    "confidence": 0.0,
    "message": "No system source"
  }
}
```

### Field descriptions

#### Top-level

| Field | Type | Description |
|-------|------|-------------|
| `schema_version` | int | Always `1` in this release |
| `frame_id` | int | Monotonically increasing per ingress bus |
| `timestamp` | float | Monotonic clock at frame construction |
| `wall_clock` | float | UTC wall time (`time.time()`) |
| `overall_quality` | float [0–1] | Mean confidence of usable modalities |
| `active_modalities` | list[str] | Modalities with `is_usable == True` |

#### AudioState fields

| Field | Type | Description |
|-------|------|-------------|
| `energy` | float ≥ 0 | RMS energy of the latest audio chunk |
| `speaking_ratio` | float [0–1] | Fraction of recent VAD frames with activity |
| `pause_density` | float [0–1] | Rate of speech→silence transitions |
| `noise_level` | float [0–1] | Spectral-flatness proxy (0 = tonal, 1 = noise) |
| `audio_freshness_ms` | float ≥ 0 | ms since the last chunk was processed |
| `is_speaking` | bool | Whether speech is currently detected |

#### VideoState fields

| Field | Type | Description |
|-------|------|-------------|
| `motion_level` | float [0–1] | Normalised mean-absolute-diff between frames |
| `scene_change_rate` | float ≥ 0 | Scene changes per second (rolling 10 s) |
| `face_presence` | float or null | `1.0`/`0.0` when Haar detection enabled, else `null` |
| `video_freshness_ms` | float ≥ 0 | ms since the previous frame |

---

## Quality Flags

`QualityFlag` communicates the availability and reliability of each modality.

| Flag | Meaning | `is_usable` |
|------|---------|-------------|
| `ok` | Signal is fresh and reliable | ✅ |
| `degraded` | Signal available but reduced quality | ✅ |
| `missing` | No source has provided this signal | ❌ |
| `stale` | Signal has not been updated within the threshold | ❌ |
| `permission_denied` | OS permission was refused | ❌ |
| `device_unavailable` | Hardware or library not present | ❌ |

Downstream consumers should check `quality.is_usable` before reading the
corresponding modality field; the field will be `None` whenever the quality
is not usable.

---

## Usage Examples

### Audio-only ingest

```python
from core.multimodal.audio_ingest import AudioIngestPipeline

pipeline = AudioIngestPipeline()

def on_audio(state, quality):
    if quality.is_usable:
        print(f"speaking={state.is_speaking} energy={state.energy:.3f}")

pipeline.add_callback(on_audio)
await pipeline.run()
```

### Full ingress bus

```python
from core.multimodal import MultimodalIngressBus
from core.multimodal.audio_ingest import AudioIngestPipeline
from core.multimodal.video_ingest import VideoIngestPipeline

bus = MultimodalIngressBus(tick_ms=200)
audio = AudioIngestPipeline()
video = VideoIngestPipeline()

audio.add_callback(bus.update_audio)
video.add_callback(bus.update_video)

q = bus.subscribe()

# Start everything concurrently
await asyncio.gather(
    audio.run(),
    video.run(),
    bus.run(),
)
```

### Inject system signals

```python
from core.multimodal.perception_frame import SystemSignals

bus.update_system(SystemSignals(screen_activity=0.6, cpu_load=0.3))
```

---

## Graceful Degradation

All ingest pipelines handle unavailable hardware without raising exceptions:

- **sounddevice not installed** → `AudioIngestPipeline.run()` returns immediately;
  quality flag set to `device_unavailable`.
- **Microphone permission denied** → caught and logged; quality → `permission_denied`.
- **aiortc not installed** → `VideoIngestPipeline` / `WebRTCCameraSession` degrade
  silently; quality → `device_unavailable`.
- **Stale signal** → bus automatically downgrades quality to `stale` after
  `stale_threshold_ms` (default 2 000 ms).

The `PerceptionFrame.overall_quality` and `active_modalities` fields give
downstream code a single point to check for signal health.
