# Cortex

A shared brain for Home Assistant: one household memory, one set of speech rules, safety and health checks, and a tariff-aware energy controller for a solar + battery + EV home. Built for an AGL time-of-use plan with a Neovolt/Sungrow battery and a BYD EV, but every entity, rate and window is a setting.

## What it does

| Area | Features |
|---|---|
| Memory | Durable household facts, near-duplicate merging, recall by keyword. Exposed to any conversation agent through the `cortex` LLM API (tools: remember, recall, forget, remind, energy_status, run_routine, security_check). |
| Speech rules | Quiet hours (urgent gets through), banned words, repeat suppression, hush, room choice from recent motion, delivery by `assist_satellite.announce` or `tts.speak`, phone push for urgent. |
| Safety and health | Smoke, CO, gas, water, tamper and safety sensors detected automatically and announced urgently. Five-minute check for low batteries, offline devices and pending updates. |
| Watches and reminders | Speak when an entity changes (with cooldown). Timed reminders that survive restarts. |
| Energy | Tariff period, import and feed-in rate, next change, export needed to cover the daily charge, solar forecast vs need, battery and EV stored/usable/room kWh, one-line summary. |
| Energy control (off by default) | Shoulder-window grid top-up only when forecast solar cannot cover battery and EV needs, evening export while feed-in is high, EV plug-in gate for the cheap window. |
| Briefings | Morning and evening briefing at set times with chosen sections (energy, weather, reminders, health, security, parcels); optional AI polish. Weekly report on Sundays with stats from the timeline. |
| Routines | Named step lists (say, push, any service, delay) run on demand, on a schedule, or when an entity changes. Assistants can run them with the `run_routine` tool. |
| Learning | Watches the entities you pick, finds things you do at the same time each day and "A then B" chains, and offers them as suggestions you can turn into routines with one click. Plain code, no model calls. |
| Night watch and security | Doors and windows opening at night are announced urgently; `security_check` is a read-only sweep of open doors, unlocked locks and disarmed alarms. |
| Visitors and parcels | Doorbell press grabs a camera still, asks your own AI Task entity what it shows, announces it, tracks parcels until you mark them collected. Camera spots (for example "front porch") give the model context. |
| Camera watches | A watch can add a camera look and/or a short AI remark. Calls are capped per hour. |
| Motion lights | Lights on with motion when it is dark (lux sensor or sun), off after a delay; only turns off lights it turned on. |
| Heating pre-warm | Starts a climate entity early enough to reach a target by a set time; learns how fast the room warms. |
| Voice room | Replies go to the room where someone last spoke to a satellite, falling back to recent motion. |
| Backup | JSON backup of everything Cortex remembers under `cortex_backups/` (last 10 kept, weekly if enabled) and `restore`. |
| Panel | Sidebar page: rate schedule chart, storage, health, suggestions, routines, security, visitors and camera spots, weekly stats, timeline, memory manager, speech log, backup. |

## Install

1. HACS > Custom repositories > add this repo as an **Integration**.
2. Install Cortex, restart Home Assistant.
3. Settings > Devices & services > Add integration > Cortex.
4. Configure: **Voice and rules** (speakers, quiet hours), **Briefings and reports**, **House, cameras and learning** (AI Task entity, doorbell, night watch), **Energy and EV** (entities, capacities), **Tariff rates**.
5. In your voice assistant settings, enable **Cortex** next to Assist under *Control Home Assistant*.

Energy actions are off by default. If you already run HA automations for the same top-up or export, disable them before switching Cortex's on, or both will drive the battery.

## Services

`cortex.say`, `ask`, `remember`, `recall`, `forget`, `remind`, `cancel_reminder`, `watch`, `unwatch`, `briefing`, `hush`, `run_checks`, `energy_action` (`topup`, `export`, `stop`; `force` skips the checks), `save_routine`, `delete_routine`, `run_routine`, `accept_suggestion`, `dismiss_suggestion`, `add_motion_light`, `remove_motion_light`, `add_heating`, `remove_heating`, `security_check`, `look`, `set_spot`, `parcels_collected`, `weekly_report`, `backup`, `restore`. `watch` also takes `ai` and `camera`.

## Tariff model

- Shoulder 10:00-14:00 daily. Peak 16:00-20:00 on business days only (not weekends or public holidays). Everything else off-peak.
- High-season peak rate November to March, low-season April to October.
- Feed-in: evening 17:00-21:00, morning 07:00-08:00, other times a low rate.
- Public holidays come from a calendar entity (for example `calendar.australia_nsw`). Only today is looked up, so "next change" assumes tomorrow is not a holiday.

## Sensors

Tariff period, import rate, feed-in rate, next period, next change, export to cover daily charge, solar shortfall, solar day, battery stored / usable / room left, EV stored / room left, storage summary, energy summary, memories, last spoken, likely room, house health issues, routine suggestions, visitors today, parcels waiting, security issues, last event.

## Development

```
pip install -r requirements_test.txt
pytest -q
```

MIT licensed.
