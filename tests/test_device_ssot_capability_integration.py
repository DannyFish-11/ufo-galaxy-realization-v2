"""
tests/test_device_ssot_capability_integration.py
=================================================
Integration tests verifying the device-SSOT → capability-visibility wiring
introduced by this PR.

Covers:
  1. Registering a device through UnifiedDeviceManager (UDM) automatically
     propagates capabilities into CapabilityBus.
  2. Unregistering a device through UDM removes its capabilities from
     CapabilityBus.
  3. DevicePoolManager.register_device() writes to UDM SSOT.
  4. DevicePoolManager.unregister_device() writes to UDM SSOT (offline).
  5. SSOT helpers (galaxy_gateway.ssot) are the documented canonical entry
     point for gateway-side callers.
  6. aip_protocol_v2 is hard-disabled (protocol authority is aip_v3).
  7. CapabilityManager docstring marks it as a legacy compatibility facade.
  8. CapabilityOrchestrator docstring marks it as a legacy compatibility facade.
"""

from __future__ import annotations

import importlib
import sys
import unittest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset_udm_singleton() -> None:
    """Reset the UnifiedDeviceManager singleton between tests."""
    try:
        from core.unified import device_manager as _dm_mod
        _dm_mod.UnifiedDeviceManager._instance = None
    except Exception:
        pass


def _reset_capability_bus_singleton() -> None:
    """Reset the CapabilityBus singleton between tests."""
    try:
        from core import capability_bus as _cb_mod
        _cb_mod.reset_capability_bus()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 1. UDM register → CapabilityBus propagation
# ---------------------------------------------------------------------------

