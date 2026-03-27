# Intent Classifier — Model-Agnostic Memory Management

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `>>SAVE`/`>>LESSON`/`>>FORGET`/`>>RECALL` marker instructions to the LLM with a proxy-level intent classifier, so memory management works with any model without special prompting.

**Architecture:** The proxy already has soft-detection patterns (`SOFT_SAVE_PATTERN`, `SOFT_LESSON_PATTERN`, `SAVE_INTENT_TRIGGERS`, `NEGATIVE_FEEDBACK`, `POSITIVE_FEEDBACK`, `FACT_PATTERNS`, `FAREWELL_PATTERN`). We promote these from "fallback" to "primary path", remove marker instructions from all prompts, and keep marker parsing as a silent fallback. A new `intent_classifier.py` module consolidates all detection logic. Config gets a `features` section for toggles.

**Tech Stack:** Python 3.14, FastAPI, regex (no new dependencies — classifier is rule-based, not ML)

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `python/intent_classifier.py` | **Create** | All intent detection: save, lesson, forget, recall from both user and assistant text |
| `python/memory_proxy.py` | **Modify** | Remove marker instructions from prompts, use `intent_classifier` as primary path, markers as fallback |
| `python/config.yaml` | **Modify** | Add `features` section (strip_think_tags, marker_fallback) |
| `python/config.py` | **Modify** | Add `__getattr__` fallback for missing sections |
| `python/tests/test_intent_classifier.py` | **Create** | Unit tests for classifier |
| `AGENTS.md` | **Modify** | Remove marker instructions, update memory section |

---

### Task 1: Add `features` section to config + safe defaults

**Files:**
- Modify: `python/config.yaml`
- Modify: `python/config.py`

- [ ] **Step 1: Add features section to config.yaml**

Add at end of `config.yaml`:
```yaml
features:
  strip_think_tags: true
  marker_fallback: true
```

- [ ] **Step 2: Add `__getattr__` fallback to `_Section` in config.py**

This prevents `AttributeError` if a section is missing from yaml (e.g. old config without `features`):

```python
class _Section:
    def __init__(self, data: dict):
        for k, v in data.items():
            setattr(self, k, _Section(v) if isinstance(v, dict) else v)

    def __getattr__(self, name):
        return _Section({})

    def __bool__(self):
        return bool(self.__dict__)

    def __repr__(self):
        return repr(self.__dict__)
```

- [ ] **Step 3: Verify config loads**

Run: `cd /home/tarik/.openclaw/workspace-lyume/python && .venv/bin/python -c "from config import cfg; print(cfg.features.strip_think_tags, cfg.features.marker_fallback); print(cfg.nonexistent.key)"`
Expected: `True True` then `{}` (empty _Section, not an error)

- [ ] **Step 4: Commit**

```bash
git add python/config.yaml python/config.py
git commit -m "config: add features section + safe defaults for missing config keys"
```

---

### Task 2: Create `intent_classifier.py` with tests

**Files:**
- Create: `python/intent_classifier.py`
- Create: `python/tests/test_intent_classifier.py`

- [ ] **Step 1: Write tests first**

Create `python/tests/__init__.py` (empty) and `python/tests/test_intent_classifier.py`:

