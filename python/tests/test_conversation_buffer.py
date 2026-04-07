"""Tests for ConversationBuffer — short-term memory with power-law decay."""

import time
import json

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


class TestNoiseFilter:
    def test_user_noise_filtered(self):
        buf = ConversationBuffer()
        buf.add("user", "ок")
        buf.add("user", "так")
        buf.add("user", "ага")
        assert buf.get_weighted() == []

    def test_user_real_message_kept(self):
        buf = ConversationBuffer()
        buf.add("user", "Зроби auth endpoint")
        entries = buf.get_weighted()
        assert len(entries) == 1

    def test_assistant_short_filtered(self):
        buf = ConversationBuffer()
        buf.add("assistant", "Ок")
        buf.add("assistant", "Добре")
        assert buf.get_weighted() == []

    def test_assistant_real_response_kept(self):
        buf = ConversationBuffer()
        buf.add("assistant", "Починаю з JWT middleware для auth")
        entries = buf.get_weighted()
        assert len(entries) == 1


class TestFormatBlock:
    def test_empty_buffer_returns_empty(self):
        buf = ConversationBuffer()
        assert buf.format_block() == ""

    def test_format_contains_tags(self):
        buf = ConversationBuffer()
        buf.add("user", "Hello world test")
        block = buf.format_block()
        assert "<recent_conversation>" in block
        assert "</recent_conversation>" in block

    def test_format_contains_role_and_content(self):
        buf = ConversationBuffer()
        buf.add("user", "Build the auth system")
        block = buf.format_block()
        assert "user: Build the auth system" in block

    def test_format_shows_time_ago(self):
        buf = ConversationBuffer()
        buf._entries.append({
            "role": "user",
            "content": "Old message here",
            "ts": time.time() - 600,  # 10 min ago
        })
        block = buf.format_block()
        assert "10 хв тому" in block

    def test_format_shows_shchoyno_for_recent(self):
        buf = ConversationBuffer()
        buf.add("user", "Just now message")
        block = buf.format_block()
        assert "щойно" in block


class TestPersistence:
    def test_dump_and_load(self, tmp_path):
        buf = ConversationBuffer()
        buf.add("user", "Remember this message")
        buf.add("assistant", "I will remember that for you")
        path = tmp_path / "buffer.json"
        buf.dump(path)

        buf2 = ConversationBuffer()
        buf2.load(path)
        entries = buf2.get_weighted()
        assert len(entries) == 2
        assert entries[0]["content"] == "Remember this message"

    def test_load_filters_expired(self, tmp_path):
        path = tmp_path / "buffer.json"
        old_entry = {"role": "user", "content": "Ancient message", "ts": time.time() - 8 * 3600}
        new_entry = {"role": "user", "content": "Fresh message", "ts": time.time()}
        path.write_text(json.dumps([old_entry, new_entry]))

        buf = ConversationBuffer(weight_cutoff=0.05)
        buf.load(path)
        entries = buf.get_weighted()
        assert len(entries) == 1
        assert entries[0]["content"] == "Fresh message"

    def test_load_missing_file(self, tmp_path):
        buf = ConversationBuffer()
        buf.load(tmp_path / "nonexistent.json")
        assert buf.get_weighted() == []

    def test_load_corrupted_file(self, tmp_path):
        path = tmp_path / "buffer.json"
        path.write_text("not json at all {{{")
        buf = ConversationBuffer()
        buf.load(path)
        assert buf.get_weighted() == []
