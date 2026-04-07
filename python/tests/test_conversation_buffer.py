"""Tests for ConversationBuffer — short-term memory with power-law decay."""

import time
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from conversation_buffer import ConversationBuffer


class TestDecayMath:
    """Power-law weight: w = (1 + t_minutes) ** (-decay_power)"""

    def test_weight_at_zero(self):
        buf = ConversationBuffer()
        now = time.time()
        assert buf._weight(now, now) == pytest.approx(1.0)

    def test_weight_at_1_min(self):
        buf = ConversationBuffer()
        now = time.time()
        assert buf._weight(now - 60, now) == pytest.approx(0.7071, rel=0.01)

    def test_weight_at_5_min(self):
        buf = ConversationBuffer()
        now = time.time()
        assert buf._weight(now - 300, now) == pytest.approx(0.4082, rel=0.01)

    def test_weight_at_1_hour(self):
        buf = ConversationBuffer()
        now = time.time()
        assert buf._weight(now - 3600, now) == pytest.approx(0.1280, rel=0.01)

    def test_weight_at_6_hours_below_cutoff(self):
        buf = ConversationBuffer(weight_cutoff=0.05)
        now = time.time()
        w = buf._weight(now - 7 * 3600, now)
        assert w < 0.05

    def test_custom_decay_power(self):
        buf = ConversationBuffer(decay_power=1.0)
        now = time.time()
        # (1 + 5)^(-1.0) = 0.1667
        assert buf._weight(now - 300, now) == pytest.approx(0.1667, rel=0.01)


class TestAddAndGet:
    def test_add_user_message(self):
        buf = ConversationBuffer()
        buf.add("user", "Hello world")
        entries = buf.get_weighted()
        assert len(entries) == 1
        assert entries[0]["role"] == "user"
        assert entries[0]["content"] == "Hello world"

    def test_add_assistant_message(self):
        buf = ConversationBuffer()
        buf.add("assistant", "I can help with that task")
        entries = buf.get_weighted()
        assert len(entries) == 1
        assert entries[0]["role"] == "assistant"

    def test_fifo_eviction(self):
        buf = ConversationBuffer(max_entries=3)
        buf.add("user", "Message one")
        buf.add("user", "Message two")
        buf.add("user", "Message three")
        buf.add("user", "Message four")
        entries = buf.get_weighted()
        assert len(entries) == 3
        assert entries[0]["content"] == "Message two"

    def test_weight_cutoff_filters_old(self):
        buf = ConversationBuffer(weight_cutoff=0.05)
        old_ts = time.time() - 7 * 3600  # 7 hours ago
        buf._entries.append({"role": "user", "content": "Old msg", "ts": old_ts})
        buf.add("user", "New msg")
        entries = buf.get_weighted()
        assert len(entries) == 1
        assert entries[0]["content"] == "New msg"

    def test_max_inject_limit(self):
        buf = ConversationBuffer(max_inject=3)
        for i in range(10):
            buf.add("user", f"Message {i}")
        entries = buf.get_weighted()
        assert len(entries) == 3

    def test_content_truncation(self):
        buf = ConversationBuffer(max_chars=20)
        buf.add("user", "A" * 100)
        entries = buf.get_weighted()
        assert len(entries[0]["content"]) == 23  # 20 + "..."

    def test_chronological_order(self):
        buf = ConversationBuffer()
        buf.add("user", "First")
        buf.add("assistant", "Second response here")
        buf.add("user", "Third")
        entries = buf.get_weighted()
        assert [e["content"] for e in entries] == ["First", "Second response here", "Third"]

    def test_clear(self):
        buf = ConversationBuffer()
        buf.add("user", "Hello")
        buf.clear()
        assert buf.get_weighted() == []