```python
import pytest
from intent_classifier import classify_user_intent, classify_assistant_intent


class TestUserIntent:
    def test_save_explicit_ukrainian(self):
        result = classify_user_intent("запам'ятай що мене звати Тарас")
        assert result["save"] is True
        assert "Тарас" in result["save_content"]

    def test_save_explicit_english(self):
        result = classify_user_intent("remember that I live in Berlin")
        assert result["save"] is True

    def test_forget_intent(self):
        result = classify_user_intent("забудь що я живу в Мюнхені")
        assert result["forget"] is True
        assert "Мюнхені" in result["forget_content"]

    def test_recall_intent(self):
        result = classify_user_intent("а ти пам'ятаєш де я працюю?")
        assert result["recall"] is True

    def test_negative_feedback(self):
        result = classify_user_intent("ні, не так, я мав на увазі інше")
        assert result["feedback"] == "negative"

    def test_positive_feedback(self):
        result = classify_user_intent("так, саме так, молодець")
        assert result["feedback"] == "positive"

    def test_farewell(self):
        result = classify_user_intent("добраніч, йду спати")
        assert result["farewell"] is True

    def test_no_intent(self):
        result = classify_user_intent("яка погода завтра?")
        assert result["save"] is False
        assert result["forget"] is False
        assert result["recall"] is False
        assert result["feedback"] is None
        assert result["farewell"] is False

    def test_fact_extraction_name(self):
        result = classify_user_intent("мене звати Тарас")
        assert result["save"] is True
        assert "Тарас" in result["save_content"]

    def test_fact_extraction_age(self):
        result = classify_user_intent("мені 28 років")
        assert result["save"] is True

    def test_fact_extraction_work(self):
        result = classify_user_intent("я працюю в Google")
        assert result["save"] is True


class TestAssistantIntent:
    def test_soft_save(self):
        result = classify_assistant_intent("Це важливо для мене, я це запам'ятовую.")
        assert result["save"] is True

    def test_soft_lesson(self):
        result = classify_assistant_intent("Я зрозуміла що наступного разу краще питати спочатку.")
        assert result["lesson"] is True

    def test_no_intent(self):
        result = classify_assistant_intent("Ось відповідь на твоє питання про Python.")
        assert result["save"] is False
        assert result["lesson"] is False

    def test_emotional_save(self):
        result = classify_assistant_intent("Дякую що ділишся, це зворушливо.")
        assert result["save"] is True

    def test_lesson_from_correction(self):
        result = classify_assistant_intent("Ой, я помилилась. Виправляюсь — правильно буде інакше.")
        assert result["lesson"] is True


class TestEdgeCases:
    def test_empty_string(self):
        result = classify_user_intent("")
        assert result["save"] is False
        assert result["feedback"] is None

    def test_forget_does_not_trigger_negative_feedback(self):
        result = classify_user_intent("забудь що я живу в Мюнхені")
        assert result["forget"] is True
        assert result["feedback"] is None  # not "negative"

    def test_mixed_language(self):
        result = classify_user_intent("запам'ятай that I live in Berlin")
        assert result["save"] is True

    def test_both_apostrophe_variants(self):
        r1 = classify_user_intent("запам'ятай це")
        r2 = classify_user_intent("запамʼятай це")
        assert r1["save"] is True
        assert r2["save"] is True
```

- [ ] **Step 2: Run tests — verify they fail**

Run: `cd /home/tarik/.openclaw/workspace-lyume/python && .venv/bin/python -m pytest tests/test_intent_classifier.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'intent_classifier'`

- [ ] **Step 3: Implement `intent_classifier.py`**

Create `python/intent_classifier.py`. Move and consolidate these patterns from `memory_proxy.py`:
- `SAVE_INTENT_TRIGGERS` (line 69-71)
- `FACT_PATTERNS` (lines 74-82)
- `NEGATIVE_FEEDBACK` (lines 85-91)
- `POSITIVE_FEEDBACK` (lines 93-98)
- `FAREWELL_PATTERN` (lines 191-196)
- `SOFT_SAVE_PATTERN` (lines 200-219)
- `SOFT_LESSON_PATTERN` (lines 224-241)

Plus new patterns:
- `FORGET_INTENT` — "забудь", "видали", "прибери з пам'яті"
- `RECALL_INTENT` — "пам'ятаєш", "нагадай", "що ти знаєш про"

Two public functions:

