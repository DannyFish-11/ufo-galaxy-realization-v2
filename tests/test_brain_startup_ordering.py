"""tests/test_brain_startup_ordering.py
=========================================

GalaxyUnified.select_and_start_brain() previously called
core.model_selection.background_pull() (which fires a one-shot,
non-retrying `ollama pull` attempt in a daemon thread) BEFORE
self.start_local_brain() - the call that actually starts the Ollama
service and retries for up to ~40s until it responds.

On a real machine where Ollama's own service is slow to bind its port
(Windows cold start: GPU/driver probing, antivirus scanning the exe),
background_pull()'s single unguarded attempt would consistently lose
this race and give up permanently for that run - reproducing on every
launch, not intermittently, matching a real report that "whether
starting fresh or manually retrying, the model pull always fails".

This test proves start_local_brain() now runs before background_pull()
is invoked.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest


class TestBrainStartupOrdering:
    def test_start_local_brain_runs_before_background_pull(self):
        call_order = []

        async def fake_start_local_brain(self):
            call_order.append("start_local_brain")

        def fake_background_pull(tag):
            call_order.append("background_pull")

        with patch("unified_launcher.GalaxyUnified.start_local_brain", new=fake_start_local_brain):
            import unified_launcher as ul

            with (
                patch("core.model_selection.resolve_main_brain", side_effect=lambda interactive: "gemma4:e2b"),
                patch("core.model_selection.background_pull", side_effect=fake_background_pull),
                patch("core.model_selection.get_compute_summary", side_effect=lambda: (0, False, "n/a")),
                patch("core.model_selection.recommend", side_effect=lambda *a, **k: "gemma4:e2b"),
                patch("core.model_selection.list_models", side_effect=lambda: []),
            ):
                launcher = ul.GalaxyUnified()
                asyncio.run(launcher.select_and_start_brain())

        assert call_order == [
            "start_local_brain",
            "background_pull",
        ], f"expected start_local_brain before background_pull, got {call_order}"

    def test_no_model_chosen_still_starts_local_brain(self):
        """If model selection yields nothing, start_local_brain() must still run
        (it shouldn't be gated on a successful chosen tag), and background_pull
        must not be called at all."""
        call_order = []

        async def fake_start_local_brain(self):
            call_order.append("start_local_brain")

        def fake_background_pull(tag):
            call_order.append("background_pull")

        with patch("unified_launcher.GalaxyUnified.start_local_brain", new=fake_start_local_brain):
            import unified_launcher as ul

            with (
                patch("core.model_selection.resolve_main_brain", side_effect=lambda interactive: ""),
                patch("core.model_selection.background_pull", side_effect=fake_background_pull),
            ):
                launcher = ul.GalaxyUnified()
                asyncio.run(launcher.select_and_start_brain())

        assert call_order == ["start_local_brain"], call_order
