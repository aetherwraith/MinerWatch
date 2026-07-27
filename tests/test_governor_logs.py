# SPDX-License-Identifier: AGPL-3.0-only
import pytest
from backend import db


@pytest.mark.anyio
async def test_governor_decisions_db(tmp_path, monkeypatch):
    test_db = tmp_path / "test.db"
    monkeypatch.setattr("backend.config.db_path", lambda: test_db)
    await db.init_db()

    # Add dummy miner
    miner_id = await db.upsert_miner({"name": "TestMiner", "family": "bitaxe", "host": "192.168.1.100"})

    # Insert decisions
    d1 = await db.insert_governor_decision(
        miner_id=miner_id,
        governor_type="guardian",
        action_taken="STEP_DOWN",
        reason="VR temp 78.5C > 75C",
        chip_temp=62.0,
        vr_temp=78.5,
        target_chip_temp=60.0,
        target_vr_temp=75.0,
        details={"freq_from": 800, "freq_to": 775},
    )
    assert d1 > 0

    d2 = await db.insert_governor_decision(
        miner_id=miner_id,
        governor_type="autofan",
        action_taken="FAN_ADJUST",
        reason="Fan adjusted 50% -> 60%",
        chip_temp=61.0,
        vr_temp=65.0,
        target_chip_temp=60.0,
        target_vr_temp=60.0,
        details={"fan1_pct": 60, "fan2_pct": 60},
    )
    assert d2 > 0

    # Fetch decisions
    all_dec = await db.get_governor_decisions(miner_id)
    assert len(all_dec) == 2

    guard_dec = await db.get_governor_decisions(miner_id, governor_type="guardian")
    assert len(guard_dec) == 1
    assert guard_dec[0]["action_taken"] == "STEP_DOWN"
    assert guard_dec[0]["details"]["freq_to"] == 775

    # Fetch history
    history = await db.get_governor_history(miner_id, hours=24)
    assert len(history) == 2