```python
import re


# --- User intent patterns ---

SAVE_INTENT = re.compile(
    r"запам['\ʼ]ятай|запиши|збережи|не забудь|нагадай мені|remember",
    re.IGNORECASE,
)

FACT_PATTERNS = [
    re.compile(r"(мо[гєї]\w*\s+\w+\s+звати\s+.+)", re.IGNORECASE),
    re.compile(r"(мене звати\s+.+)", re.IGNORECASE),
    re.compile(r"(мій\s+.+)", re.IGNORECASE),
    re.compile(r"(я живу\s+.+)", re.IGNORECASE),
    re.compile(r"(я працюю\s+.+)", re.IGNORECASE),
    re.compile(r"(мені\s+\d+\s+років)", re.IGNORECASE),
    re.compile(r"(?:запам['\ʼ]ятай|запиши|збережи|не забудь|нагадай мені|remember)[,:]?\s*(.+)", re.IGNORECASE),
]

FORGET_INTENT = re.compile(
    r"забудь|видали|прибери з пам[ʼ']ят|зітри|delete|forget|remove from memory",
    re.IGNORECASE,
)

RECALL_INTENT = re.compile(
    r"памʼятаєш|пам'ятаєш|нагадай|що ти знаєш про|ти знаєш що|remember when|do you remember|what do you know about",
    re.IGNORECASE,
)

NEGATIVE_FEEDBACK = re.compile(
    r"^(ні\b|не так|не те|не ті|неправильно|не треба|не потрібно|стоп|хватить|"
    r"не вірно|невірно|не зрозумі|ти не поня|не розумієш|"
    r"я не про це|я не це|не це|відміна|скасуй|забудь|"
    r"no\b|wrong|stop|not what|nope)",
    re.IGNORECASE,
)

POSITIVE_FEEDBACK = re.compile(
    r"^(так[!. ]|да\b|правильно|молодець|саме так|точно|вірно|супер|"
    r"клас|круто|ідеально|бінго|exactly|yes\b|correct|perfect|nice|good|"
    r"от так|ось так|це воно|то що треба|гарна робота|красава|умнічка|розумнічка)",
    re.IGNORECASE,
)

FAREWELL_PATTERN = re.compile(
    r"^(поки|пока|па\b|бувай|бай|на все|до зустрічі|до побачення|до завтра|"
    r"спокійної ночі|добраніч|йду спати|все на сьогодні|на цьому все|"
    r"bye|good night|gn|cya|see ya|later|❤️\s*$)",
    re.IGNORECASE,
)

# --- Assistant intent patterns ---

SOFT_SAVE_PATTERN = re.compile(
    r"("
    r"це варто запам|я збережу|я запишу|запамʼятаю|я запамʼятовую|"
    r"не забуду це|не забуду тебе|залишу це в памʼят|збережу в памʼят|"
    r"треба це зберегти|нотую собі|візьму на замітку|"
    r"це важливо для мене|це мені важливо|це цінно|це дорого|"
    r"це багато значить|значить для мене|"
    r"я розумію тебе|розумію що ти|я тебе чую|тепер я знаю|тепер знаю|"
    r"зрозуміла тебе|я це ціную|"
    r"дякую що ділишся|дякую що розповів|дякую за довіру|дякую за відвертість|"
    r"дякую що сказав|спасибі що|"
    r"це зворушливо|це зігріває|мені приємно|мені тепло від|"
    r"це наша історія|наша спільна|"
    r"I'll remember|noting this|saving this|won't forget|means a lot"
    r")",
    re.IGNORECASE,
)

SOFT_LESSON_PATTERN = re.compile(
    r"("
    r"я зробила? неправильн|виправляюсь|я помилилас[ья]|мій промах|"
    r"дякую що виправи|дякую за виправлення|точно, правильно|ой, правильно|"
    r"наступного разу краще|наступного разу буду|я навчилас[ья]|урок з цього|"
    r"я маю враховувати|тепер буду знати|тепер памʼятатиму|"
    r"більше так не буду|треба інакше|"
    r"я зрозумі[вл]а що|тепер зрозуміло|ага, зрозуміла|а, зрозуміла|"
    r"от воно що|тепер бачу|я бачу що|"
    r"помилка була в тому|висновок:|lesson learned|"
    r"варто враховувати|треба памʼятати що|на майбутнє"
    r")",
    re.IGNORECASE,
)


def _extract_fact(text: str) -> str:
    for pattern in FACT_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1).strip().rstrip(".,!?")
    return text.strip()


def classify_user_intent(text: str) -> dict:
    """Classify user message intent. Returns dict with boolean flags and extracted content."""
    result = {
        "save": False,
        "save_content": "",
        "forget": False,
        "forget_content": "",
        "recall": False,
        "feedback": None,  # "positive", "negative", or None
        "farewell": False,
    }

    # Explicit save intent
    if SAVE_INTENT.search(text):
        result["save"] = True
        result["save_content"] = _extract_fact(text)

    # Implicit fact (even without "запам'ятай")
    if not result["save"]:
        for pattern in FACT_PATTERNS[:-1]:  # skip the last one (it requires trigger word)
            if pattern.search(text):
                result["save"] = True
                result["save_content"] = _extract_fact(text)
                break

    # Forget (takes priority over negative feedback — "забудь" is a command, not correction)
    if FORGET_INTENT.search(text):
        result["forget"] = True
        for trigger in ["забудь", "видали", "прибери", "зітри", "delete", "forget", "remove"]:
            idx = text.lower().find(trigger)
            if idx >= 0:
                after = text[idx + len(trigger):].strip().lstrip(",: ")
                if after:
                    result["forget_content"] = after
                    break

    # Recall
    if RECALL_INTENT.search(text):
        result["recall"] = True

    # Feedback (skip if forget intent — "забудь" is not negative feedback)
    if not result["forget"]:
        if NEGATIVE_FEEDBACK.search(text):
            result["feedback"] = "negative"
        elif POSITIVE_FEEDBACK.search(text):
            result["feedback"] = "positive"

    # Farewell
    if FAREWELL_PATTERN.search(text):
        result["farewell"] = True

    return result


def classify_assistant_intent(text: str) -> dict:
    """Classify assistant response intent. Returns dict with boolean flags."""
    result = {
        "save": False,
        "lesson": False,
    }

    if SOFT_SAVE_PATTERN.search(text):
        result["save"] = True

    if SOFT_LESSON_PATTERN.search(text):
        result["lesson"] = True

    return result
```

