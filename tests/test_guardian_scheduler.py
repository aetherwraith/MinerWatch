"""Tests for Guardian Profiles & Scheduled Profile Switcher."""

import pytest
from backend import db, guardian_scheduler


@pytest.mark.anyio
async def test_guardian_profiles_and_schedules_db():
    miner_id = await db.upsert_miner({
        "family": "bitaxe",
        "host": "192.168.1.98",
        "port": 80,
        "name": "Test Profile Miner",
        "enabled": 1,
    })

    try:
        # Create custom profile
        prof_id = await db.save_guardian_profile(miner_id, {
            "name": "Quiet Profile (Day)",
            "max_freq_mhz": 450,
            "voltage_mv": 1150,
            "fan_max_pct": 60,
        })
        assert prof_id > 0

        # Retrieve profiles
        profiles = await db.get_guardian_profiles(miner_id)
        assert len(profiles) >= 1
        custom_prof = next(p for p in profiles if p["id"] == prof_id)
        assert custom_prof["name"] == "Quiet Profile (Day)"
        assert custom_prof["max_freq_mhz"] == 450

        # Create schedule
        sched_id = await db.save_guardian_schedule(miner_id, {
            "profile_id": prof_id,
            "time_hhmm": "08:00",
            "days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
            "enabled": True,
        })
        assert sched_id > 0

        # Retrieve schedules
        schedules = await db.get_guardian_schedules(miner_id)
        assert len(schedules) == 1
        assert schedules[0]["time_hhmm"] == "08:00"
        assert schedules[0]["profile_name"] == "Quiet Profile (Day)"

        # Retrieve all active schedules
        all_enabled = await db.get_all_enabled_guardian_schedules()
        assert any(s["id"] == sched_id for s in all_enabled)

        # Clean up schedule and profile
        await db.delete_guardian_schedule(miner_id, sched_id)
        assert len(await db.get_guardian_schedules(miner_id)) == 0

        await db.delete_guardian_profile(miner_id, prof_id)
        profs_after = await db.get_guardian_profiles(miner_id)
        assert not any(p["id"] == prof_id for p in profs_after)

    finally:
        async with db.connect() as conn:
            await conn.execute("DELETE FROM miners WHERE id = ?", (miner_id,))
