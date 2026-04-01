"""Tests for wizard OpenClaw integration."""
import json
from wizard.state import WizardState
from wizard.steps.openclaw_agent import parse_agents_json


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


def test_parse_agents_json_valid():
    raw = json.dumps([
        {
            "id": "lyume-v2",
            "name": "lyume-v2",
            "workspace": "/home/tarik/.openclaw/workspace-lyume",
            "agentDir": "/home/tarik/.openclaw/agents/lyume-v2/agent",
            "model": "home/qwen3.5-35b-a3b",
            "bindings": 0,
            "isDefault": True,
            "routes": ["default (no explicit rules)"]
        },
        {
            "id": "helper",
            "name": "helper",
            "workspace": "/home/tarik/.openclaw/workspace-helper",
            "agentDir": "/home/tarik/.openclaw/agents/helper/agent",
            "model": "home/llama-3",
            "bindings": 0,
            "isDefault": False,
            "routes": []
        }
    ])
    agents = parse_agents_json(raw)
    assert len(agents) == 2
    assert agents[0]["id"] == "lyume-v2"
    assert agents[0]["workspace"] == "/home/tarik/.openclaw/workspace-lyume"
    assert agents[1]["id"] == "helper"


def test_parse_agents_json_empty():
    agents = parse_agents_json("[]")
    assert agents == []


def test_parse_agents_json_invalid():
    agents = parse_agents_json("not json")
    assert agents == []


def test_full_state_flow():
    """Simulate the full wizard state changes through all steps."""
    state = WizardState()

    # Step 0: OpenClaw agent selected
    state.openclaw_agent_id = "my-agent"
    state.openclaw_workspace = "/tmp/test-workspace"
    state.agent_name = "my-agent"

    # Step 1: Backend
    state.backend_name = "LM Studio"
    state.llm_url = "http://127.0.0.1:1234/v1"
    state.llm_model = "qwen3-coder"

    # Step 2: Embedding
    state.embed_provider = "http"
    state.embed_url = "http://127.0.0.1:1234/v1"
    state.embed_model = "nomic-embed-text"
    state.embed_dimensions = 768

    # Step 4: Database
    state.db_provider = "docker"
    state.db_host = "127.0.0.1"
    state.db_port = 5432

    # Generate config
    config = state.generate_config()

    assert config["llm"]["url"] == "http://127.0.0.1:1234/v1"
    assert config["llm"]["model"] == "qwen3-coder"
    assert config["embedding"]["model"] == "nomic-embed-text"
    assert config["database"]["name"] == "ai_memory_my_agent"
    assert config["database"]["host"] == "127.0.0.1"


def test_deploy_path_is_workspace_based():
    """Verify the target deploy path is <workspace>/lyumemory/."""
    from pathlib import Path
    state = WizardState(
        openclaw_workspace="/home/user/.openclaw/workspace-test",
        openclaw_agent_id="test",
    )
    target = Path(state.openclaw_workspace) / "lyumemory"
    assert str(target) == "/home/user/.openclaw/workspace-test/lyumemory"
