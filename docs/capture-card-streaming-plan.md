# Capture Card Streaming Plan

> Status: planning only. No capture card is currently deployed.

## Goal

Move as much streaming work as practical off `lj-gaming-pc` and onto `media-vm`, while keeping the gaming PC focused on Fortnite.

The current relay path already moved platform fanout and VOD delivery off the gaming PC:

```text
Gaming PC OBS
  encoded SRT stream
    -> media-vm stream-relay.service
    -> Twitch + YouTube + VOD delivery
```

That still requires the gaming PC to run OBS, render the OBS scene, and encode one outgoing stream.

A capture-card workflow can remove some or all of that local OBS/encoding cost, depending on how it is wired.

## Expected Performance Gain

The realistic gain depends on which work leaves the gaming PC.

### Hybrid Capture Path

```text
Gaming PC OBS
  full-screen projector on second GPU output
    -> HDMI capture card attached to media-vm
    -> media-vm encodes/fans out/records
```

This removes the OBS stream encoder from the gaming PC, but OBS still runs and still renders the scene. Expected gain is modest unless the OBS encoder or local recording path is causing stutters.

### True Dual-PC Path

```text
Gaming PC game/video output
  second GPU output or clone
    -> HDMI capture card attached to media-vm
    -> OBS/FFmpeg composition and encoding on media-vm
```

This is the real "gaming PC does not encode stream video" path. The gaming PC can avoid OBS entirely or run much less OBS work. This has the best chance of improving 1% lows and reducing stream-time stutters, but it makes audio, webcam, overlays, alerts, and scene control more complicated.

### Important Expectation

Fortnite on the Ryzen 9 3900X appears more likely to be constrained by main-thread / CCD / memory-latency behavior than by raw GPU usage. A capture card can reduce streaming overhead, but it is not guaranteed to turn an inconsistent 145-170 FPS into a locked 200 FPS by itself.

Likely wins:

- lower OBS/encoder overhead on `lj-gaming-pc`
- no local recording write/mux cost on `lj-gaming-pc`
- cleaner VOD recording on `media-vm`
- fewer stream-time spikes from OBS, local recording, or multi-output fanout

Less likely:

- large Fortnite average-FPS gain when not streaming
- fixing CPU main-thread bottlenecks by itself

## Physical Wiring

Preferred wiring:

```text
Gaming PC GPU second output
  -> HDMI cable
  -> capture card
  -> TS440/media-vm
```

Avoid putting the capture card inline with the primary gaming monitor unless the card supports the exact resolution, refresh rate, VRR, HDR, and latency behavior needed for competitive play. Inline passthrough can silently cap refresh rate, break VRR, or add display quirks.

Safer options:

- Use a second GPU output dedicated to capture.
- Clone the main display only if Windows/NVIDIA does not force the primary monitor down to the capture card's mode.
- Use an OBS full-screen projector to the capture output for the hybrid path.

## Capture Hardware Classes

### Cheap USB UVC Capture Card

Good for proof-of-concept only.

Pros:

- lowest cost
- easiest to pass through to `media-vm`
- should appear as `/dev/video*` plus an ALSA audio device if UVC/UAC compliant

Cons:

- usually limited to 1080p60
- inconsistent color, latency, EDID behavior, and audio sync
- many cheap listings overstate capability

Use this only to prove the architecture has value before buying better hardware.

### Magewell USB Capture HDMI Gen 2 / Similar UVC Device

Good Linux-friendly external option.

Relevant official specs:

- Linux V4L2/ALSA support
- HDMI embedded audio
- USB 3.0
- OBS/VLC/GStreamer compatibility

This is the kind of device that fits `media-vm` best operationally, but it is not budget hardware.

### Elgato HD60 X / Similar Consumer Capture Card

Good gaming specs on paper, especially passthrough.

Relevant official specs:

- USB 3.0
- passthrough up to 2160p60, 1440p120, 1080p240, VRR, HDR
- capture up to 2160p30, 1440p60, 1080p60 HDR

Caveat: Elgato's official supported software list emphasizes Windows/macOS OBS and Elgato utilities. Treat Linux/media-vm compatibility as something to verify before purchase, not assume.

### Blackmagic DeckLink / Magewell PCIe

Best suited for a serious permanent media host setup.

Pros:

- PCIe stability
- official Linux driver/SDK options depending on vendor/model
- good for rack/server workflows

Cons:

- higher cost
- Proxmox PCIe passthrough and IOMMU grouping work
- proprietary driver maintenance in the Blackmagic case
- physical slot availability in the TS440 must be checked

## media-vm Feasibility

This is feasible with the current architecture.

`media-vm` already has the Quadro P2200 for NVENC. The capture card would become the input device, and the relay would encode on the Quadro and keep the existing fanout/VOD model.

USB path:

```text
capture card on TS440 USB 3
  -> Proxmox USB device passthrough
  -> media-vm /dev/videoX + ALSA input
  -> FFmpeg or OBS on media-vm
```

PCIe path:

```text
PCIe capture card in TS440
  -> Proxmox PCIe passthrough
  -> media-vm vendor driver or V4L2 device
  -> FFmpeg or OBS on media-vm
```

USB is the first deployment target because it is cheaper to test and less invasive.

## Deployment Phases

### Phase 0: Baseline Current Relay

Before buying hardware, capture a clean baseline with the current setup:

- Fortnite actual match or 1v1 realistic
- OBS streaming to media-vm relay
- no local OBS recording
- PresentMon capture
- OBS stats if available
- media-vm relay logs

Compare average FPS, 1%/0.1% lows, frame-time spikes, CPU busy, GPU busy, OBS CPU/GPU, and NVENC usage.

### Phase 1: Cheap USB Proof-Of-Concept

Use a cheap UVC HDMI capture card if one can be borrowed or bought cheaply.

Objectives:

- confirm TS440 USB passthrough to `media-vm`
- confirm `media-vm` sees `/dev/video*`
- confirm HDMI audio appears
- record a local test file on `media-vm`
- stream to a local/null output without touching Twitch/YouTube

This can be tested without going live.

### Phase 2: Ansible Device Management

Add repo-managed support:

- `media-vm` packages: `v4l-utils`, `alsa-utils`
- optional udev rule for persistent capture-card symlink
- inventory vars for capture input device, audio device, resolution, frame rate, and pixel format
- health check extension that verifies signal/device presence
- docs for the physical wiring and rollback

### Phase 3: Relay Input Mode

Extend the stream relay to support input modes:

- `srt` for the current OBS network input
- `capture-card` for `/dev/video*` + ALSA input

The capture-card mode should reuse:

- Quadro P2200 NVENC encode
- Twitch/YouTube fanout
- VOD recording and mover
- Astra/local health checks

### Phase 4: Audio, Webcam, And Overlays

Decide which composition model is being used.

Hybrid model:

- Gaming PC OBS still owns scenes, webcam, alerts, and overlays.
- OBS projector goes to the capture output.
- Audio stays simple because OBS can mix it before projection/capture if routed correctly.

True dual-PC model:

- media-vm owns scenes and encoding.
- Gaming PC sends game video and game audio.
- Mic, webcam, alerts, browser sources, chat overlays, and Apple Music/SonoBus need to feed media-vm or be recreated there.

The true dual-PC model is more performant but significantly more operational work.

### Phase 5: A/B Benchmark

Compare:

1. Current OBS-to-SRT relay.
2. Hybrid OBS projector-to-capture-card.
3. True game-output-to-capture-card, if practical.

Use the same benchmark harness and same Fortnite scenario as much as possible.

### Phase 6: Production Cutover

Only cut over if the A/B test proves value.

Production requirements:

- one-command rollback to current SRT relay
- capture-card health alert through `stream-relay-health`
- no public go-live needed for local capture tests
- no dependency on display clone behavior that caps the main monitor
- documented startup checklist in `docs/streaming-runbook.md`

## Source Notes

- Magewell USB Capture HDMI Gen 2 official specs list Linux V4L2/ALSA support and OBS/VLC/GStreamer compatibility: https://www.magewell.com/tech-specs/usb-capture-hdmi-gen-2
- Elgato HD60 X official specs list passthrough/capture capabilities, but official supported software is Windows/macOS-focused: https://help.elgato.com/hc/en-us/articles/5293216945805-Elgato-Game-Capture-HD60-X-Technical-Specifications
- Blackmagic DeckLink model specs list Linux SDK support and PCIe capture models: https://www.blackmagicdesign.com/products/decklink/models
