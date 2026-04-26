"""
tests/test_pr9_stability_idempotency.py
========================================

PR9 — Stability + Idempotency test suite.

Covers:
  1. Heartbeat timeout & auto-offline with grace period (UDM).
  2. Device registration de-duplication (UDM).
  3. Idempotent task-result handling in MessageHandler.
  4. Idempotent task-result handling in DeviceRouter.
  5. Local caches updated only after UDM write success (regression guard).
"""

import asyncio
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset_udm():
    """Reset UnifiedDeviceManager singleton for test isolation."""
    # Direct module import avoids triggering fastapi imports in core/unified/__init__.py
    from core.unified import device_manager as _mod
    _mod.UnifiedDeviceManager._instance = None


def _fresh_udm():
    _reset_udm()
    from core.unified.device_manager import UnifiedDeviceManager
    return UnifiedDeviceManager()


def _make_device(device_id: str, **kwargs):
    from core.unified.models import UnifiedDevice, UnifiedDeviceStatus
    dev = UnifiedDevice(device_id=device_id, **kwargs)
    dev.status = UnifiedDeviceStatus.ONLINE
    return dev


# ===========================================================================
# 1. Heartbeat timeout & auto-offline with grace period
# ===========================================================================

class TestHeartbeatTimeout(unittest.IsolatedAsyncioTestCase):
    """check_heartbeat_timeouts marks devices offline after timeout+grace."""

    async def test_device_goes_offline_after_timeout(self):
        udm = _fresh_udm()
        dev = _make_device("hb-dev-1")
        udm.register_device(dev)
        # Simulate heartbeat that is well past the threshold (set AFTER registration).
        udm._devices["hb-dev-1"].last_heartbeat = datetime.now(timezone.utc) - timedelta(seconds=120)

        offline = await udm.check_heartbeat_timeouts(timeout_secs=60.0, grace_secs=10.0)

        from core.unified.models import UnifiedDeviceStatus
        self.assertIn("hb-dev-1", offline)
        self.assertEqual(udm._devices["hb-dev-1"].status, UnifiedDeviceStatus.OFFLINE)

    async def test_device_stays_online_within_grace(self):
        udm = _fresh_udm()
        dev = _make_device("hb-dev-2")
        udm.register_device(dev)
        # Last heartbeat 50 s ago — within timeout+grace(60+10=70)
        udm._devices["hb-dev-2"].last_heartbeat = datetime.now(timezone.utc) - timedelta(seconds=50)

        offline = await udm.check_heartbeat_timeouts(timeout_secs=60.0, grace_secs=10.0)

        from core.unified.models import UnifiedDeviceStatus
        self.assertNotIn("hb-dev-2", offline)
        self.assertEqual(udm._devices["hb-dev-2"].status, UnifiedDeviceStatus.ONLINE)

    async def test_device_recovers_on_heartbeat_after_offline(self):
        udm = _fresh_udm()
        dev = _make_device("hb-dev-3")
        udm.register_device(dev)
        udm._devices["hb-dev-3"].last_heartbeat = datetime.now(timezone.utc) - timedelta(seconds=200)

        await udm.check_heartbeat_timeouts(timeout_secs=60.0, grace_secs=10.0)

        from core.unified.models import UnifiedDeviceStatus
        self.assertEqual(udm._devices["hb-dev-3"].status, UnifiedDeviceStatus.OFFLINE)

        # New heartbeat should recover the device.
        udm.heartbeat("hb-dev-3")
        self.assertEqual(udm._devices["hb-dev-3"].status, UnifiedDeviceStatus.ONLINE)

    async def test_already_offline_device_not_listed_again(self):
        from core.unified.models import UnifiedDeviceStatus
        udm = _fresh_udm()
        dev = _make_device("hb-dev-4")
        udm.register_device(dev)
        # Manually mark offline first.
        udm._devices["hb-dev-4"].status = UnifiedDeviceStatus.OFFLINE
        udm._devices["hb-dev-4"].last_heartbeat = datetime.now(timezone.utc) - timedelta(seconds=200)

        offline = await udm.check_heartbeat_timeouts(timeout_secs=60.0, grace_secs=10.0)

        self.assertNotIn("hb-dev-4", offline)


# ===========================================================================
# 2. Device registration de-duplication
# ===========================================================================

