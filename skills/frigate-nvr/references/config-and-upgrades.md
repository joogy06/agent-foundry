# Frigate config changes by version

<!-- FRESHNESS:v1
volatility: high
anchors:
  - kind: external_fact
    subject: frigate-breaking-changes
    source_url: https://github.com/blakeblackshear/frigate/releases
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "Breaking changes 0.15-0.18 as listed; 0.18.0 released 2026-09-12."
-->

Source: the GitHub release notes for each tag (https://github.com/blakeblackshear/frigate/releases), fetched 2026-09-27 [V] unless marked [I]. Always read the notes of **every** major you cross, and back up `config.yml` and the database first.

| Version (date) | Change that breaks old configs |
|---|---|
| 0.15.0 (2025-02-08) | `record` split: `alerts` and `detections` each take `retain`; FFmpeg 7, some Intel users move from `preset-vaapi` to `preset-intel-qsv-h264/h265`; detector `model` block became `model_path`; SHM rewrite warns when `shm_size` is too low |
| 0.16.0 (2025-08-16) | `tensorrt` detector removed for Nvidia GPUs, use `onnx`; `rocm` detector removed, use `onnx` with the `-rocm` image; **object detection off by default**, set `detect: enabled: true`; `preset-record-generic-audio-copy` becomes `-aac`; Viewer role and required proxy role mapping; Bookworm base; HA app config moved to its own config dir as `config.yml` |
| 0.17.0 (2026-02-27) | Tiered retention: `record.continuous` and `record.motion`; GenAI fields moved to `objects.genai`; remove `strftime_fmt`; go2rtc `exec`/`expr`/`echo` sources disabled unless `GO2RTC_ALLOW_ARBITRARY_EXEC`; GTX 900 series dropped; YOLOv9 on Coral |
| 0.18.0 (2026-09-12) | Multi-provider GenAI with `roles`; snapshots saved as clean `.webp` only, `clean_copy` removed; zones/masks gain `enabled` and `friendly_name`; FFmpeg 8.1.1 and a go2rtc hardware-transcode config change; Intel GPU stats need host kernel 6.5+; `sync_recordings`, `timelapse_args`, `ui.date_format`/`time_format` removed; DeGirum detector removed; DeepStack deprecated (removed in 0.19); UI-based full config, Profiles switchable via MQTT `frigate/profile/set` |

## Upgrade procedure

1. Read notes for every version between current and target.
2. Stop Frigate; copy `config.yml` and `frigate.db`.
3. Pull the new image tag (pin a version tag, not only `stable`, so a rollback is one line).
4. Start, read the log for config validation errors, fix, restart.
5. Confirm detection, recording, and that HA entities still update over MQTT.
6. Keep the old tag and backups until a week of recordings looks right.

## Reference config

Each running Frigate serves its full reference config in the docs for that version (docs.frigate.video/configuration/reference). Copy keys from the docs matching the **running** version, never from a blog post of unknown date.

## Model/detector notes

- RF-DETR is not listed in the 0.18 detector docs [V absence]; do not promise it.
- Nvidia: the `-tensorrt` image with `onnx` detector and `preset-nvidia` decode, plus the compose `deploy.resources.reservations.devices` GPU block [V-summary].
- Jetson: `-tensorrt-jp6` image, `preset-jetson-h264/h265` [V].
- Coral device paths: USB `/dev/bus/usb`, PCIe `/dev/apex_0` [V installation].