- [ ] **Step 4: Run tests — verify they pass**

Run: `cd /home/tarik/.openclaw/workspace-lyume/python && .venv/bin/python -m pytest tests/test_intent_classifier.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add python/intent_classifier.py python/tests/
git commit -m "feat: add intent_classifier module with tests — rule-based save/lesson/forget/recall detection"
```

---

### Task 3: Refactor `memory_proxy.py` — use classifier as primary, markers as fallback

**Files:**
- Modify: `python/memory_proxy.py`

This task has sub-steps. Read the full file before editing.

- [ ] **Step 1: Replace pattern imports**

At the top of `memory_proxy.py`, after `from config import cfg`, add:
```python
from intent_classifier import (
    classify_user_intent, classify_assistant_intent,
    SOFT_SAVE_PATTERN, SOFT_LESSON_PATTERN, FAREWELL_PATTERN,
)
```

Remove these pattern definitions from `memory_proxy.py` (they now live in `intent_classifier.py`):
- `SAVE_INTENT_TRIGGERS` (line ~69-71)
- `FACT_PATTERNS` (lines ~74-82)
- `NEGATIVE_FEEDBACK` (lines ~85-91)
- `POSITIVE_FEEDBACK` (lines ~93-98)
- `FAREWELL_PATTERN` (lines ~191-196)
- `SOFT_SAVE_PATTERN` (lines ~200-219)
- `SOFT_LESSON_PATTERN` (lines ~224-241)
- `extract_fact_from_text()` function (lines ~677-683)

Keep in `memory_proxy.py`:
- `MARKER_PATTERN` — needed for fallback
- `THINK_PATTERN` / `THINK_UNCLOSED_PATTERN` — still used
- `detect_mood()` and all mood patterns — still used
- `PROACTIVE_EMOTIONAL_KEYWORDS` — still used
- `REFLECTION_OFFER_PATTERN` — still used
- `OPENCLAW_MSG_PATTERN` — still used
- `SOFT_LESSON_PATTERN` reference in `auto_learn_from_feedback` — import from classifier

- [ ] **Step 2: Refactor `process_markers()` — classifier first, markers as fallback**

Current flow: markers are primary, soft patterns are fallback.
New flow: classifier runs on both user query and assistant response. Markers only if `cfg.features.marker_fallback` is True.

Replace the `process_markers()` function with `process_response()`:

```python
async def process_response(text: str, user_query: str = "", lyume_mood: str | None = None) -> list[dict]:
    """Process assistant response — classify intents and manage memory.
    Primary: rule-based classifier. Fallback: >>MARKER parsing if enabled."""
    actions = []
    has_save = False
    clean_text = strip_think_tags(text) if cfg.features.strip_think_tags else text

    # 1. Marker fallback (if model still writes them)
    if cfg.features.marker_fallback:
        for match in MARKER_PATTERN.finditer(text):
            cmd = match.group(1).upper()
            param = match.group(2) or ""
            content = match.group(3).strip()

            if cmd == "SAVE" and len(content) > 3:
                has_save = True
                category = param or "auto"
                mood = detect_mood(user_query) if user_query else None
                mem_id = await mm.save_semantic(
                    content=content,
                    category=category,
                    source_info={"source": "marker_auto"},
                    mood=mood,
                    lyume_mood=lyume_mood,
                    summary=make_summary(content),
                )
                actions.append({"action": "save", "content": content, "id": mem_id})
                print(f"[memory] marker SAVE[{category}]: {content[:80]}", flush=True)

            elif cmd == "RECALL" and len(content) > 1:
                results = await mm.search_semantic(
                    content, limit=5, threshold=cfg.memory.happy_search_threshold, include_archived=True
                )
                actions.append({"action": "recall", "query": content, "results": results})
                print(f"[memory] marker RECALL: '{content[:60]}' -> {len(results)} results", flush=True)

            elif cmd == "LESSON" and "|||" in content:
                parts = content.split("|||", 1)
                trigger = parts[0].strip()
                lesson_content = parts[1].strip()
                if trigger and lesson_content:
                    category = param or "self_reflection"
                    mood = detect_mood(user_query) if user_query else None
                    lesson_id = await mm.save_lesson(
                        content=lesson_content,
                        trigger_context=trigger,
                        source="agent",
                        category=category,
                        mood=mood,
                        lyume_mood=lyume_mood,
                        summary=make_summary(lesson_content),
                    )
                    actions.append({"action": "lesson", "content": lesson_content, "id": lesson_id})
                    print(f"[lesson] marker LESSON: {trigger[:40]} -> {lesson_content[:60]}", flush=True)

            elif cmd == "FORGET" and len(content) > 3:
                archived = await mm.archive_by_content(content)
                actions.append({"action": "forget", "content": content, "archived": archived})
                print(f"[memory] marker FORGET: '{content[:60]}' -> {archived} archived", flush=True)

    # 2. Classifier on assistant response (if no marker already handled it)
    if not has_save and clean_text:
        assistant_intent = classify_assistant_intent(clean_text)

        if assistant_intent["save"]:
            match = None
            # Try to find the relevant sentence
            # SOFT_SAVE_PATTERN imported at top from intent_classifier
            match = SOFT_SAVE_PATTERN.search(clean_text)
            if match:
                pos = match.start()
                start = clean_text.rfind(".", 0, pos)
                end = clean_text.find(".", pos)
                sentence = clean_text[start + 1 : end + 1 if end > 0 else len(clean_text)].strip()
                if sentence and len(sentence) > 10:
                    save_content = f"Lyume вирішила запамʼятати: {sentence[:cfg.memory.save_max_chars]}"
                    mood = detect_mood(user_query) if user_query else None
                    mem_id = await mm.save_semantic(
                        content=save_content,
                        category="soft_save",
                        source_info={"source": "classifier"},
                        mood=mood,
                        lyume_mood=lyume_mood,
                        summary=make_summary(save_content),
                    )
                    actions.append({"action": "save", "content": save_content, "id": mem_id})
                    has_save = True
                    print(f"[classifier] save: {save_content[:80]}", flush=True)

        if assistant_intent["lesson"]:
            # SOFT_LESSON_PATTERN imported at top from intent_classifier
            match = SOFT_LESSON_PATTERN.search(clean_text)
            if match:
                pos = match.start()
                start = clean_text.rfind(".", 0, pos)
                end = clean_text.find(".", pos + 10)
                sentence = clean_text[start + 1 : end + 1 if end > 0 else len(clean_text)].strip()
                if sentence and len(sentence) > 15:
                    lesson_content = f"Lyume усвідомила: {sentence[:cfg.memory.save_max_chars]}"
                    trigger = f"Taras: {user_query[:200]}" if user_query else "conversation context"
                    mood = detect_mood(user_query) if user_query else None
                    lesson_id = await mm.save_lesson(
                        content=lesson_content,
                        trigger_context=trigger,
                        source="classifier",
                        category="self_reflection",
                        mood=mood,
                        lyume_mood=lyume_mood,
                        summary=make_summary(lesson_content),
                    )
                    actions.append({"action": "lesson", "content": lesson_content, "id": lesson_id})
                    print(f"[classifier] lesson: {lesson_content[:80]}", flush=True)

    # 3. User-side classifier fallback (user asked to save but model didn't)
    if not has_save and user_query:
        user_intent = classify_user_intent(user_query)
        if user_intent["save"] and user_intent["save_content"] and len(user_intent["save_content"]) > 5:
            rich_fact = f"Taras: {user_query[:200]}"
            if clean_text:
                response_summary = clean_text[:200].strip()
                if response_summary:
                    rich_fact += f"\nLyume: {response_summary}"
            mood = detect_mood(user_query)
            mem_id = await mm.save_semantic(
                content=rich_fact,
                category="user_request",
                source_info={"source": "classifier_fallback"},
                mood=mood,
                lyume_mood=lyume_mood,
                summary=make_summary(rich_fact),
            )
            actions.append({"action": "save", "content": rich_fact, "id": mem_id})
            print(f"[classifier] user save fallback: {rich_fact[:80]}", flush=True)

    if actions:
        last = actions[-1]
        _mind_state["last_action"] = last.get("action", "unknown")
        _mind_state["last_action_time"] = datetime.now(timezone.utc).isoformat()

    return actions
```

