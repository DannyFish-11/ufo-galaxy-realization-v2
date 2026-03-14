"""
Tests for OpenClawd Heartbeat ACK suppression logic.

Focused unit tests for ``is_ack_response`` to ensure that ACK suppression
correctly prevents heartbeat no-op responses from reaching user-visible output.
"""

import pytest

from core.openclawd_heartbeat import is_ack_response


class TestAckSuppressionEdgeCases:
    """Extended edge-case coverage for ACK suppression."""

    DEFAULT_TOKEN = "HEARTBEAT_OK"
    DEFAULT_MAX = 160

    # ---- short responses that SHOULD be suppressed ----

    def test_token_only(self):
        assert is_ack_response("HEARTBEAT_OK", self.DEFAULT_TOKEN, self.DEFAULT_MAX)

    def test_token_with_trailing_whitespace(self):
        assert is_ack_response("  HEARTBEAT_OK  ", self.DEFAULT_TOKEN, self.DEFAULT_MAX)

    def test_token_at_start_with_trailing_text(self):
        assert is_ack_response("HEARTBEAT_OK — no tasks pending", self.DEFAULT_TOKEN, self.DEFAULT_MAX)

    def test_token_at_end_with_leading_text(self):
        assert is_ack_response("No tasks. HEARTBEAT_OK", self.DEFAULT_TOKEN, self.DEFAULT_MAX)

    def test_lowercase_token(self):
        assert is_ack_response("heartbeat_ok", self.DEFAULT_TOKEN, self.DEFAULT_MAX)

    def test_mixed_case_token(self):
        assert is_ack_response("HeArTbEaT_oK", self.DEFAULT_TOKEN, self.DEFAULT_MAX)

    def test_short_multi_line_ack(self):
        text = "All clear.\nHEARTBEAT_OK"
        assert is_ack_response(text, self.DEFAULT_TOKEN, self.DEFAULT_MAX)

    # ---- responses that SHOULD NOT be suppressed ----

    def test_long_response_with_token_at_start(self):
        text = "HEARTBEAT_OK " + "x" * 200
        assert not is_ack_response(text, self.DEFAULT_TOKEN, self.DEFAULT_MAX)

    def test_long_response_with_token_at_end(self):
        text = "x" * 200 + " HEARTBEAT_OK"
        assert not is_ack_response(text, self.DEFAULT_TOKEN, self.DEFAULT_MAX)

    def test_response_without_token(self):
        text = "I performed the scheduled maintenance tasks."
        assert not is_ack_response(text, self.DEFAULT_TOKEN, self.DEFAULT_MAX)

    def test_token_in_middle_not_suppressed(self):
        # Token is in the middle (text both before AND after) —
        # not at start and not at end, so it must not be suppressed.
        text = "Some prefix HEARTBEAT_OK some suffix"
        assert not is_ack_response(text, self.DEFAULT_TOKEN, self.DEFAULT_MAX)

    def test_empty_string(self):
        # Empty string has no token — should not be suppressed
        assert not is_ack_response("", self.DEFAULT_TOKEN, self.DEFAULT_MAX)

    # ---- custom token and max_chars ----

    def test_custom_token(self):
        assert is_ack_response("OK_DONE", "OK_DONE", 20)

    def test_custom_max_chars_strict(self):
        # Exactly 10 chars with token
        assert is_ack_response("DONE", "DONE", 10)
        assert not is_ack_response("DONE " + "x" * 7, "DONE", 10)

    def test_zero_max_chars_nothing_suppressed(self):
        # max_output_chars=0 means nothing is ever suppressed (len > 0)
        assert not is_ack_response("HEARTBEAT_OK", self.DEFAULT_TOKEN, 0)