class TestUDMCapabilityBusPropagation(unittest.TestCase):
    """Registering a device via UDM must propagate capabilities to CapabilityBus."""

    def setUp(self):
        _reset_udm_singleton()
        _reset_capability_bus_singleton()

    def tearDown(self):
        _reset_udm_singleton()
        _reset_capability_bus_singleton()

    def test_register_device_propagates_capabilities_to_bus(self):
        """Capabilities declared on a device appear in CapabilityBus after registration."""
        from core.unified.device_manager import UnifiedDeviceManager
        from core.unified.models import UnifiedDevice, UnifiedDeviceStatus, UnifiedDeviceType
        from core.capability_bus import get_capability_bus, CapabilityBusRole

        udm = UnifiedDeviceManager()
        device = UnifiedDevice(
            device_id="test_device_ssot_001",
            device_name="Test Phone",
            device_type=UnifiedDeviceType.ANDROID,
            status=UnifiedDeviceStatus.ONLINE,
            capabilities=["screen", "camera", "microphone"],
            metadata={},
        )
        udm.register_device(device)

        bus = get_capability_bus()
        device_entries = bus.list_by_role(CapabilityBusRole.DEVICE)
        device_ids_in_bus = {e.source_id for e in device_entries}

        self.assertIn(
            "test_device_ssot_001",
            device_ids_in_bus,
            "Device ID must appear in CapabilityBus after UDM registration",
        )

        all_names = {e.name for e in device_entries}
        self.assertIn(
            "device__test_device_ssot_001__screen",
            all_names,
            "'screen' capability must be visible in CapabilityBus",
        )
        self.assertIn(
            "device__test_device_ssot_001__camera",
            all_names,
            "'camera' capability must be visible in CapabilityBus",
        )
        self.assertIn(
            "device__test_device_ssot_001__microphone",
            all_names,
            "'microphone' capability must be visible in CapabilityBus",
        )

    def test_register_device_no_capabilities_does_not_raise(self):
        """Registering a device with no capabilities must not raise."""
        from core.unified.device_manager import UnifiedDeviceManager
        from core.unified.models import UnifiedDevice, UnifiedDeviceStatus, UnifiedDeviceType

        udm = UnifiedDeviceManager()
        device = UnifiedDevice(
            device_id="test_device_nocaps",
            device_name="No Caps Device",
            device_type=UnifiedDeviceType.IOT,
            status=UnifiedDeviceStatus.ONLINE,
            capabilities=[],
            metadata={},
        )
        # Must not raise
        udm.register_device(device)

    def test_unregister_device_removes_capabilities_from_bus(self):
        """Unregistering a device via UDM must remove its capabilities from CapabilityBus."""
        from core.unified.device_manager import UnifiedDeviceManager
        from core.unified.models import UnifiedDevice, UnifiedDeviceStatus, UnifiedDeviceType
        from core.capability_bus import get_capability_bus, CapabilityBusRole

        udm = UnifiedDeviceManager()
        device = UnifiedDevice(
            device_id="test_device_ssot_002",
            device_name="Device To Remove",
            device_type=UnifiedDeviceType.ANDROID,
            status=UnifiedDeviceStatus.ONLINE,
            capabilities=["touch", "gps"],
            metadata={},
        )
        udm.register_device(device)

        # Verify it was added
        bus = get_capability_bus()
        pre_entries = {e.name for e in bus.list_by_role(CapabilityBusRole.DEVICE)}
        self.assertIn("device__test_device_ssot_002__touch", pre_entries)
        self.assertIn("device__test_device_ssot_002__gps", pre_entries)

        # Unregister
        udm.unregister_device("test_device_ssot_002")

        # Verify capabilities were removed
        post_entries = {e.name for e in bus.list_by_role(CapabilityBusRole.DEVICE)}
        self.assertNotIn(
            "device__test_device_ssot_002__touch",
            post_entries,
            "'touch' capability must be removed from CapabilityBus after unregistration",
        )
        self.assertNotIn(
            "device__test_device_ssot_002__gps",
            post_entries,
            "'gps' capability must be removed from CapabilityBus after unregistration",
        )

    def test_reregister_device_updates_capabilities(self):
        """Re-registering a device (dedup) re-propagates capabilities."""
        from core.unified.device_manager import UnifiedDeviceManager
        from core.unified.models import UnifiedDevice, UnifiedDeviceStatus, UnifiedDeviceType
        from core.capability_bus import get_capability_bus, CapabilityBusRole

        udm = UnifiedDeviceManager()
        device_v1 = UnifiedDevice(
            device_id="test_device_ssot_003",
            device_name="Device V1",
            device_type=UnifiedDeviceType.ANDROID,
            status=UnifiedDeviceStatus.ONLINE,
            capabilities=["screen"],
            metadata={},
        )
        udm.register_device(device_v1)

        device_v2 = UnifiedDevice(
            device_id="test_device_ssot_003",
            device_name="Device V1",
            device_type=UnifiedDeviceType.ANDROID,
            status=UnifiedDeviceStatus.ONLINE,
            capabilities=["screen", "bluetooth"],
            metadata={},
        )
        udm.register_device(device_v2)

        bus = get_capability_bus()
        all_names = {e.name for e in bus.list_by_role(CapabilityBusRole.DEVICE)}
        self.assertIn(
            "device__test_device_ssot_003__bluetooth",
            all_names,
            "New capability 'bluetooth' must appear after re-registration",
        )


# ---------------------------------------------------------------------------
# 2. DevicePoolManager UDM write-through
# ---------------------------------------------------------------------------