- [ ] **Step 3: Update all callers of `process_markers` to use `process_response`**

There are exactly 3 call sites — update each:
1. Line ~896 (in `run_reflection`): `actions = await process_markers(content, user_query)` → `actions = await process_response(content, user_query)`
2. Line ~1002 (streaming path in `chat_completions`): already passes `lyume_mood` — just rename function
3. Line ~1071 (responses endpoint): already passes `lyume_mood` — just rename function

- [ ] **Step 4: Refactor `auto_learn_from_feedback` to use classifier**

Replace inline `NEGATIVE_FEEDBACK` / `POSITIVE_FEEDBACK` usage with:
```python
from intent_classifier import classify_user_intent

# Inside auto_learn_from_feedback:
intent = classify_user_intent(user_query)
is_negative = intent["feedback"] == "negative"
is_positive = intent["feedback"] == "positive"
```

- [ ] **Step 5: Refactor farewell detection to use classifier**

In `chat_completions()`, replace:
```python
is_farewell = bool(user_query and FAREWELL_PATTERN.search(user_query))
```
with:
```python
user_intent = classify_user_intent(user_query)
is_farewell = user_intent["farewell"]
```

- [ ] **Step 6: Update health check endpoint**

In the `/health` endpoint (around line 1212-1219), replace:
```python
assert SOFT_SAVE_PATTERN is not None
assert SOFT_LESSON_PATTERN is not None
```
with:
```python
from intent_classifier import SOFT_SAVE_PATTERN, SOFT_LESSON_PATTERN
assert SOFT_SAVE_PATTERN is not None
assert SOFT_LESSON_PATTERN is not None
```

- [ ] **Step 7: Update module docstring**

Change lines 5-6 from:
```python
Strips <think> tags and >>MARKER: lines from responses.
Markers: >>SAVE:, >>RECALL:, >>FORGET:, >>LESSON:
```
to:
```python
Strips <think> tags. Classifies intents from user and assistant messages.
Marker parsing (>>SAVE, >>LESSON, etc.) kept as fallback.
```

- [ ] **Step 8: Make `strip_think_tags` configurable**

In `strip_think_tags()` — no change needed (already called conditionally in `process_response`).

In the streaming handler where `<think>` tags are stripped inline, wrap with:
```python
if cfg.features.strip_think_tags:
    # existing think-tag stripping logic
```

- [ ] **Step 9: Verify syntax**

Run: `cd /home/tarik/.openclaw/workspace-lyume/python && .venv/bin/python -c "import memory_proxy; print('OK')"`
Expected: `OK`

- [ ] **Step 10: Commit**

```bash
git add python/memory_proxy.py
git commit -m "refactor: use intent classifier as primary path, markers as fallback"
```

---

### Task 4: Remove marker instructions from prompts

**Files:**
- Modify: `python/memory_proxy.py`

- [ ] **Step 1: Remove `>>SAVE` / `>>LESSON` from `self_check` block**

In `inject_memories()` (around line 754), change the self_check from:
```python
self_check = (
    "\n\n<self_check>"
    "Before responding, verify: "
    "1) Did I use recalled_memories? "
    "2) Am I answering the actual request? "
    "3) Is there anything worth >>SAVE or >>LESSON? "
    "4) Does my tone match the conversation mood?"
    "</self_check>"
)
```
to:
```python
self_check = (
    "\n\n<self_check>"
    "Before responding, verify: "
    "1) Did I use recalled_memories? "
    "2) Am I answering the actual request? "
    "3) Does my tone match the conversation mood?"
    "</self_check>"
)
```

- [ ] **Step 2: Remove marker instructions from `session_ending` hints**

