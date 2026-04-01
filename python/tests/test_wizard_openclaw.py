"""Tests for wizard OpenClaw integration."""
from wizard.state import WizardState


def test_state_has_openclaw_fields():
    state = WizardState()
    assert state.openclaw_workspace == ""
    assert state.openclaw_agent_id == ""


def test_state_agent_name_default():
    state = WizardState()
    assert state.agent_name == "lyumemory"


def test_generate_config_uses_openclaw_workspace():
    state = WizardState(
        openclaw_workspace="/home/user/.openclaw/workspace-test",
        openclaw_agent_id="test-agent",
        agent_name="test-agent",
        llm_url="http://127.0.0.1:1234/v1",
        llm_model="qwen",
        embed_model="nomic",
    )
    config = state.generate_config()
    assert config["database"]["name"] == "ai_memory_test_agent"


def test_state_checkpoint_roundtrip(tmp_path):
    state = WizardState(
        openclaw_workspace="/home/user/.openclaw/workspace-lyume",
        openclaw_agent_id="lyume-v2",
        agent_name="lyume-v2",
    )
    cp = tmp_path / "checkpoint.yaml"
    state.save_checkpoint(cp)
    loaded = WizardState.load_checkpoint(cp)
    assert loaded.openclaw_workspace == "/home/user/.openclaw/workspace-lyume"
    assert loaded.openclaw_agent_id == "lyume-v2"
    assert loaded.agent_name == "lyume-v2"