class TestDevicePoolManagerUDMWriteThrough(unittest.TestCase):
    """DevicePoolManager must write to UDM before updating the local pool."""

    def setUp(self):
        _reset_udm_singleton()
        _reset_capability_bus_singleton()
        # Reset pool manager singleton
        try:
            from core import device_pool_manager as _dpm_mod
            _dpm_mod.DevicePoolManager._instance = None
        except Exception:
            pass

    def tearDown(self):
        _reset_udm_singleton()
        _reset_capability_bus_singleton()
        try:
            from core import device_pool_manager as _dpm_mod
            _dpm_mod.DevicePoolManager._instance = None
        except Exception:
            pass

    def test_pool_register_calls_udm_write(self):
        """DevicePoolManager.register_device must call UDM write-through."""
        from core.device_pool_manager import DevicePoolManager

        pool = DevicePoolManager()
        with patch("galaxy_gateway.ssot.udm_write_register") as mock_udm:
            mock_udm.return_value = True
            pool.register_device(
                "pool_dev_001",
                capabilities=["screen", "touch"],
                device_type="android",
            )
        mock_udm.assert_called_once()
        call_kwargs = mock_udm.call_args
        self.assertEqual(call_kwargs.kwargs.get("device_id") or call_kwargs.args[0], "pool_dev_001")

    def test_pool_unregister_calls_udm_write(self):
        """DevicePoolManager.unregister_device must call UDM write-through."""
        from core.device_pool_manager import DevicePoolManager

        pool = DevicePoolManager()
        # Register first (bypass UDM for setup)
        with patch("galaxy_gateway.ssot.udm_write_register", return_value=True):
            pool.register_device("pool_dev_002", capabilities=["screen"])

        with patch("galaxy_gateway.ssot.udm_write_unregister") as mock_udm:
            mock_udm.return_value = True
            pool.unregister_device("pool_dev_002")
        mock_udm.assert_called_once()

    def test_pool_register_succeeds_even_if_udm_unavailable(self):
        """Pool register must succeed in degraded mode if UDM write fails."""
        from core.device_pool_manager import DevicePoolManager

        pool = DevicePoolManager()
        with patch(
            "galaxy_gateway.ssot.udm_write_register",
            side_effect=RuntimeError("UDM unavailable"),
        ):
            # Must not raise
            dev = pool.register_device("pool_dev_003", capabilities=["screen"])

        self.assertEqual(dev.device_id, "pool_dev_003")

    def test_pool_register_device_visible_in_pool_list(self):
        """Devices registered via pool must be visible in list_devices."""
        from core.device_pool_manager import DevicePoolManager

        pool = DevicePoolManager()
        with patch("galaxy_gateway.ssot.udm_write_register", return_value=True):
            pool.register_device(
                "pool_dev_004",
                capabilities=["screen"],
                device_type="android",
            )

        devices = pool.list_devices()
        ids = [d["device_id"] for d in devices]
        self.assertIn("pool_dev_004", ids)


# ---------------------------------------------------------------------------
# 3. SSOT helpers — canonical gateway entry point
# ---------------------------------------------------------------------------

class TestSSOTHelpers(unittest.TestCase):
    """galaxy_gateway.ssot helpers are the canonical gateway write entry point."""

    def setUp(self):
        _reset_udm_singleton()

    def tearDown(self):
        _reset_udm_singleton()

    def test_udm_write_register_succeeds(self):
        """udm_write_register must return True on success."""
        from galaxy_gateway.ssot import udm_write_register

        result = udm_write_register(
            device_id="ssot_dev_001",
            device_name="SSOT Test Device",
            device_type_raw="android",
            capabilities=["screen"],
            metadata={},
        )
        self.assertTrue(result, "udm_write_register must return True on success")

    def test_udm_write_heartbeat_succeeds(self):
        """udm_write_heartbeat must return True after successful registration."""
        from galaxy_gateway.ssot import udm_write_register, udm_write_heartbeat

        udm_write_register(
            device_id="ssot_dev_002",
            device_name="Heartbeat Device",
            device_type_raw="android",
            capabilities=[],
            metadata={},
        )
        result = udm_write_heartbeat("ssot_dev_002")
        self.assertTrue(result, "udm_write_heartbeat must return True on success")

    def test_udm_write_unregister_succeeds(self):
        """udm_write_unregister must return True after successful registration."""
        from galaxy_gateway.ssot import udm_write_register, udm_write_unregister

        udm_write_register(
            device_id="ssot_dev_003",
            device_name="Unregister Device",
            device_type_raw="android",
            capabilities=[],
            metadata={},
        )
        result = udm_write_unregister("ssot_dev_003")
        self.assertTrue(result, "udm_write_unregister must return True on success")

    def test_ssot_docstring_describes_canonical_path(self):
        """ssot module docstring must mention the canonical path chain."""
        from galaxy_gateway import ssot
        doc = ssot.__doc__ or ""
        self.assertIn(
            "UnifiedDeviceManager",
            doc,
            "ssot module must document UnifiedDeviceManager as the canonical SSOT",
        )
        self.assertIn(
            "CapabilityBus",
            doc,
            "ssot module must document CapabilityBus as part of the canonical chain",
        )


