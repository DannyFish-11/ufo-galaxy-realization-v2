#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PR-25: gateway canonical ingress routing discipline regression."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.websockets import WebSocket

pytest.importorskip("websockets", reason="websockets required for gateway websocket tests")

from galaxy_gateway.routes import websocket as ws_routes


def test_ingress_surface_registry_has_single_canonical_device_ingress():
    canonical_entries = [
        entry
        for entry in ws_routes.DEVICE_WS_INGRESS_SURFACE_REGISTRY
        if entry.get("classification") == "canonical"
    ]
    assert len(canonical_entries) == 1
    assert canonical_entries[0]["path"] == "/ws/device/{device_id}"


def _make_client_with_captured_ingress(monkeypatch):
    app = FastAPI()
    captured = []

    async def _fake_handle_android_ws(
        websocket: WebSocket,
        device_id: str,
        *,
        ingress_path: str = "/ws/device/{device_id}",
        ingress_classification: str = "canonical",
    ):
        captured.append(
            {
                "device_id": device_id,
                "ingress_path": ingress_path,
                "ingress_classification": ingress_classification,
            }
        )
        await websocket.accept()
        await websocket.close(code=1000)

    monkeypatch.setattr(ws_routes, "_handle_android_ws", _fake_handle_android_ws)
    ws_routes.register_websocket_routes(app)
    return app, captured


def test_canonical_ws_device_route_is_marked_canonical(monkeypatch):
    app, captured = _make_client_with_captured_ingress(monkeypatch)

    with TestClient(app) as client:
        with client.websocket_connect("/ws/device/device-canonical"):
            pass

    assert captured
    assert captured[-1]["ingress_path"] == "/ws/device/{device_id}"
    assert captured[-1]["ingress_classification"] == "canonical"


@pytest.mark.parametrize(
    "path,expected_ingress_path",
    [
        ("/ws/android/device-compat", "/ws/android/{device_id}"),
        ("/ws/android?device_id=device-compat-query", "/ws/android"),
    ],
)
def test_android_compat_routes_remain_non_canonical(monkeypatch, path, expected_ingress_path):
    app, captured = _make_client_with_captured_ingress(monkeypatch)

    with TestClient(app) as client:
        with client.websocket_connect(path):
            pass

    assert captured
    assert captured[-1]["ingress_path"] == expected_ingress_path
    assert captured[-1]["ingress_classification"] == "compat"