class TestDeviceRegistrationDedup(unittest.TestCase):
    """Repeated registration of the same device_id must not create duplicates."""

    def test_duplicate_registration_no_new_entry(self):
        udm = _fresh_udm()
        dev1 = _make_device("dup-dev-1", device_name="First Name")
        udm.register_device(dev1)
        count_before = udm.get_device_count()

        dev2 = _make_device("dup-dev-1", device_name="Updated Name")
        udm.register_device(dev2)

        self.assertEqual(udm.get_device_count(), count_before, "No new entry should be created")

    def test_duplicate_registration_updates_metadata(self):
        udm = _fresh_udm()
        dev1 = _make_device("dup-dev-2", metadata={"version": 1})
        udm.register_device(dev1)

        dev2 = _make_device("dup-dev-2", metadata={"version": 2})
        udm.register_device(dev2)

        self.assertEqual(udm.get_device("dup-dev-2").metadata["version"], 2)

    def test_duplicate_registration_preserves_registered_at(self):
        udm = _fresh_udm()
        dev1 = _make_device("dup-dev-3")
        udm.register_device(dev1)
        original_time = udm.get_device("dup-dev-3").registered_at

        dev2 = _make_device("dup-dev-3")
        udm.register_device(dev2)

        self.assertEqual(
            udm.get_device("dup-dev-3").registered_at,
            original_time,
            "registered_at must not change on re-registration",
        )

    def test_duplicate_registration_sets_online(self):
        from core.unified.models import UnifiedDeviceStatus
        udm = _fresh_udm()
        dev1 = _make_device("dup-dev-4")
        udm.register_device(dev1)
        # Manually mark offline to simulate a reconnect scenario.
        udm._devices["dup-dev-4"].status = UnifiedDeviceStatus.OFFLINE

        dev2 = _make_device("dup-dev-4")
        udm.register_device(dev2)

        self.assertEqual(
            udm._devices["dup-dev-4"].status,
            UnifiedDeviceStatus.ONLINE,
            "Re-registration should restore ONLINE status",
        )


# ===========================================================================
# 3. Idempotent task-result handling — MessageHandler
# ===========================================================================

class TestMessageHandlerTaskResultIdempotency(unittest.IsolatedAsyncioTestCase):
    """_handle_task_result must ignore duplicate task_id."""

    def _reset_durable_store(self):
        """Reset the durable result-ID singleton and clear its backing file."""
        try:
            from core.durable_result_idempotency import (
                get_durable_result_id_store,
                reset_durable_result_id_store,
            )
            get_durable_result_id_store().clear()
            reset_durable_result_id_store()
        except Exception:
            pass

    def setUp(self):
        self._reset_durable_store()

    def tearDown(self):
        self._reset_durable_store()

    def _make_handler(self):
        from galaxy_gateway.handlers.message_handler import MessageHandler
        dm = MagicMock()
        return MessageHandler(dm)

    def _make_task_result_message(self, task_id: str, payload: dict = None):
        from galaxy_gateway.protocol import AIPMessage, MessageType
        return AIPMessage(
            type=MessageType.TASK_RESULT,
            device_id="test-device",
            task_id=task_id,
            payload=payload or {},
        )

    async def test_first_result_is_processed(self):
        handler = self._make_handler()
        task_id = "task-idem-1"
        handler.create_task(task_id, "dev1", "goal_execution")
        msg = self._make_task_result_message(task_id)

        with patch(
            "galaxy_gateway.orchestrator.parallel_tracker.record_parallel_fields",
            new_callable=AsyncMock,
        ):
            result = await handler._handle_task_result("dev1", msg)

        self.assertIsNone(result)
        self.assertIn(task_id, handler._seen_task_result_ids)

    async def test_duplicate_result_is_ignored(self):
        handler = self._make_handler()
        task_id = "task-idem-2"
        handler.create_task(task_id, "dev1", "goal_execution")
        msg = self._make_task_result_message(task_id)

        with patch(
            "galaxy_gateway.orchestrator.parallel_tracker.record_parallel_fields",
            new_callable=AsyncMock,
        ) as mock_pt:
            await handler._handle_task_result("dev1", msg)
            mock_pt.reset_mock()
            # Second call — should be no-op.
            result = await handler._handle_task_result("dev1", msg)

        self.assertIsNone(result)
        # parallel_tracker must NOT be called again for the duplicate.
        mock_pt.assert_not_called()

    async def test_parallel_subtask_dedup(self):
        handler = self._make_handler()
        task_id = "task-par-1"
        handler.create_task(task_id, "dev1", "parallel_subtask")
        payload = {"group_id": "grp-1", "subtask_index": 0}
        msg = self._make_task_result_message(task_id, payload)

        with patch(
            "galaxy_gateway.orchestrator.parallel_tracker.record_parallel_fields",
            new_callable=AsyncMock,
        ) as mock_pt:
            await handler._handle_task_result("dev1", msg)
            mock_pt.reset_mock()

            # Duplicate with same group_id+subtask_index but different task_id.
            msg2 = self._make_task_result_message("task-par-1b", payload)
            result = await handler._handle_task_result("dev1", msg2)

        self.assertIsNone(result)
        mock_pt.assert_not_called()


