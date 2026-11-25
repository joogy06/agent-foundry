# Choosing cameras for Frigate

<!-- FRESHNESS:v1
volatility: medium
anchors:
  - kind: external_fact
    subject: frigate-camera-recommendations
    source_url: https://docs.frigate.video/frigate/hardware
    verified_on: 2026-09-27
    review_by: 2027-03-27
    claim: "Docs prefer Dahua, Hikvision, Amcrest; avoid Wi-Fi cameras; Reolink <=5MP via http-flv; H.264 widest compatibility."
-->

Labels: **[V]** fetched 2026-09-27 from docs.frigate.video (hardware, camera_setup, camera_specific pages); **[I]** inferred.

## Must-haves

| Requirement | Why |
|---|---|
| A **supported local stream** (RTSP, or a model-specific one such as Reolink http-flv [V]), ideally ONVIF, no cloud account needed | Frigate ingests local streams only; test the exact model against the camera_specific docs |
| A configurable **sub stream** (~720p) | Detection runs on it; the main stream is for recording [V] |
| Wired Ethernet, PoE | Docs advise against Wi-Fi cameras [V]; PoE lets the switch power-cycle a hung camera |
| **H.264** available on at least the sub stream | Widest HA and browser playback compatibility; H.265 has limited browser support [V] |
| Adjustable I-frame interval, constant bitrate | Clean segment boundaries; docs suggest ~30 main / ~5 sub [V] |
| Firmware that works with no internet access | So the camera can live on a blocked VLAN [I] |

## Brand notes

- Preferred by the docs: **Dahua**, **Hikvision**, **Amcrest** (rebadged Dahua) [V]. Dahua main stream path `/cam/realmonitor?channel=1&subtype=0`; Hikvision `/streaming/channels/101` [V].
- **Reolink**: at 5MP or less use the http-flv stream; newest 6MP+ models http-flv with FFmpeg 8 or RTSP with enhanced H.265; older 6MP+ RTSP; set "On, fluency first" [V camera_specific].
- **Tapo**: has RTSP once a camera account is created in the Tapo app [I]; acceptable indoors, weaker outdoors [I].
- **Cloud-only** (no local RTSP; e.g. Ring, Nest, Blink [I, not named in Frigate docs]): avoid for Frigate.

## Placement and privacy

- Aim for faces/bodies at 2-3 m height, not straight down [I].
- Do not point cameras at neighbours' property or public space without checking local law (UK: ICO domestic CCTV guidance) [I].
- Record decisions (stream URLs, credentials location) in the project notes; credentials go in Frigate's environment variables (`{FRIGATE_RTSP_PASSWORD}`) [I], never plain in a committed config.
