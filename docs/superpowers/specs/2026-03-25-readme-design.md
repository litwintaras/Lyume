# README Design Spec — Lyume Memory Proxy

**Date:** 2026-03-25
**Status:** Alpha — API may change
**Goal:** Create a README.md that hooks visitors in 5 seconds and gets them running in 5 minutes.

## Tagline

"Your LLM remembers everything. Locally. No cloud needed."

## Target Audience

Developers looking for a private memory layer for local LLMs + people seeking alternatives to Mem0/Letta/Zep.

"If you're frustrated with Mem0's cloud lock-in or Letta's instability with local models, you're in the right place."

## Structure

### 1. Hero Section
- Project name + tagline
- Status badge: Alpha
- Demo GIF: chat session where AI remembers a fact from previous message
- Badges: License, Python version, Docker

### 2. What is this? (2-3 sentences)
Lyume Memory Proxy sits between your app and your local LLM. It automatically saves facts, learns from corrections, and recalls relevant memories — without any special prompting. Works with any OpenAI-compatible API (LM Studio, Ollama, llama.cpp).

### 3. Why not alternatives? (comparison table)

| Feature | Lyume | Mem0 | Letta (MemGPT) | Zep |
|---------|-------|------|-----------------|-----|
| Works with local LLMs | ✅ | ⚠️ Cloud-first | ❌ Unreliable with local LLMs | ⚠️ Deprecated CE |
| No telemetry | ✅ | ❌ | ✅ | ✅ |
| Learns from feedback | ✅ | ❌ | ❌ | ❌ |
| No special prompting needed | ✅ | ❌ | ❌ | ❌ |
| Free & open source | ✅ | ⚠️ | ⚠️ | ❌ Cloud-only, paid |

### 4. Prerequisites
- Docker & Docker Compose
- A local LLM server running OpenAI-compatible API (LM Studio, Ollama, or llama.cpp)
- ~2GB RAM for the proxy + database

### 5. Quick Start (3 steps)
```
git clone ...
cp .env.example .env
docker compose up
```
Then point your app to localhost:1235 instead of localhost:1234.

**Verify it works:**
```bash
curl http://localhost:1235/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "any", "messages": [{"role": "user", "content": "My name is Alex, I live in Berlin"}]}'
```

### 6. How it works (diagram only, no prose duplication)
```
User ↔ Lyume Proxy (port 1235) ↔ LM Studio (port 1234)
              ↕
        PostgreSQL + pgvector
```
Steps: intercept → extract query → embed → search memories → inject into system prompt → forward to LLM → classify response intents → save facts/lessons

### 7. Features
- Automatic memory — saves facts, preferences, corrections
- Learns from feedback — negative = lesson, positive = reinforcement
- Semantic search — pgvector embeddings, finds relevant memories
- Session warmup — starts each conversation with context
- Mood detection — emotional context in memories
- 100% local — no cloud, no telemetry, your data stays yours
- One command setup — docker compose up

### 8. Configuration
Link to config.yaml with brief explanation of sections.

### 9. Footer
- Contributing guidelines (brief)
- License: MIT
- Acknowledgments: pgvector, LM Studio, llama.cpp, nomic-embed-text

## Demo GIF Concept

Two-message chat exchange (in English for international audience):
1. User: "My name is Alex, I live in Berlin"
2. AI: "Nice to meet you, Alex! I'll remember that."
3. (new session indicator)
4. User: "Where do I live?"
5. AI: "You live in Berlin, Alex!"

Shows the core value prop in ~10 seconds.

## Design Decisions

- **Language:** English (international audience)
- **Tone:** Direct, confident, slightly rebellious ("your data, your rules")
- **Length:** Under 300 lines total
- **No:** walls of text, excessive badges, lengthy API docs (link to wiki/docs instead)
- **No emoji in feature list** — clean, professional look matching the rebellious tone
