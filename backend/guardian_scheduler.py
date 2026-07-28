"""Guardian Profile Switch Scheduler Engine.

Runs a background task checking active profile switch rules once every 30 seconds.
When a rule's time of day (HH:MM) and day of week match, it applies the target
Guardian profile settings to the miner.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
from typing import Any

from backend import benchmark, db, guardian

logger = logging.getLogger("minerwatch.guardian_scheduler")

_scheduler_task: asyncio.Task | None = None


async def start_guardian_scheduler() -> None:
    """Start the background Guardian profile scheduler loop."""
    global _scheduler_task
    if _scheduler_task is None or _scheduler_task.done():
        _scheduler_task = asyncio.create_task(_scheduler_loop(), name="guardian-scheduler")


async def stop_guardian_scheduler() -> None:
    """Stop the background Guardian profile scheduler loop."""
    global _scheduler_task
    if _scheduler_task and not _scheduler_task.done():
        _scheduler_task.cancel()
        _scheduler_task = None


async def _scheduler_loop() -> None:
    """Check active profile switch schedules every 30 seconds."""
    logger.info("Started Guardian profile switch scheduler loop")
    while True:
        try:
            await check_and_execute_schedules()
        except asyncio.CancelledError:
            logger.info("Guardian profile switch scheduler loop stopped")
            break
        except Exception as e:
            logger.error("Error in Guardian profile switch scheduler loop: %s", e, exc_info=True)

        await asyncio.sleep(30)


async def check_and_execute_schedules() -> None:
    """Check all enabled profile switch schedules against current time and day."""
    now = datetime.datetime.now()
    curr_hhmm = now.strftime("%H:%M")
    curr_day = now.strftime("%a").lower()  # 'mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'
    now_epoch = int(now.timestamp())

    schedules = await db.get_all_enabled_guardian_schedules()
    for sched in schedules:
        sched_id = sched["id"]
        miner_id = sched["miner_id"]
        time_hhmm = sched["time_hhmm"]
        last_trig = sched.get("last_triggered_ts") or 0

        # Check time match
        if time_hhmm != curr_hhmm:
            continue

        # Prevent double-triggering within 60 seconds
        if now_epoch - last_trig < 60:
            continue

        # Check day match
        days_list = []
        if sched.get("days_json"):
            try:
                days_list = json.loads(sched["days_json"])
            except Exception:  # noqa: BLE001
                days_list = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

        if days_list and curr_day not in [d.lower() for d in days_list]:
            continue

        # Execute profile switch for miner!
        profile_name = sched.get("profile_name") or "Scheduled Profile"
        freq = sched.get("max_freq_mhz")
        volt = sched.get("voltage_mv")
        fan_max = sched.get("fan_max_pct")
        max_power = sched.get("max_power_w")

        logger.info(
            "Executing scheduled profile switch '%s' (ID %d) for miner #%d at %s",
            profile_name,
            sched_id,
            miner_id,
            curr_hhmm,
        )

        try:
            # Update Guardian DB config
            await db.set_guardian_config(
                miner_id,
                max_freq_mhz=freq,
                max_power_w=max_power,
                fan_max_override=fan_max,
            )

            # Reset Guardian governor state
            guardian.reset_miner(miner_id)

            # Apply frequency & voltage directly if set
            if freq and volt:
                await benchmark._apply_freq_and_volt(miner_id, freq, volt)

            if fan_max:
                await benchmark._set_fan_speed(miner_id, fan_max)

            # Log governor decision event
            async with db.connect() as conn:
                await conn.execute(
                    """
                    INSERT INTO governor_decisions (
                        miner_id, governor_type, ts, action_taken, reason, details
                    ) VALUES (?, 'guardian', ?, 'PROFILE_SWITCH', ?, ?)
                    """,
                    (
                        miner_id,
                        now_epoch,
                        f"Scheduled Profile Switch: {profile_name}",
                        json.dumps({
                            "profile_name": profile_name,
                            "freq_mhz": freq,
                            "voltage_mv": volt,
                            "fan_max_pct": fan_max,
                        }),
                    ),
                )

            # Update trigger timestamp
            await db.update_guardian_schedule_last_triggered(sched_id, now_epoch)

        except Exception as e:
            logger.error("Failed executing scheduled profile switch for miner #%d: %s", miner_id, e)