# ===========================================================================
# 4. Idempotent task-result handling — DeviceRouter
# ===========================================================================

class TestDeviceRouterTaskResultIdempotency(unittest.IsolatedAsyncioTestCase):
    """handle_task_result must ignore duplicate task_id in DeviceRouter."""

    def _reset_durable_store(self):
        """Reset the durable result-ID singleton and clear its backing file."""
        try:
            from core.durable_result_idempotency import (
                get_durable_result_id_store,
                reset_durable_result_id_store,
            )
            get_durable_result_id_store().clear()
            reset_durable_result_id_store()
        except Exception:
            pass

    def setUp(self):
        self._reset_durable_store()

    def tearDown(self):
        self._reset_durable_store()

    async def test_first_result_stored(self):
        from galaxy_gateway.device_router import DeviceRouter
        router = DeviceRouter()
        with patch(
            "galaxy_gateway.orchestrator.parallel_tracker.record_parallel_fields",
            new_callable=AsyncMock,
        ):
            await router.handle_task_result("tid-1", {"success": True})

        self.assertIn("tid-1", router.task_results)

    async def test_duplicate_result_not_overwritten(self):
        from galaxy_gateway.device_router import DeviceRouter
        router = DeviceRouter()
        first_result = {"success": True, "data": "original"}
        second_result = {"success": False, "data": "should_be_ignored"}

        with patch(
            "galaxy_gateway.orchestrator.parallel_tracker.record_parallel_fields",
            new_callable=AsyncMock,
        ):
            await router.handle_task_result("tid-2", first_result)
            await router.handle_task_result("tid-2", second_result)

        # Original result must remain untouched.
        self.assertEqual(router.task_results["tid-2"]["data"], "original")

    async def test_duplicate_does_not_re_signal_event(self):
        from galaxy_gateway.device_router import DeviceRouter
        router = DeviceRouter()
        event = asyncio.Event()
        router._task_events["tid-3"] = event

        with patch(
            "galaxy_gateway.orchestrator.parallel_tracker.record_parallel_fields",
            new_callable=AsyncMock,
        ):
            await router.handle_task_result("tid-3", {"success": True})
            event.clear()
            # Duplicate should not set the event again.
            await router.handle_task_result("tid-3", {"success": True})

        self.assertFalse(event.is_set(), "Event must not be re-signalled for duplicate result")


# ===========================================================================
# 5. Local cache only updated after UDM write success (regression guard)
# ===========================================================================

class TestSSoTLocalCacheGuard(unittest.TestCase):
    """Local cache must NOT be updated when UDM write fails (regression guard)."""

    def _make_device_info(self, device_id="gc-test"):
        from galaxy_gateway.protocol import DeviceInfo, DeviceType
        return DeviceInfo(
            device_id=device_id,
            device_type=DeviceType.ANDROID_PHONE,
        )

    def test_register_no_local_update_on_udm_failure(self):
        from galaxy_gateway.handlers.device_manager import DeviceManager
        dm = DeviceManager()
        dev = self._make_device_info("gc-fail")

        with patch("galaxy_gateway.handlers.device_manager.udm_write_register", return_value=False):
            result = dm.register_device(dev)

        self.assertFalse(result)
        self.assertNotIn("gc-fail", dm.devices)

    def test_register_local_update_on_udm_success(self):
        from galaxy_gateway.handlers.device_manager import DeviceManager
        dm = DeviceManager()
        dev = self._make_device_info("gc-ok")

        with patch("galaxy_gateway.handlers.device_manager.udm_write_register", return_value=True):
            result = dm.register_device(dev)

        self.assertTrue(result)
        self.assertIn("gc-ok", dm.devices)

    def test_heartbeat_no_status_update_on_udm_failure(self):
        from galaxy_gateway.handlers.device_manager import DeviceManager
        from galaxy_gateway.protocol import DeviceInfo, DeviceType
        dm = DeviceManager()
        dm.devices["gc-hb"] = DeviceInfo(device_id="gc-hb", device_type=DeviceType.ANDROID_PHONE)
        dm.device_status["gc-hb"] = "offline"

        with patch("galaxy_gateway.handlers.device_manager.udm_write_heartbeat", return_value=False):
            dm.update_device_status("gc-hb", "online")

        self.assertEqual(dm.device_status["gc-hb"], "offline")


if __name__ == "__main__":
    unittest.main()
