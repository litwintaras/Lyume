# LyuMemory-LLM

Your LLM remembers everything. Locally. No cloud needed.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue)](https://www.python.org/)
[![Docker Ready](https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)
[![Status: Alpha](https://img.shields.io/badge/Status-Alpha-orange)](https://github.com/lyume/lyume-memory-proxy)

![demo](docs/assets/demo.gif)

## What is this?

Lyume Memory Proxy sits between your app and your local LLM. It automatically saves facts, learns from corrections, and recalls relevant memories—without any special prompting. Works with any OpenAI-compatible API (LM Studio, Ollama, llama.cpp).

No cloud. No telemetry. Your data stays yours.

## Why not alternatives?

| Feature | Lyume | Mem0 | Letta (MemGPT) | Zep |
|---------|-------|------|-----------------|-----|
| Works with local LLMs | ✅ | ⚠️ Cloud-first | ❌ Unreliable with local LLMs | ⚠️ Deprecated CE |
| No telemetry | ✅ | ❌ | ✅ | ✅ |
| Learns from feedback | ✅ | ❌ | ❌ | ❌ |
| No special prompting needed | ✅ | ❌ | ❌ | ❌ |
| Free & open source | ✅ | ⚠️ | ⚠️ | ❌ Cloud-only, paid |

## Prerequisites

- **Docker & Docker Compose** — for running the proxy and database
- **A local LLM server** — running OpenAI-compatible API (LM Studio, Ollama, or llama.cpp on port 1234)
- **~2GB RAM** — for the proxy and PostgreSQL + pgvector database

## Quick Start

### Option A: Interactive wizard (recommended)

```bash
git clone https://github.com/lyume/lyume-memory-proxy.git
cd lyume-memory-proxy
uv run python python/wizard.py
```

The wizard will guide you through:
1. **Agent identity** — name your AI companion
2. **LLM backend** — auto-detects models from Ollama, LM Studio, or any OpenAI-compatible server
3. **Embedding** — configures vector embeddings (HTTP endpoint or local CPU fallback)
4. **Database** — Docker PostgreSQL or existing server
5. **Memory import** — optionally imports memories from Claude Code, Cursor, Windsurf, and other AI agents

Then start the proxy:

```bash
docker compose up -d    # if using Docker PostgreSQL
uv run python -m uvicorn memory_proxy:app --host 127.0.0.1 --port 1235
```

### Option B: Manual setup

```bash
git clone https://github.com/lyume/lyume-memory-proxy.git
cd lyume-memory-proxy
cp python/config.yaml.example python/config.yaml
# Edit python/config.yaml with your LLM URL, model, and database settings
docker compose up -d
```

### Verify it works

Point your app to `http://localhost:1235` instead of your LLM's direct URL.

```bash
curl http://localhost:1235/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "any",
    "messages": [
      {"role": "user", "content": "My name is Alex, I live in Berlin"}
    ]
  }'
```

In a new session, ask:

```bash
curl http://localhost:1235/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "any",
    "messages": [
      {"role": "user", "content": "Where do I live?"}
    ]
  }'
```

The AI recalls "Berlin" — without you re-stating it.

## How it works

```
User App ↔ Lyume Proxy (port 1235) ↔ LM Studio (port 1234)
                 ↕
         PostgreSQL + pgvector
```

**Pipeline:**
1. Intercept incoming chat request
2. Embed query and search for relevant memories (semantic search)
3. Inject top memories into system prompt
4. Forward request to LLM
5. Classify response intents (facts, corrections, lessons)
6. Extract and save memories with emotional context
7. Return response to user

## Features

- Automatic memory — saves facts, preferences, corrections without explicit tagging
- Learns from feedback — negative responses become lessons, positive reinforce existing knowledge
- Semantic search — pgvector embeddings find contextually relevant memories, not just keyword matches
- Session warmup — starts each conversation with personalized context
- Mood detection — tracks emotional context in user interactions
- 100% local — no cloud, no telemetry, no tracking — your data stays on your machine
- One-command setup — `docker compose up` gets you running in seconds

## Configuration

Edit `python/config.yaml` (created by wizard or manually). Key sections:

- **`llm:`** — LLM API URL, model name, API key, timeouts (works with any OpenAI-compatible server)
- **`embedding:`** — provider (`http` or `local`), model, dimensions
- **`database:`** — provider (`docker` or `external`), PostgreSQL connection settings
- **`memory:`** — search limits, similarity thresholds, dedup settings
- **`lessons:`** — ELO rating system, similarity thresholds
- **`features:`** — toggle think-tag stripping, session summaries, marker fallback
- **`consolidation:`** — automatic memory merging schedule and thresholds

See [python/config.yaml](python/config.yaml) for all options and defaults.

### Memory Import

Import memories from other AI agents at any time:

```bash
uv run python python/wizard.py  # re-run wizard, choose "Memory Import"
```

Supported sources: Claude Code, Cursor, Windsurf, Cline, GitHub Copilot, OpenAI Codex, Gemini CLI, Aider.

## Roadmap

- [ ] Web dashboard for memory management
- [ ] Multi-user sessions with isolated memory stores
- [ ] Fine-tuning mode for specialized domains
- [ ] Export/import memory backups
- [ ] Rate limiting and quota management

## Contributing

Found a bug? Have an idea? Open an issue or PR on [GitHub](https://github.com/lyume/lyume-memory-proxy).

## License

MIT — see [LICENSE](LICENSE) for details.

## Acknowledgments

Built with [pgvector](https://github.com/pgvector/pgvector), [LM Studio](https://lmstudio.ai/), [llama.cpp](https://github.com/ggerganov/llama.cpp), and [nomic-embed-text](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5).