# ---------------------------------------------------------------------------
# 4. Protocol authority — aip_protocol_v2 hard-disabled
# ---------------------------------------------------------------------------

class TestProtocolAuthority(unittest.TestCase):
    """The canonical protocol path is aip_v3; aip_protocol_v2 must be disabled."""

    def test_aip_protocol_v2_raises_import_error(self):
        """Importing galaxy_gateway.aip_protocol_v2 must raise ImportError."""
        # Remove from sys.modules to force a fresh import attempt
        sys.modules.pop("galaxy_gateway.aip_protocol_v2", None)
        with self.assertRaises(ImportError, msg="aip_protocol_v2 must raise ImportError"):
            import galaxy_gateway.aip_protocol_v2  # noqa: F401

    def test_aip_v3_is_importable(self):
        """galaxy_gateway.protocol.aip_v3 must be importable."""
        from galaxy_gateway.protocol import aip_v3  # noqa: F401

    def test_protocol_package_init_documents_canonical_path(self):
        """Protocol package __init__ must document the canonical path."""
        from galaxy_gateway import protocol
        doc = protocol.__doc__ or ""
        self.assertIn(
            "aip_v3",
            doc,
            "Protocol __init__ must mention aip_v3 as the canonical path",
        )
        self.assertIn(
            "HARD DISABLED",
            doc,
            "Protocol __init__ must state that aip_protocol_v2 is HARD DISABLED",
        )


# ---------------------------------------------------------------------------
# 5. Capability facade demotion — capability_manager / capability_orchestrator
# ---------------------------------------------------------------------------

class TestCapabilityFacadeDemotion(unittest.TestCase):
    """capability_manager and capability_orchestrator must be marked as legacy facades."""

    def test_capability_manager_docstring_has_deprecated_marker(self):
        """CapabilityManager module docstring must contain a deprecation notice."""
        from core import capability_manager
        doc = capability_manager.__doc__ or ""
        self.assertIn(
            "deprecated",
            doc.lower(),
            "capability_manager must have a deprecation notice in its module docstring",
        )
        self.assertIn(
            "CapabilityBus",
            doc,
            "capability_manager must point to CapabilityBus as the canonical authority",
        )

    def test_capability_orchestrator_docstring_has_deprecated_marker(self):
        """CapabilityOrchestrator module docstring must contain a deprecation notice."""
        from core import capability_orchestrator
        doc = capability_orchestrator.__doc__ or ""
        self.assertIn(
            "deprecated",
            doc.lower(),
            "capability_orchestrator must have a deprecation notice in its module docstring",
        )
        self.assertIn(
            "CapabilityBus",
            doc,
            "capability_orchestrator must point to CapabilityBus as the canonical authority",
        )


# ---------------------------------------------------------------------------
# 6. DevicePoolManager architecture role documentation
# ---------------------------------------------------------------------------

class TestDevicePoolManagerArchitectureRole(unittest.TestCase):
    """DevicePoolManager module must document its scheduling-layer role."""

    def test_module_docstring_describes_scheduling_layer_role(self):
        """DevicePoolManager module docstring must clarify it's a scheduling layer."""
        from core import device_pool_manager
        doc = device_pool_manager.__doc__ or ""
        self.assertIn(
            "UnifiedDeviceManager",
            doc,
            "device_pool_manager must mention UnifiedDeviceManager as the canonical SSOT",
        )
        self.assertIn(
            "scheduling",
            doc.lower(),
            "device_pool_manager must describe its scheduling-layer role",
        )


# ---------------------------------------------------------------------------
# 7. DeviceStatusAPI architecture role documentation
# ---------------------------------------------------------------------------