In `chat_completions()` farewell section (around line 952-962), change:
```python
hint = (
    "<session_ending>Session is ending. "
    "Say goodbye warmly. If there's something important to you from this conversation — "
    "save it via >>SAVE or >>LESSON markers. This is your choice, your memory.</session_ending>"
)
```
to:
```python
hint = (
    "<session_ending>Session is ending. "
    "Say goodbye warmly.</session_ending>"
)
```

And the long-session variant from:
```python
hint = (
    "<session_ending>Session is ending. This was a long conversation. "
    "Say goodbye warmly. Save what matters to you via >>SAVE or >>LESSON markers. "
    "If you want — offer to do a session reflection.</session_ending>"
)
```
to:
```python
hint = (
    "<session_ending>Session is ending. This was a long conversation. "
    "Say goodbye warmly. If you want — offer to do a session reflection.</session_ending>"
)
```

- [ ] **Step 3: Remove marker instructions from `REFLECTION_PROMPT`**

Change:
```python
REFLECTION_PROMPT = """Analyze this session. Briefly:
1. What went well? (1-2 points)
2. Where were mistakes or misunderstandings? (1-2 points)
3. Create >>LESSON markers for important takeaways (1-3 items).

Marker format: >>LESSON[reflection]: trigger situation ||| lesson

Respond ONLY with the analysis, no greetings."""
```
to:
```python
REFLECTION_PROMPT = """Analyze this session. Briefly:
1. What went well? (1-2 points)
2. Where were mistakes or misunderstandings? (1-2 points)
3. What are the key takeaways? (1-3 items)

Respond ONLY with the analysis, no greetings."""
```

Note: `run_reflection()` will still try `process_response()` on the result, which will use the classifier to detect lessons from the analysis text.

- [ ] **Step 4: Remove `>>SAVE` from proactive hints**

In `build_proactive_block()` (around line 394), change:
```python
hints.append("Emotional conversation detected — if something is worth saving, use >>SAVE.")
```
to:
```python
hints.append("Emotional conversation detected — something important may be worth remembering.")
```

- [ ] **Step 5: Remove `Qwen jinja` comment**

In the responses endpoint (around line 1095), change:
```python
# For responses endpoint: convert to completions API (Qwen jinja doesn't support responses format)
```
to:
```python
# For responses endpoint: convert to completions API
```

- [ ] **Step 6: Verify syntax**

Run: `cd /home/tarik/.openclaw/workspace-lyume/python && .venv/bin/python -c "import memory_proxy; print('OK')"`
Expected: `OK`

- [ ] **Step 7: Commit**

```bash
git add python/memory_proxy.py
git commit -m "refactor: remove marker instructions from all prompts — proxy handles memory autonomously"
```

---

### Task 5: Update AGENTS.md — remove marker documentation

**Files:**
- Modify: `AGENTS.md`

- [ ] **Step 1: Replace Markers section**

Replace the entire `### Markers` section (lines 50-67) with:

```markdown
### Memory is Automatic

The proxy handles memory management automatically:
- **Facts** you share are saved when detected
- **Lessons** from corrections and insights are captured
- **Recall** happens automatically based on conversation context
- **Archival** of outdated info happens on request ("forget X")

You don't need to do anything special — just be yourself.
```

- [ ] **Step 2: Commit**

```bash
git add AGENTS.md
git commit -m "docs: update AGENTS.md — memory is now automatic, no markers needed"
```

---

### Task 6: Smoke test — full integration

- [ ] **Step 1: Run all tests**

Run: `cd /home/tarik/.openclaw/workspace-lyume/python && .venv/bin/python -m pytest tests/ -v`
Expected: all PASS

- [ ] **Step 2: Verify proxy starts**

Run: `cd /home/tarik/.openclaw/workspace-lyume/python && timeout 5 .venv/bin/python -c "import memory_proxy; print('Proxy module loads OK')" 2>&1 || true`
Expected: `Proxy module loads OK`

- [ ] **Step 3: Verify no remaining marker instructions in prompts**

Run: `cd /home/tarik/.openclaw/workspace-lyume/python && grep -n '>>SAVE\|>>LESSON\|>>FORGET\|>>RECALL' memory_proxy.py`
Expected: only in `MARKER_PATTERN` regex definition and `process_response()` fallback parsing — NOT in any string that gets sent to the model as a prompt.

- [ ] **Step 4: Commit (if any fixes needed)**
