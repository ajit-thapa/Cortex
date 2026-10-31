# Cortex

A shared brain for Home Assistant: one household memory, one set of speech rules, safety and health checks, and a tariff-aware energy controller for a solar + battery + EV home. Built for an AGL time-of-use plan with a Neovolt/Sungrow battery and a BYD EV, but every entity, rate and window is a setting.

## What it does

| Area | Features |
|---|---|
| Memory | Durable household facts, near-duplicate merging, recall by keyword. Exposed to any conversation agent through the `cortex` LLM API (tools: remember, recall, forget, remind, energy_status). |
| Speech rules | Quiet hours (urgent gets through), banned words, repeat suppression, hush, room choice from recent motion, delivery by `assist_satellite.announce` or `tts.speak`, phone push for urgent. |
| Safety and health | Smoke, CO, gas, water, tamper and safety sensors detected automatically and announced urgently. Five-minute check for low batteries, offline devices and pending updates. |
| Watches and reminders | Speak when an entity changes (with cooldown). Timed reminders that survive restarts. |
| Energy | Tariff period, import and feed-in rate, next change, export needed to cover the daily charge, solar forecast vs need, battery and EV stored/usable/room kWh, one-line summary. |
| Energy control (off by default) | Shoulder-window grid top-up only when forecast solar cannot cover battery and EV needs, evening export while feed-in is high, EV plug-in gate for the cheap window. |
| Panel | Sidebar page: rate schedule chart, storage, health, reminders, watches, memory manager, speech log. |

## Install

1. HACS > Custom repositories > add this repo as an **Integration**.
2. Install Cortex, restart Home Assistant.
3. Settings > Devices & services > Add integration > Cortex.
4. Configure: **Voice and rules** (speakers, quiet hours), **Energy and EV** (entities, capacities), **Tariff rates**.
5. In your voice assistant settings, enable **Cortex** next to Assist under *Control Home Assistant*.

Energy actions are off by default. If you already run HA automations for the same top-up or export, disable them before switching Cortex's on, or both will drive the battery.

## Services

`cortex.say`, `ask`, `remember`, `recall`, `forget`, `remind`, `cancel_reminder`, `watch`, `unwatch`, `briefing`, `hush`, `run_checks`, `energy_action` (`topup`, `export`, `stop`; `force` skips the checks).

## Tariff model

- Shoulder 10:00-14:00 daily. Peak 16:00-20:00 on business days only (not weekends or public holidays). Everything else off-peak.
- High-season peak rate November to March, low-season April to October.
- Feed-in: evening 17:00-21:00, morning 07:00-08:00, other times a low rate.
- Public holidays come from a calendar entity (for example `calendar.australia_nsw`). Only today is looked up, so "next change" assumes tomorrow is not a holiday.

## Sensors

Tariff period, import rate, feed-in rate, next period, next change, export to cover daily charge, solar shortfall, solar day, battery stored / usable / room left, EV stored / room left, storage summary, energy summary, memories, last spoken, likely room, house health issues.

## Development

```
pip install -r requirements_test.txt
pytest -q
```

MIT licensed.
