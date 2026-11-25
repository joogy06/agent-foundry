# Safety-sensor validation method (leak sensor as the worked case)

Validate before the sensor becomes inaccessible (sealed behind tiles, in a void, in a ceiling). Each check produces a recorded number or a pass/fail with the time taken, so a later regression is visible. Record results in the consumer project's notes with the device's friendly name and IEEE address.

## Preconditions

- Coordinator on its final channel; routers paired in final positions.
- Sensor joined **in its final position** (or re-joined there).
- Critical notification script, unavailable watchdog and battery automation already deployed (`home-assistant`).
- A stopwatch, and a second person or phone to receive alerts.

## Checks

| # | Check | How | Pass when |
|---|---|---|---|
| 1 | Link | Read LQI and route in the stack's map with the sensor in place | Route goes via a router when the direct link is weak; LQI comparable to healthy devices |
| 2 | Link, worst case | Close doors/covers/panels as they will be; wake the sensor (press its button) and re-read | Still reports; route unchanged or better |
| 3 | Detect | Wet the probe/cable | HA entity goes `on`; record seconds from wetting |
| 4 | Alert | Same event, with each phone in Do Not Disturb / silent | Critical alert sounds on every phone; record seconds. Android: the `alarm_stream` channel's sound and DND-override settings decide this, so check them per phone |
| 5 | Repeat | Keep it wet | Repeat alerts arrive at the automation's interval (not the device's) |
| 6 | Clear | Dry the probe | Entity returns `off`; repeats stop |
| 7 | Battery | Read battery entity | A value is reported (not unknown) |
| 8 | Unavailable | Remove the battery (or power down its parent router) | Unavailable alert fires after the stack timeout + HA `for:`; record time. With a 25 h default battery timeout this takes a day: set the safety sensor's own timeout first, or shorten both temporarily for the test and restore them after |
| 9 | Router loss | Power down the router it uses | Sensor re-routes or goes unavailable and alerts: never silently dead |
| 10 | Coordinator reboot | Reboot the coordinator | Network resumes, no re-pair; offline alert fired during the outage |
| 11 | HA reboot | Reboot HA (or its VM) | Sensor state correct afterwards, no re-pair, no false leak alert |
| 12 | Backup | Take HA backup + Zigbee network backup after all joins | Both stored off-host with a date |

Checks 3-6 are repeated for any other sensor type with its own stimulus (motion: walk past, then time the clear timeout).

## Reading results

- Fail on 1-2: add a router nearer the sensor, re-join the sensor in place, re-test. Do not seal.
- Fail on 4 but pass on 3: the problem is the phone or payload (critical permission, channel settings), not Zigbee.
- Fail on 8 with no alert ever: availability is off in the stack, or HA's `for:` is longer than the test waited.
- Fail on 10-11 with re-pair needed: the network identity is not persisted; fix backups before continuing.

## Sign-off

The sensor may be sealed only when 1-12 pass, times are recorded, and the backup from check 12 exists.