class TestDeviceStatusAPIArchitectureRole(unittest.TestCase):
    """device_status_api module must document its presentation-layer role."""

    def test_module_docstring_describes_presentation_layer_role(self):
        """device_status_api module docstring must clarify it's a presentation layer."""
        from core import device_status_api
        doc = device_status_api.__doc__ or ""
        self.assertIn(
            "UnifiedDeviceManager",
            doc,
            "device_status_api must mention UnifiedDeviceManager as the canonical SSOT",
        )
        self.assertIn(
            "presentation",
            doc.lower(),
            "device_status_api must describe its presentation-layer role",
        )


# ---------------------------------------------------------------------------
# 8. UDM register → CapabilityAssimilationLayer projection (PR-B2)
# ---------------------------------------------------------------------------

def _reset_capability_assimilation_singleton() -> None:
    """Reset the CapabilityAssimilationLayer singleton between tests."""
    try:
        from core.capability_assimilation import reset_capability_assimilation_layer
        reset_capability_assimilation_layer()
    except Exception:
        pass


class TestUDMCapabilityAssimilationIntegration(unittest.TestCase):
    """register_device() must project the device into CapabilityAssimilationLayer.

    Covers PR-B2 acceptance criteria:
    1. Device is queryable in CapabilityAssimilationLayer after register_device().
    2. register_device() with empty capabilities still calls assimilation without error.
    3. Capability update via upsert_device_state() re-assimilates idempotently.
    4. Re-registration (dedup) re-assimilates and merges capabilities.
    """

    def setUp(self):
        _reset_udm_singleton()
        _reset_capability_bus_singleton()
        _reset_capability_assimilation_singleton()

    def tearDown(self):
        _reset_udm_singleton()
        _reset_capability_bus_singleton()
        _reset_capability_assimilation_singleton()

    def test_register_device_projects_into_assimilation_layer(self):
        """After register_device(), the device must be queryable in CapabilityAssimilationLayer."""
        from core.unified.device_manager import UnifiedDeviceManager
        from core.unified.models import UnifiedDevice, UnifiedDeviceStatus, UnifiedDeviceType
        from core.capability_assimilation import get_capability_assimilation_layer

        udm = UnifiedDeviceManager()
        device = UnifiedDevice(
            device_id="assim_test_001",
            device_name="Assimilation Phone",
            device_type=UnifiedDeviceType.ANDROID,
            status=UnifiedDeviceStatus.ONLINE,
            capabilities=["screen", "camera", "touch"],
            metadata={},
        )
        udm.register_device(device)

        layer = get_capability_assimilation_layer()
        record = layer.get_record("assim_test_001")
        self.assertIsNotNone(
            record,
            "Device must have an AssimilationRecord after register_device()",
        )
        self.assertIn(
            "screen",
            record.capability_descriptor.capabilities,
            "'screen' must be present in the assimilation record capabilities",
        )
        self.assertIn(
            "camera",
            record.capability_descriptor.capabilities,
            "'camera' must be present in the assimilation record capabilities",
        )

    def test_register_device_no_capabilities_does_not_raise_assimilation(self):
        """Registering a device with empty capabilities must not raise during assimilation."""
        from core.unified.device_manager import UnifiedDeviceManager
        from core.unified.models import UnifiedDevice, UnifiedDeviceStatus, UnifiedDeviceType
        from core.capability_assimilation import get_capability_assimilation_layer

        udm = UnifiedDeviceManager()
        device = UnifiedDevice(
            device_id="assim_nocaps_001",
            device_name="No Caps Device",
            device_type=UnifiedDeviceType.IOT,
            status=UnifiedDeviceStatus.ONLINE,
            capabilities=[],
            metadata={},
        )
        # Must not raise
        udm.register_device(device)

        layer = get_capability_assimilation_layer()
        record = layer.get_record("assim_nocaps_001")
        self.assertIsNotNone(
            record,
            "Device with empty capabilities must still have an AssimilationRecord",
        )

    def test_upsert_capabilities_triggers_reassimilation(self):
        """upsert_device_state() with new capabilities must update the AssimilationLayer."""
        from core.unified.device_manager import UnifiedDeviceManager
        from core.unified.models import UnifiedDevice, UnifiedDeviceStatus, UnifiedDeviceType
        from core.capability_assimilation import get_capability_assimilation_layer

        udm = UnifiedDeviceManager()
        device = UnifiedDevice(
            device_id="assim_upsert_001",
            device_name="Upsert Device",
            device_type=UnifiedDeviceType.ANDROID,
            status=UnifiedDeviceStatus.ONLINE,
            capabilities=[],
            metadata={},
        )
        udm.register_device(device)

        # Initially no capabilities in the record
        layer = get_capability_assimilation_layer()
        record_before = layer.get_record("assim_upsert_001")
        self.assertIsNotNone(record_before)
        self.assertEqual(
            record_before.capability_descriptor.capabilities,
            [],
            "No capabilities expected before upsert",
        )

        # Now capabilities arrive via a separate capability_report
        udm.upsert_device_state(
            "assim_upsert_001",
            {"capabilities": ["bluetooth", "nfc", "gps"]},
            source="capability_report",
        )

        record_after = layer.get_record("assim_upsert_001")
        self.assertIsNotNone(record_after)
        self.assertIn(
            "bluetooth",
            record_after.capability_descriptor.capabilities,
            "'bluetooth' must appear in AssimilationLayer after upsert",
        )
        self.assertIn(
            "nfc",
            record_after.capability_descriptor.capabilities,
            "'nfc' must appear in AssimilationLayer after upsert",
        )
        self.assertIn(
            "gps",
            record_after.capability_descriptor.capabilities,
            "'gps' must appear in AssimilationLayer after upsert",
        )

    def test_upsert_no_capability_change_does_not_change_assimilation(self):
        """upsert_device_state() without capability change must not re-trigger assimilation."""
        from core.unified.device_manager import UnifiedDeviceManager
        from core.unified.models import UnifiedDevice, UnifiedDeviceStatus, UnifiedDeviceType
        from unittest.mock import patch as mock_patch

        udm = UnifiedDeviceManager()
        device = UnifiedDevice(
            device_id="assim_upsert_noop_001",
            device_name="Noop Device",
            device_type=UnifiedDeviceType.ANDROID,
            status=UnifiedDeviceStatus.ONLINE,
            capabilities=["screen"],
            metadata={},
        )
        udm.register_device(device)

        # Upsert only status — no capability change; assimilation must NOT be triggered again.
        with mock_patch.object(
            udm, "_assimilate_device_to_capability_layer"
        ) as mock_assimilate:
            udm.upsert_device_state(
                "assim_upsert_noop_001",
                {"status": "busy"},
                source="heartbeat",
            )
        mock_assimilate.assert_not_called()

    def test_reregister_device_updates_assimilation_idempotently(self):
        """Re-registering a device must update capabilities in AssimilationLayer."""
        from core.unified.device_manager import UnifiedDeviceManager
        from core.unified.models import UnifiedDevice, UnifiedDeviceStatus, UnifiedDeviceType
        from core.capability_assimilation import get_capability_assimilation_layer

        udm = UnifiedDeviceManager()
        device_v1 = UnifiedDevice(
            device_id="assim_rereg_001",
            device_name="Rereg Device",
            device_type=UnifiedDeviceType.ANDROID,
            status=UnifiedDeviceStatus.ONLINE,
            capabilities=["screen"],
            metadata={},
        )
        udm.register_device(device_v1)

        device_v2 = UnifiedDevice(
            device_id="assim_rereg_001",
            device_name="Rereg Device",
            device_type=UnifiedDeviceType.ANDROID,
            status=UnifiedDeviceStatus.ONLINE,
            capabilities=["screen", "microphone", "accelerometer"],
            metadata={},
        )
        udm.register_device(device_v2)

        layer = get_capability_assimilation_layer()
        record = layer.get_record("assim_rereg_001")
        self.assertIsNotNone(record)
        self.assertIn(
            "microphone",
            record.capability_descriptor.capabilities,
            "'microphone' must appear in AssimilationLayer after re-registration",
        )
        self.assertIn(
            "accelerometer",
            record.capability_descriptor.capabilities,
            "'accelerometer' must appear in AssimilationLayer after re-registration",
        )


if __name__ == "__main__":
    unittest.main()
