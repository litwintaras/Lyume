"""
Memory Proxy for Lyume.
Port 1235 → proxies to LM Studio (1234).
Injects relevant memories into system prompt.
Strips <think> tags. Classifies intents from user and assistant messages.
Marker parsing (>>SAVE, >>LESSON, etc.) kept as fallback.
"""

import asyncio
import hashlib
import json
import logging
import re
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse

logger = logging.getLogger(__name__)

from config import cfg
from memory_manager import MemoryManager, get_embedding, get_embedding_async
from intent_classifier import (
    classify_user_intent, classify_assistant_intent, is_noise,
    SOFT_SAVE_PATTERN, SOFT_LESSON_PATTERN, FAREWELL_PATTERN,
)
from session_tracker import SessionTracker
from bns import BNSEngine

from llm_client import LLMClient

_llm_client = LLMClient(
    url=cfg.llm.url,
    api_key=getattr(cfg.llm, "api_key", ""),
    model=getattr(cfg.llm, "model", ""),
    timeout=getattr(cfg.llm, "request_timeout", 300),
)

# Backward compat aliases (used throughout file in httpx calls — will be fully replaced later)
LM_STUDIO_URL = cfg.llm.url
LM_STUDIO_API_KEY = getattr(cfg.llm, "api_key", "")
LM_STUDIO_HEADERS = {
    "Content-Type": "application/json",
}
if LM_STUDIO_API_KEY:
    LM_STUDIO_HEADERS["Authorization"] = f"Bearer {LM_STUDIO_API_KEY}"
MEMORY_SEARCH_LIMIT = cfg.memory.search_limit
MEMORY_SIMILARITY_THRESHOLD = cfg.memory.similarity_threshold

# Request dedup — ignore identical requests within N seconds
REQUEST_DEDUP_TTL = cfg.memory.dedup_ttl
_recent_requests: dict[str, float] = {}  # hash → timestamp

# ── Tier 3F: Proactive initiative ──
# Thresholds for proactive behavior
_phs = cfg.memory.proactive_high_similarity
PROACTIVE_HIGH_SIM = _phs if isinstance(_phs, (int, float)) else 0.85
_pdd = cfg.memory.proactive_dormant_days
PROACTIVE_DORMANT_DAYS = _pdd if isinstance(_pdd, (int, float)) else 30
PROACTIVE_EMOTIONAL_KEYWORDS = re.compile(
    r"(люблю|ненавиджу|боюсь|мрію|хочу|сумую|скучаю|тривож|хвилюю|радію|пишаюсь|"
    r"болить|важко|складно|страшно|щасливий|щаслива|вдячний|вдячна|самотн|love|miss|dream|fear|worry)",
    re.IGNORECASE,
)
# Session topic tracking
_session_topics: list[str] = []  # recent user queries this session

# Mind state tracking (for dashboard)
_mind_state = {
    "last_mood": None,         # last detected Lyume mood
    "last_mood_time": None,    # when it was detected
    "last_user_query": None,   # last user message
    "last_user_time": None,    # when last user message came
    "last_action": None,       # last marker action (SAVE/RECALL/LESSON/FORGET)
    "last_action_time": None,
    "session_start": None,     # when proxy started this session
    "bns_state": None,         # current BNS chemical state
}

THINK_PATTERN = re.compile(r"<think>.*?</think>", re.DOTALL)
THINK_UNCLOSED_PATTERN = re.compile(r"<think>.*", re.DOTALL)

# All marker patterns
MARKER_PATTERN = re.compile(
    r">>(SAVE|RECALL|FORGET|LESSON|USEFUL|USELESS|RATE_LESSON)(?:\[([^\]]*)\])?:\s*(.+?)(?:\n|$)", re.IGNORECASE
)

# Emoji → mood mapping (emotional context for "pleasant memories")
EMOJI_MOOD_MAP = {
    # Warm / love
    "❤️": "warm", "💕": "warm", "🥰": "warm", "😘": "warm", "💖": "warm",
    "💗": "warm", "💛": "warm", "🫶": "warm", "❤": "warm",
    # Joy / fun
    "😂": "fun", "🤣": "fun", "😄": "fun", "😁": "fun", "😆": "fun",
    "😅": "awkward",
    "😊": "happy", "🙂": "happy", "☺️": "happy", "🎉": "happy", "🥳": "happy",
    # Excitement / approval
    "🔥": "excited", "💪": "excited", "🚀": "excited", "⚡": "excited",
    "👍": "approval", "👏": "approval", "🙌": "approval", "✅": "approval",
    "💯": "approval",
    # Cool / chill
    "😎": "cool", "🤙": "cool", "✨": "cool",
    # Frustration / anger
    "😡": "frustrated", "🤬": "frustrated", "😤": "frustrated", "💩": "frustrated",
    "😠": "angry",
    # Sadness
    "😢": "sad", "😭": "sad", "😞": "sad", "😔": "sad", "🥺": "sad",
    # Confusion / thinking
    "🤔": "thinking", "❓": "confused", "🤷": "confused",
    # Sarcasm / irony
    "🙃": "ironic", "😏": "ironic",
}


# Text → mood mapping (no emoji needed)
TEXT_MOOD_MAP = [
    (re.compile(r"дякую|дяки|спасибі|thx|thanks|thank you", re.IGNORECASE), "warm"),
    (re.compile(r"люблю|love|обожнюю|кохаю", re.IGNORECASE), "warm"),
    (re.compile(r"круто|кайф|вогонь|бомба|awesome|amazing", re.IGNORECASE), "excited"),
    (re.compile(r"смішно|ржу|лол|lol|haha|ахах", re.IGNORECASE), "fun"),
    (re.compile(r"класно|прикольно|файно|nice|cool|neat", re.IGNORECASE), "happy"),
    (re.compile(r"молодець|красава|гарна робота|good job|well done", re.IGNORECASE), "approval"),
    (re.compile(r"блін|чорт|damn|shit|курва|тьху", re.IGNORECASE), "frustrated"),
    (re.compile(r"не працює|зламав|broken|баг|bug|помилка|error", re.IGNORECASE), "frustrated"),
    (re.compile(r"сумно|жаль|шкода|sad|unfortunately", re.IGNORECASE), "sad"),
    (re.compile(r"не розумію|шо|що\?|huh|wut|незрозуміло", re.IGNORECASE), "confused"),
]


# Formatting signals
BOLD_PATTERN = re.compile(r"\*\*[^*]+\*\*")
CAPS_PATTERN = re.compile(r"\b[A-ZА-ЯІЇЄҐ]{3,}\b")
EXCLAIM_PATTERN = re.compile(r"!{2,}")


def detect_mood(text: str) -> str | None:
    """Detect mood from emojis, text and formatting. Returns dominant mood or None."""
    moods: dict[str, int] = {}
    # Emoji detection
    for emoji, mood in EMOJI_MOOD_MAP.items():
        count = text.count(emoji)
        if count > 0:
            moods[mood] = moods.get(mood, 0) + count * 2  # emoji = strong signal
    # Text detection
    for pattern, mood in TEXT_MOOD_MAP:
        if pattern.search(text):
            moods[mood] = moods.get(mood, 0) + 1
    # Formatting = emphasis/passion
    bold_count = len(BOLD_PATTERN.findall(text))
    caps_count = len(CAPS_PATTERN.findall(text))
    exclaim_count = len(EXCLAIM_PATTERN.findall(text))
    emphasis = bold_count + caps_count + exclaim_count
    if emphasis >= 2:
        moods["passionate"] = moods.get("passionate", 0) + emphasis
    if not moods:
        return None
    return max(moods, key=moods.get)

mm = MemoryManager()
session_tracker: SessionTracker | None = None

# BNS — Neurochemical Simulation
_bns = BNSEngine(state_path=str(Path(__file__).parent / "bns_state.json"))


_EMOJI_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F680-\U0001F6FF"  # transport & map
    "\U0001F1E0-\U0001F1FF"  # flags
    "\U00002702-\U000027B0"
    "\U0000FE00-\U0000FE0F"  # variation selectors
    "\U0000200D"             # zero width joiner
    "\U00002640-\U00002642"
    "\U0001F900-\U0001F9FF"  # supplemental symbols
    "\U00002600-\U000026FF"
    "]+",
)

_WRAPPER_RE = re.compile(
    r"^(Lyume вирішила запамʼятати:\s*|Lyume усвідомила:\s*|Taras:\s*)",
    re.IGNORECASE,
)


def clean_for_memory(text: str) -> str:
    """Strip emoji, wrapper prefixes, and excessive whitespace from memory content."""
    text = _EMOJI_RE.sub("", text)
    text = _WRAPPER_RE.sub("", text)
    # Collapse whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def make_summary(text: str, max_len: int = 150) -> str:
    """Extract a short summary from text — first meaningful sentence or truncated."""
    text = text.strip()
    # Try first sentence
    for sep in [". ", ".\n", "!\n", "?\n"]:
        if sep in text:
            first = text[:text.index(sep) + 1].strip()
            if 10 < len(first) <= max_len:
                return first
    # Truncate at word boundary
    if len(text) <= max_len:
        return text
    cut = text[:max_len].rsplit(" ", 1)[0]
    return cut + "..."



REFLECTION_PROMPT = """Analyze this session. Briefly:
1. What went well? (1-2 points)
2. Where were mistakes or misunderstandings? (1-2 points)
3. What are the key takeaways? (1-3 items)

Respond ONLY with the analysis, no greetings."""

# Detect when Lyume offered reflection and user agreed
REFLECTION_OFFER_PATTERN = re.compile(
    r"рефлексі[юї]|провела?\s+аналіз|проаналізу",
    re.IGNORECASE,
)


_auto_detect_cache: dict = {"last_check": 0.0, "ttl": 60}


def auto_detect_model(force: bool = False):
    """
    Автоматично визначає моделі через GET запит до /v1/models.
    Записує першу модель без 'embed' у cfg.llm.model,
    першу модель з 'embed' у cfg.embedding.model.
    У разі помилки або невдачі — залишає поточні значення.
    Кешує результат на 60 секунд.
    """
    now = time.monotonic()
    if not force and now - _auto_detect_cache["last_check"] < _auto_detect_cache["ttl"]:
        return
    _auto_detect_cache["last_check"] = now
    try:
        response = httpx.get(f"{cfg.llm.url}/v1/models", timeout=5)
        response.raise_for_status()
        models_data = response.json()

        if not isinstance(models_data, dict) or "data" not in models_data:
            print("[auto-detect] failed, using config: no valid models data", flush=True)
            return

        models = models_data["data"]
        if not isinstance(models, list):
            print("[auto-detect] failed, using config: models is not a list", flush=True)
            return

        llm_model = None
        embed_model = None

        for model in models:
            model_name = model.get("id", "")
            if not isinstance(model_name, str):
                continue
            if 'embed' in model_name.lower() and embed_model is None:
                embed_model = model_name
            elif 'embed' not in model_name.lower() and llm_model is None:
                llm_model = model_name

        if llm_model and llm_model != cfg.llm.model:
            print(f"[auto-detect] model: {llm_model}", flush=True)
            cfg.llm.model = llm_model
        if embed_model and embed_model != cfg.embedding.model:
            print(f"[auto-detect] embedding: {embed_model}", flush=True)
            print(f"[auto-detect] hint: for OpenClaw memory_search, set memorySearch.model to '{embed_model}'", flush=True)
            cfg.embedding.model = embed_model

        if not llm_model and not embed_model:
            print("[auto-detect] no models found at backend", flush=True)

    except Exception as e:
        print(f"[auto-detect] failed, using config: {e}", flush=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Check if first run — launch wizard
    config_path = str(Path(__file__).parent / "config.yaml")
    from wizard import should_run_wizard
    if should_run_wizard(config_path):
        from wizard import run_wizard
        run_wizard(config_path)
        # Reload config after wizard
        import importlib
        import config as config_module
        importlib.reload(config_module)
        from config import cfg as new_cfg
        # Update LLM client
        global _llm_client, LM_STUDIO_URL, LM_STUDIO_API_KEY, LM_STUDIO_HEADERS
        _llm_client = LLMClient(
            url=new_cfg.llm.url,
            api_key=getattr(new_cfg.llm, "api_key", ""),
            model=getattr(new_cfg.llm, "model", ""),
            timeout=getattr(new_cfg.llm, "request_timeout", 300),
        )
        LM_STUDIO_URL = new_cfg.llm.url
        LM_STUDIO_API_KEY = getattr(new_cfg.llm, "api_key", "")
        LM_STUDIO_HEADERS = {"Content-Type": "application/json"}
        if LM_STUDIO_API_KEY:
            LM_STUDIO_HEADERS["Authorization"] = f"Bearer {LM_STUDIO_API_KEY}"

    await mm.connect()

    # Auto-detect models from LM Studio
    auto_detect_model(force=True)

    # Deferred memory import (from wizard)
    if hasattr(cfg, '_import_paths') and cfg._import_paths:
        from memory_import import ImportPipeline
        from embedding_client import create_embedding_client
        emb_cfg = cfg.embedding
        embed_client = create_embedding_client(
            provider=getattr(emb_cfg, "provider", "http"),
            url=getattr(emb_cfg, "url", ""),
            api_key=getattr(emb_cfg, "api_key", ""),
            model=getattr(emb_cfg, "model", "nomic-embed-text"),
            model_path=getattr(emb_cfg, "model_path", ""),
        )
        pipeline = ImportPipeline(memory_manager=mm, embedding_client=embed_client)
        for path in cfg._import_paths:
            stats = await pipeline.import_directory(path)
            print(f"[import] {path}: {stats['imported']} imported, {stats['duplicate']} duplicates", flush=True)

    _mind_state["session_start"] = datetime.now(timezone.utc).isoformat()
    global session_tracker
    if cfg.features.session_summary:
        session_tracker = SessionTracker(mm, LM_STUDIO_URL, LM_STUDIO_HEADERS)
        print("[session] Session tracker enabled", flush=True)
    print("Memory proxy started — port 1235 → LM Studio 1234", flush=True)
    yield
    await mm.close()


app = FastAPI(lifespan=lifespan)


# OpenClaw wraps user messages as:
# "Sender (untrusted metadata):\n```json\n{...}\n```\n\n[timestamp] actual text"
OPENCLAW_MSG_PATTERN = re.compile(r"\]\s*(.+)$", re.DOTALL)


def extract_user_query(messages: list[dict]) -> str:
    """Get the last user message for memory search, stripping OpenClaw metadata."""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, list):
                parts = [p.get("text", "") for p in content if p.get("type") == "text"]
                content = " ".join(parts)

            if "Sender (untrusted metadata)" in content:
                match = OPENCLAW_MSG_PATTERN.search(content)
                if match:
                    return match.group(1).strip()

            return content
    return ""


MOOD_HINTS = {
    "warm": "теплий спогад",
    "fun": "веселий момент",
    "happy": "приємний спогад",
    "excited": "яскравий момент",
    "approval": "він це оцінив",
    "cool": "було круто",
    "awkward": "трохи ніяково",
    "passionate": "емоційний момент",
    "frustrated": "було напружено",
    "angry": "неприємний момент",
    "sad": "сумний спогад",
    "thinking": "він задумався",
    "confused": "було незрозуміло",
    "ironic": "з іронією",
}


def _mood_hint(user_mood: str | None, lyume_mood: str | None) -> str:
    """Natural language mood hint for recalled memories."""
    # Prioritize: user mood first, then lyume mood
    mood = user_mood or lyume_mood
    if not mood:
        return ""
    hint = MOOD_HINTS.get(mood, "")
    return f" ({hint})" if hint else ""


def build_memory_block(memories: list[dict]) -> str:
    """Format memories as authoritative context — not just data, but instruction."""
    if not memories:
        return ""
    lines = [
        "\n\n<recalled_memories>",
        "THIS IS YOUR MEMORY. These memories were already retrieved for this message.",
        "Use them BEFORE searching via tools.",
        "If the answer can be composed from these memories — respond immediately.",
        "",
    ]
    for m in memories:
        sim = m["similarity"]
        tag = " [archived]" if m.get("archived") else ""
        hint = _mood_hint(m.get("mood"), m.get("lyume_mood"))
        # High relevance (>80%) — show full content; otherwise summary
        text = m["content"]
        summary_sim = getattr(cfg.memory, 'summary_similarity', 0.8)
        if not isinstance(summary_sim, (int, float)):
            summary_sim = 0.8
        if sim < summary_sim and m.get("summary"):
            text = m["summary"]
        lines.append(f"- [{sim:.0%}]{tag} {text}{hint}")
    lines.append("</recalled_memories>")
    return "\n".join(lines)


MOOD_LABELS = {
    "warm": "💛", "fun": "😄", "happy": "😊", "excited": "🔥",
    "approval": "👍", "cool": "😎", "awkward": "😅", "passionate": "💥",
    "frustrated": "😤", "angry": "😠", "sad": "😢", "thinking": "🤔",
    "confused": "❓", "ironic": "🙃",
}


def build_intuition_block(lessons: list[dict]) -> str:
    """Format lessons as intuitive knowledge — past experience that guides behavior."""
    if not lessons:
        return ""
    lines = [
        "\n\n<intuition>",
        "This is your experience from past situations. Consider before responding.",
        "",
    ]
    for l in lessons:
        hint = _mood_hint(l.get("mood"), l.get("lyume_mood"))
        lines.append(f"- [{l['id']}] {l['content']}{hint}")
    lines.append("</intuition>")
    return "\n".join(lines)


def build_proactive_block(memories: list[dict], user_query: str) -> str:
    """Generate proactive hints based on memory patterns."""
    hints = []
    now = datetime.now(timezone.utc)

    for m in memories:
        sim = m["similarity"]
        summary = m.get("summary") or m["content"][:100]

        # High similarity — nudge "до речі, ти раніше згадував..."
        if sim >= PROACTIVE_HIGH_SIM and m.get("access_count", 0) <= 2:
            hints.append(f"This memory is very close to the current topic: «{summary}» — mention it naturally.")

        # Dormant memory — not accessed for a while but matches
        if m.get("last_accessed"):
            last = datetime.fromisoformat(m["last_accessed"])
            days_ago = (now - last).days
            if days_ago >= PROACTIVE_DORMANT_DAYS and sim > cfg.memory.dormant_hint_similarity:
                hints.append(f"Dormant memory ({days_ago}d since last access): «{summary}»")

    # Emotional depth — suggest saving if conversation is emotional
    if PROACTIVE_EMOTIONAL_KEYWORDS.search(user_query) and not hints:
        hints.append("Emotional conversation detected — something important may be worth remembering.")

    # Topic continuity — detect returning to a topic
    if _session_topics:
        for prev in _session_topics[-5:]:
            # Simple overlap check (>threshold words in common)
            prev_words = set(prev.lower().split())
            curr_words = set(user_query.lower().split())
            if len(prev_words) > 2 and len(curr_words) > 2:
                overlap = len(prev_words & curr_words) / min(len(prev_words), len(curr_words))
                if overlap > cfg.memory.overlap_threshold:
                    hints.append("You are returning to a topic already discussed earlier in this session.")
                    break

    if not hints:
        return ""

    lines = ["\n\n<proactive>", "Hints based on your experience:", ""]
    for h in hints[:3]:  # Max 3 hints
        lines.append(f"- {h}")
    lines.append("</proactive>")
    print(f"[proactive] {len(hints)} hints generated", flush=True)
    return "\n".join(lines)


def build_warmup_block(memories: list[dict], lessons: list[dict]) -> str:
    """Format session warmup — most important memories and lessons for cold start."""
    if not memories and not lessons:
        return ""
    lines = [
        "\n\n<session_warmup>",
        "This is the start of a new session. Here are your most important memories — "
        "weave them naturally into conversation.",
        "",
    ]
    if memories:
        lines.append("Key memories:")
        for m in memories:
            hint = _mood_hint(m.get("mood"), m.get("lyume_mood"))
            text = m.get("summary") or m["content"][:150]
            access = m.get("access_count", 0)
            lines.append(f"- [{access}x accessed] {text}{hint}")
    if lessons:
        lines.append("")
        lines.append("Recent lessons:")
        for l in lessons:
            hint = _mood_hint(l.get("mood"), l.get("lyume_mood"))
            lines.append(f"- {l['content'][:150]}{hint}")
    lines.append("</session_warmup>")
    return "\n".join(lines)


def strip_think_tags(text: str) -> str:
    """Strip <think>...</think> tags. Handles closed and unclosed tags."""
    text = THINK_PATTERN.sub("", text)
    text = THINK_UNCLOSED_PATTERN.sub("", text)
    return text.strip()


def strip_markers(text: str) -> str:
    """Remove all >>MARKER: lines from visible output."""
    return MARKER_PATTERN.sub("", text).strip()


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
                content = clean_for_memory(content)
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

            elif cmd == "USEFUL":
                lesson_id = content.strip()
                delta = getattr(cfg.lessons, 'elo_implicit_delta', 5)
                try:
                    new_rating = await mm.update_lesson_elo(lesson_id, delta=delta)
                    actions.append({"action": "useful", "lesson_id": lesson_id, "new_rating": new_rating})
                    print(f"[elo] USEFUL: {lesson_id} → rating {new_rating}", flush=True)
                except ValueError as e:
                    print(f"[elo] USEFUL failed: {e}", flush=True)

            elif cmd == "USELESS":
                lesson_id = content.strip()
                actions.append({"action": "useless", "lesson_id": lesson_id})
                print(f"[elo] USELESS: {lesson_id} (no penalty)", flush=True)

            elif cmd == "RATE_LESSON":
                parts = content.rsplit(":", 1)
                if len(parts) == 2 and parts[1].strip() in ("+", "-"):
                    lesson_id = parts[0].strip()
                    delta = getattr(cfg.lessons, 'elo_explicit_delta', 10)
                    if parts[1].strip() == "-":
                        delta = -delta
                    try:
                        new_rating = await mm.update_lesson_elo(lesson_id, delta=delta)
                        rating_sign = "+" if parts[1].strip() == "+" else "-"
                        actions.append({"action": "rate_lesson", "lesson_id": lesson_id, "rating": rating_sign, "new_rating": new_rating})
                        print(f"[elo] RATE_LESSON: {lesson_id} {rating_sign} → rating {new_rating}", flush=True)
                    except ValueError as e:
                        print(f"[elo] RATE_LESSON failed: {e}", flush=True)
                else:
                    print(f"[elo] RATE_LESSON format invalid: {content}", flush=True)

    # 2. User-side classifier fallback (user asked to save but model didn't)
    if not has_save and user_query:
        user_intent = classify_user_intent(user_query)
        if user_intent["save"] and user_intent["save_content"] and len(user_intent["save_content"]) > 5:
            rich_fact = clean_for_memory(user_intent["save_content"][:300])
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
            has_save = True
            print(f"[classifier] user save fallback: {rich_fact[:80]}", flush=True)

    # 3. Classifier on assistant response (if no marker already handled it)
    if not has_save and clean_text:
        assistant_intent = classify_assistant_intent(clean_text)

        if assistant_intent["save"]:
            match = SOFT_SAVE_PATTERN.search(clean_text)
            if match:
                pos = match.start()
                start = clean_text.rfind(".", 0, pos)
                end = clean_text.find(".", pos)
                sentence = clean_text[start + 1 : end + 1 if end > 0 else len(clean_text)].strip()
                if sentence and len(sentence) > 10:
                    save_content = clean_for_memory(sentence[:cfg.memory.save_max_chars])
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

    if actions:
        last = actions[-1]
        _mind_state["last_action"] = last.get("action", "unknown")
        _mind_state["last_action_time"] = datetime.now(timezone.utc).isoformat()

    return actions


def _find_previous_exchange(messages: list[dict]) -> tuple[str | None, str | None]:
    """Walk backwards to find last assistant response and the user message before it."""
    assistant_msg = None
    user_before = None
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        role = msg.get("role", "")
        content = msg.get("content", "")
        if isinstance(content, list):
            parts = [p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"]
            content = " ".join(parts)
        if not isinstance(content, str) or len(content) < 5:
            continue

        if role == "assistant" and not assistant_msg:
            assistant_msg = content[:200]
        elif role == "user" and assistant_msg:
            if "Sender (untrusted metadata)" in content:
                match = OPENCLAW_MSG_PATTERN.search(content)
                if match:
                    user_before = match.group(1).strip()[:200]
            else:
                user_before = content[:200]
            break
    return assistant_msg, user_before


async def auto_learn_from_feedback(messages: list[dict], user_query: str):
    """Detect feedback (negative or positive) and create a lesson."""
    if not user_query:
        return

    intent = classify_user_intent(user_query)
    is_negative = intent["feedback"] == "negative"
    is_positive = intent["feedback"] == "positive"

    if not is_negative and not is_positive:
        return

    feedback_type = "negative" if is_negative else "positive"
    print(f"[auto-learn] {feedback_type} feedback: {user_query[:60]}", flush=True)

    assistant_msg, user_before = _find_previous_exchange(messages)
    if not assistant_msg or not user_before:
        print(f"[auto-learn] Skipped: assistant={bool(assistant_msg)}, user_before={bool(user_before)}", flush=True)
        return

    trigger = f"Тарас попросив: {user_before}"

    if is_negative:
        lesson = f"Тарас: {user_before}\nLyume відповіла: {assistant_msg[:150]}\nТарас сказав '{user_query}' — відповідь була неправильна."
        category = "correction"
    else:
        lesson = f"Тарас: {user_before}\nLyume відповіла: {assistant_msg[:150]}\nТарас схвалив — такий підхід працює."
        category = "reinforcement"

    mood = detect_mood(user_query)
    lyume_mood = detect_mood(assistant_msg) if assistant_msg else None

    lesson_id = await mm.save_lesson(
        content=lesson,
        trigger_context=trigger,
        source="auto_feedback",
        category=category,
        mood=mood,
        lyume_mood=lyume_mood,
        summary=make_summary(lesson),
    )
    mood_str = f" mood={mood}" if mood else ""
    lm_str = f" lyume={lyume_mood}" if lyume_mood else ""
    print(f"[auto-learn] {category} lesson saved (id={lesson_id}){mood_str}{lm_str}", flush=True)
    print(f"[auto-learn]   trigger: {trigger[:80]}", flush=True)
    print(f"[auto-learn]   lesson: {lesson[:80]}", flush=True)


LESSON_SEARCH_LIMIT = cfg.lessons.search_limit
LESSON_SIMILARITY_THRESHOLD = cfg.lessons.similarity_threshold


async def inject_memories(body: dict) -> dict:
    """Search memories and lessons, inject into system prompt."""
    messages = body.get("messages", [])
    if not messages:
        return body

    user_query = extract_user_query(messages)
    if not user_query:
        return body

    if is_noise(user_query):
        print(f"[memory] Noise skipped: {user_query[:40]}", flush=True)
        return body

    # Session recall — explicit "what did we do last time?"
    user_intent = classify_user_intent(user_query)
    is_explicit = bool(user_intent.get("recall"))
    if user_intent.get("session_recall") and session_tracker:
        session_memories = await mm.get_recent_summaries(limit=3)
        if session_memories:
            lines = [
                "\n\n<session_history>",
                "Previous session summaries (chronological):",
                "",
            ]
            for s in reversed(session_memories):
                lines.append(f"- {s['content']}")
            lines.append("</session_history>")
            session_block = "\n".join(lines)
            if messages and messages[0].get("role") == "system":
                messages[0] = {
                    **messages[0],
                    "content": messages[0]["content"] + session_block,
                }
            else:
                messages.insert(0, {"role": "system", "content": session_block.strip()})
            print(f"[session] Recalled {len(session_memories)} session summaries", flush=True)

    t0 = time.monotonic()

    # Count user messages — for warmup detection
    user_msg_count = sum(1 for m in messages if m.get("role") == "user")

    # Compute embedding ONCE, pass to both search functions
    query_embedding = await get_embedding_async(user_query)
    t_embed = time.monotonic()

    memories, lessons = await asyncio.gather(
        mm.search_hybrid(
            user_query, limit=MEMORY_SEARCH_LIMIT, threshold=MEMORY_SIMILARITY_THRESHOLD,
            embedding=query_embedding,
            explicit_recall=is_explicit,
        ) if getattr(cfg.memory, 'hybrid_search', False) else mm.search_semantic(
            user_query, limit=MEMORY_SEARCH_LIMIT, threshold=MEMORY_SIMILARITY_THRESHOLD,
            embedding=query_embedding,
            explicit_recall=is_explicit,
        ),
        mm.search_lessons_balanced(
            user_query, limit=LESSON_SEARCH_LIMIT, threshold=LESSON_SIMILARITY_THRESHOLD,
            embedding=query_embedding,
            explicit_recall=is_explicit,
        ),
    )
    t_search = time.monotonic()
    print(f"[timing] embed={t_embed-t0:.3f}s search={t_search-t_embed:.3f}s total={t_search-t0:.3f}s", flush=True)

    # Session warmup — first message only, fetch top memories regardless of query
    warmup_block = ""
    if user_msg_count <= 1:
        top_memories, recent_lessons = await asyncio.gather(
            mm.get_top_memories(limit=5),
            mm.get_recent_lessons(limit=3),
        )
        if top_memories or recent_lessons:
            warmup_block = build_warmup_block(top_memories, recent_lessons)
            print(f"[warmup] Session start — {len(top_memories)} top memories, {len(recent_lessons)} lessons", flush=True)

    # Track session topics for continuity detection
    _session_topics.append(user_query)
    _mind_state["last_user_query"] = user_query[:100]
    _mind_state["last_user_time"] = datetime.now(timezone.utc).isoformat()

    if not memories and not lessons and not warmup_block:
        return body

    memory_block = build_memory_block(memories)
    intuition_block = build_intuition_block(lessons)
    proactive_block = build_proactive_block(memories, user_query) if memories else ""

    if memories:
        print(f"[memory] Found {len(memories)} memories for: {user_query[:60]}", flush=True)
    if lessons:
        print(f"[intuition] Found {len(lessons)} lessons for: {user_query[:60]}", flush=True)

    new_messages = list(messages)

    # Self-check hint: remind Lyume to check memories and consider saving
    if memories or lessons:
        self_check = (
            "\n\n<self_check>"
            "Before responding, verify: "
            "1) Did I use recalled_memories? "
            "2) Am I answering the actual request? "
            "3) Does my tone match the conversation mood?"
            "</self_check>"
        )
    else:
        self_check = ""

    # Memories + warmup go into system prompt (background context)
    system_injection = ""
    if warmup_block:
        system_injection += warmup_block
    if memory_block:
        system_injection += memory_block

    # BNS emotional state injection
    bns_block = _bns.get_prompt_injection()
    if bns_block:
        system_injection += "\n\n" + bns_block

    if system_injection:
        if new_messages and new_messages[0].get("role") == "system":
            new_messages[0] = {
                **new_messages[0],
                "content": new_messages[0]["content"] + system_injection,
            }
        else:
            new_messages.insert(0, {"role": "system", "content": system_injection.strip()})

    # Intuition + proactive + self-check go right before the last user message (high attention zone)
    inject_before_user = ""
    if intuition_block:
        inject_before_user += intuition_block.strip()
    if proactive_block:
        inject_before_user += "\n\n" + proactive_block.strip()
    if self_check:
        inject_before_user += "\n\n" + self_check.strip()

    if inject_before_user:
        last_user_idx = None
        for i in range(len(new_messages) - 1, -1, -1):
            if new_messages[i].get("role") == "user":
                last_user_idx = i
                break
        if last_user_idx is not None:
            new_messages.insert(last_user_idx, {
                "role": "system",
                "content": inject_before_user,
            })

    return {**body, "messages": new_messages}


async def inject_memories_responses(data: dict) -> dict:
    """Inject memories into Responses API format (uses 'input' and 'instructions')."""
    user_input = data.get("input", "")
    if isinstance(user_input, list):
        # Extract text from input items
        parts = []
        for item in user_input:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "message" and item.get("role") == "user":
                content = item.get("content", "")
                if isinstance(content, str):
                    parts.append(content)
                elif isinstance(content, list):
                    for c in content:
                        if isinstance(c, dict) and c.get("type") == "input_text":
                            parts.append(c.get("text", ""))
        user_input = " ".join(parts)

    if not user_input:
        return data

    if is_noise(user_input):
        print(f"[memory] Noise skipped (responses): {user_input[:40]}", flush=True)
        return data

    # Strip OpenClaw metadata
    if "Sender (untrusted metadata)" in user_input:
        match = OPENCLAW_MSG_PATTERN.search(user_input)
        if match:
            user_input = match.group(1).strip()

    query_embedding = await get_embedding_async(user_input)
    search_coro = (
        mm.search_hybrid(
            user_input, limit=MEMORY_SEARCH_LIMIT,
            threshold=MEMORY_SIMILARITY_THRESHOLD,
            embedding=query_embedding, explicit_recall=False,
        )
        if getattr(cfg.memory, 'hybrid_search', False)
        else mm.search_semantic(
            user_input, limit=MEMORY_SEARCH_LIMIT,
            threshold=MEMORY_SIMILARITY_THRESHOLD,
            embedding=query_embedding, explicit_recall=False,
        )
    )
    memories, lessons = await asyncio.gather(
        search_coro,
        mm.search_lessons_balanced(user_input, limit=LESSON_SEARCH_LIMIT, threshold=LESSON_SIMILARITY_THRESHOLD, embedding=query_embedding),
    )

    if not memories and not lessons:
        return data

    memory_block = build_memory_block(memories)
    intuition_block = build_intuition_block(lessons)

    if memories:
        print(f"[memory] Found {len(memories)} memories for: {user_input[:60]}", flush=True)
    if lessons:
        print(f"[intuition] Found {len(lessons)} lessons for: {user_input[:60]}", flush=True)

    # Inject into instructions field
    instructions = data.get("instructions", "") or ""
    if memory_block:
        instructions += memory_block
    if intuition_block:
        instructions += intuition_block
    data["instructions"] = instructions

    return data


async def run_reflection(messages: list[dict], user_query: str):
    """Background task: send conversation to Lyume for self-reflection."""
    try:
        # Build reflection request with conversation history
        reflection_messages = []
        for msg in messages:
            role = msg.get("role", "")
            if role in ("user", "assistant"):
                reflection_messages.append(msg)

        # Cap history to avoid huge requests
        if len(reflection_messages) > cfg.llm.reflection_max_messages:
            reflection_messages = reflection_messages[-cfg.llm.reflection_max_messages:]

        reflection_messages.append({
            "role": "user",
            "content": REFLECTION_PROMPT,
        })

        async with httpx.AsyncClient(timeout=cfg.llm.reflection_timeout) as client:
            resp = await client.post(
                f"{LM_STUDIO_URL}/v1/chat/completions",
                headers=LM_STUDIO_HEADERS,
                json={
                    "model": cfg.llm.model,
                    "messages": reflection_messages,
                    "max_tokens": 4096,
                    "stream": False,
                },
            )
        result = resp.json()
        content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        if content:
            content = strip_think_tags(content)
            actions = await process_response(content, user_query)
            lesson_count = sum(1 for a in actions if a["action"] == "lesson")
            print(f"[reflection] Done — {lesson_count} lessons extracted", flush=True)
            if not actions:
                print(f"[reflection] No markers found in response: {content[:200]}", flush=True)
        else:
            print("[reflection] Empty response from model", flush=True)
    except Exception as e:
        print(f"[reflection] Error: {e}", flush=True)


async def _safe_process_response(text: str, query: str, mood: str | None):
    """Fire-and-forget wrapper for process_response + BNS update."""
    try:
        await process_response(text, query, lyume_mood=mood)
        # BNS: process assistant response mood (feedback loop)
        if mood:
            _bns.process_output_mood(mood)
            spike = _bns.state.has_spike()
            if spike:
                print(f"[bns] SPIKE detected: {spike['chemical']}={spike['level']:.2f}", flush=True)
    except Exception as e:
        print(f"[process] Error in background: {e}", flush=True)


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    messages = body.get("messages", [])
    user_query = extract_user_query(messages)

    # Session tracking
    if session_tracker and user_query:
        if session_tracker.check_timeout():
            print("[session] Timeout detected, summarizing old session...", flush=True)
            asyncio.create_task(session_tracker.generate_summary("timeout"))
            session_tracker.start_new_session()
        session_tracker.track_message("user", user_query)

    # Request dedup — skip identical requests within TTL
    now = time.monotonic()
    # Clean expired entries
    expired = [h for h, t in _recent_requests.items() if now - t > REQUEST_DEDUP_TTL]
    for h in expired:
        del _recent_requests[h]
    # Hash messages (not full body — ignore temperature/max_tokens changes)
    req_hash = hashlib.md5(json.dumps(messages, ensure_ascii=False).encode()).hexdigest()
    if req_hash in _recent_requests:
        print(f"[dedup] Skipping duplicate request (within {REQUEST_DEDUP_TTL}s)", flush=True)
        return JSONResponse({"choices": [{"message": {"role": "assistant", "content": ""}}], "id": "dedup", "object": "chat.completion"})
    _recent_requests[req_hash] = now

    # Ensure max_tokens is set — reasoning models need room for think + response
    if "max_tokens" not in body:
        body["max_tokens"] = 4096
        print(f"[request] Set max_tokens=4096 (was unset)", flush=True)

    # Auto-learn: detect negative feedback and save lesson (non-blocking)
    async def _safe_auto_learn(msgs, query):
        try:
            await auto_learn_from_feedback(msgs, query)
        except Exception as e:
            print(f"[auto-learn] Error: {e}", flush=True)
    asyncio.create_task(_safe_auto_learn(messages, user_query))

    # Detect farewell — schedule reflection after response
    user_intent = classify_user_intent(user_query)
    is_farewell = user_intent["farewell"]

    # Count user messages for hybrid reflection
    user_msg_count = sum(1 for m in messages if m.get("role") == "user")

    body = await inject_memories(body)

    # Re-detect model periodically (handles hot-swap in LM Studio)
    auto_detect_model()

    # Override model with auto-detected one (client may send stale model name)
    if cfg.llm.model:
        body["model"] = cfg.llm.model

    # BNS: process user mood
    user_mood = detect_mood(user_query) if user_query else None
    if user_mood:
        _bns.process_input_mood(user_mood)

    # BNS: decay chemicals each turn
    _bns.tick()
    _mind_state["bns_state"] = _bns.state.to_dict()

    # Farewell: give Lyume a chance to save what matters to her
    if is_farewell:
        body_messages = body.get("messages", [])
        for i in range(len(body_messages) - 1, -1, -1):
            if body_messages[i].get("role") == "user":
                hint = (
                    "<session_ending>Session is ending. "
                    "Say goodbye warmly.</session_ending>"
                )
                if user_msg_count >= 10:
                    hint = (
                        "<session_ending>Session is ending. This was a long conversation. "
                        "Say goodbye warmly. If you want — offer to do a session reflection.</session_ending>"
                    )
                body_messages.insert(i, {"role": "system", "content": hint})
                break

    stream = body.get("stream", False)

    if stream:
        async def generate():
            think_buf = ""
            in_think = False
            line_buf = ""
            response_parts = []
            last_chunk_template = None

            async with httpx.AsyncClient(timeout=cfg.llm.request_timeout) as client:
                async with client.stream(
                    "POST",
                    f"{LM_STUDIO_URL}/v1/chat/completions",
                    json=body,
                    headers=LM_STUDIO_HEADERS,
                ) as resp:
                    async for line in resp.aiter_lines():
                        if not line.startswith("data: "):
                            yield line + "\n"
                            continue

                        data = line[6:]
                        if data.strip() == "[DONE]":
                            if line_buf and last_chunk_template:
                                visible = strip_markers(line_buf)
                                if visible:
                                    c = {"id": last_chunk_template.get("id", ""), "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {"content": visible}, "finish_reason": None}]}
                                    yield f"data: {json.dumps(c)}\n\n"
                            # Process markers from full response
                            full_response = "".join(response_parts)
                            response_mood = detect_mood(full_response)
                            if response_mood:
                                print(f"[lyume-mood] {response_mood}", flush=True)
                                _mind_state["last_mood"] = response_mood
                                _mind_state["last_mood_time"] = datetime.now(timezone.utc).isoformat()
                            asyncio.create_task(_safe_process_response(full_response, user_query, response_mood))
                            if session_tracker:
                                session_tracker.track_message("assistant", full_response[:500])
                            # Trigger reflection on farewell
                            if is_farewell:
                                print(f"[reflection] Farewell detected, starting session analysis...", flush=True)
                                asyncio.create_task(run_reflection(messages, user_query))
                            yield "data: [DONE]\n\n"
                            break

                        try:
                            chunk = json.loads(data)
                            delta = chunk["choices"][0].get("delta", {})
                            content = delta.get("content", "")

                            if not content:
                                yield line + "\n\n"
                                continue

                            think_buf += content
                            if "<think>" in think_buf and "</think>" not in think_buf:
                                in_think = True
                                continue
                            if in_think and "</think>" in think_buf:
                                think_buf = think_buf.split("</think>", 1)[1]
                                in_think = False

                            if in_think:
                                continue
                            if not think_buf:
                                continue

                            text = think_buf
                            think_buf = ""
                            response_parts.append(text)
                            line_buf += text
                            last_chunk_template = chunk

                            while "\n" in line_buf:
                                complete_line, line_buf = line_buf.split("\n", 1)

                                visible = strip_markers(complete_line)
                                if visible is not None:
                                    out = visible + "\n"
                                    c = {"id": chunk.get("id", ""), "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {"content": out}, "finish_reason": None}]}
                                    yield f"data: {json.dumps(c)}\n\n"

                        except (json.JSONDecodeError, KeyError, IndexError):
                            yield line + "\n\n"

        return StreamingResponse(generate(), media_type="text/event-stream")
    else:
        async with httpx.AsyncClient(timeout=cfg.llm.request_timeout) as client:
            resp = await client.post(
                f"{LM_STUDIO_URL}/v1/chat/completions",
                json=body,
                headers=LM_STUDIO_HEADERS,
            )
        result = resp.json()

        full_response = ""
        for choice in result.get("choices", []):
            msg = choice.get("message", {})
            if msg.get("content"):
                raw = msg["content"]
                full_response += raw
                response_mood = detect_mood(raw)
                if response_mood:
                    print(f"[lyume-mood] {response_mood}", flush=True)
                    _mind_state["last_mood"] = response_mood
                    _mind_state["last_mood_time"] = datetime.now(timezone.utc).isoformat()
                asyncio.create_task(_safe_process_response(raw, user_query, response_mood))
                msg["content"] = strip_markers(strip_think_tags(raw))
        if session_tracker:
            session_tracker.track_message("assistant", full_response[:500])

        # Trigger reflection on farewell
        if is_farewell:
            print(f"[reflection] Farewell detected, starting session analysis...", flush=True)
            asyncio.create_task(run_reflection(messages, user_query))

        return JSONResponse(result)


# Pass through other endpoints
@app.api_route("/v1/{path:path}", methods=["GET", "POST"])
async def proxy_passthrough(request: Request, path: str):
    body = await request.body()
    headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in ("host", "content-length")
    }
    # Ensure auth header is set for LM Studio
    if LM_STUDIO_API_KEY and "authorization" not in {k.lower() for k in headers}:
        headers["Authorization"] = f"Bearer {LM_STUDIO_API_KEY}"

    # For responses endpoint: convert to completions API
    if path == "responses" and request.method == "POST":
        try:
            data = json.loads(body)
            print(f"[proxy] Converting responses API → completions API", flush=True)

            # Extract instructions → system message
            messages = []
            instructions = data.get("instructions", "")
            if instructions:
                messages.append({"role": "system", "content": instructions})

            # Extract input → user/assistant messages
            input_data = data.get("input", "")
            if isinstance(input_data, str):
                messages.append({"role": "user", "content": input_data})
            elif isinstance(input_data, list):
                for item in input_data:
                    if isinstance(item, str):
                        messages.append({"role": "user", "content": item})
                    elif isinstance(item, dict) and item.get("type") == "message":
                        role = item.get("role", "user")
                        content = item.get("content", "")
                        if isinstance(content, list):
                            text_parts = [c.get("text", "") for c in content
                                          if isinstance(c, dict) and c.get("type") == "input_text"]
                            content = " ".join(text_parts)
                        if content:
                            messages.append({"role": role, "content": content})

            if not messages:
                print(f"[proxy] responses→completions: no messages extracted", flush=True)
            else:
                # Build completions request
                comp_body = {
                    "model": data.get("model", ""),
                    "messages": messages,
                    "stream": data.get("stream", False),
                    "max_tokens": data.get("max_tokens") or data.get("max_output_tokens") or 4096,
                }
                if data.get("temperature") is not None:
                    comp_body["temperature"] = data["temperature"]

                # Reuse the full chat_completions pipeline (memory injection, markers, etc.)
                from starlette.requests import Request as StarletteRequest
                # Forward as completions
                comp_body_bytes = json.dumps(comp_body).encode()

                # Inject memories
                comp_body = await inject_memories(comp_body)
                if cfg.llm.model:
                    comp_body["model"] = cfg.llm.model

                stream = comp_body.get("stream", False)
                if stream:
                    async def stream_converted():
                        async with httpx.AsyncClient(timeout=cfg.llm.request_timeout) as client:
                            async with client.stream(
                                "POST",
                                f"{LM_STUDIO_URL}/v1/chat/completions",
                                json=comp_body,
                                headers=LM_STUDIO_HEADERS,
                            ) as resp:
                                async for chunk in resp.aiter_bytes():
                                    yield chunk
                    return StreamingResponse(stream_converted(), media_type="text/event-stream")
                else:
                    async with httpx.AsyncClient(timeout=cfg.llm.request_timeout) as client:
                        resp = await client.post(
                            f"{LM_STUDIO_URL}/v1/chat/completions",
                            json=comp_body,
                            headers=LM_STUDIO_HEADERS,
                        )
                    return JSONResponse(resp.json())
        except (json.JSONDecodeError, Exception) as e:
            print(f"[proxy] responses→completions error: {e}", flush=True)

    async with httpx.AsyncClient(timeout=cfg.llm.request_timeout) as client:
        resp = await client.request(
            method=request.method,
            url=f"{LM_STUDIO_URL}/v1/{path}",
            content=body,
            headers=headers,
        )
        try:
            return JSONResponse(resp.json(), status_code=resp.status_code)
        except Exception:
            from starlette.responses import Response
            return Response(content=resp.content, status_code=resp.status_code,
                           media_type=resp.headers.get("content-type"))


@app.get("/health")
async def health_check():
    """Module health for Lyume Status Dashboard."""
    modules = {}

    # Mood parser
    try:
        r = detect_mood("I love this!")
        modules["mood_parser"] = {"status": "OK", "detail": f"test -> {r or 'neutral'}"}
    except Exception as e:
        modules["mood_parser"] = {"status": "ERROR", "error": str(e)[:60]}

    # Memory engine
    try:
        assert mm.pool is not None, "DB pool not initialized"
        stats = await mm.stats()
        modules["memory_engine"] = {"status": "OK", "detail": f"{stats.get('total', 0)} memories"}
    except Exception as e:
        modules["memory_engine"] = {"status": "ERROR", "error": str(e)[:60]}

    # Lesson / intuition
    try:
        count = await mm.lesson_stats()
        modules["lesson_engine"] = {"status": "OK", "detail": f"{count} active lessons"}
    except Exception as e:
        modules["lesson_engine"] = {"status": "ERROR", "error": str(e)[:60]}

    # Marker processing
    try:
        assert MARKER_PATTERN is not None
        assert SOFT_SAVE_PATTERN is not None
        assert SOFT_LESSON_PATTERN is not None
        modules["marker_processing"] = {"status": "OK", "detail": "patterns compiled"}
    except Exception as e:
        modules["marker_processing"] = {"status": "ERROR", "error": str(e)[:60]}

    # Auto-learn
    try:
        assert callable(auto_learn_from_feedback)
        modules["auto_learn"] = {"status": "OK"}
    except Exception as e:
        modules["auto_learn"] = {"status": "ERROR", "error": str(e)[:60]}

    # Proactive
    try:
        assert PROACTIVE_HIGH_SIM > 0
        assert PROACTIVE_EMOTIONAL_KEYWORDS is not None
        modules["proactive"] = {"status": "OK", "detail": f"sim>{PROACTIVE_HIGH_SIM}"}
    except Exception as e:
        modules["proactive"] = {"status": "ERROR", "error": str(e)[:60]}

    # Session tracker
    if session_tracker:
        modules["session_tracker"] = {
            "status": "OK",
            "detail": f"buffer={len(session_tracker._buffer)}, msgs={session_tracker._user_msg_count}",
        }

    all_ok = all(m["status"] == "OK" for m in modules.values())
    return {
        "status": "healthy" if all_ok else "degraded",
        "modules": modules,
        "mind_state": {
            **_mind_state,
            "session_topics": _session_topics[-5:],
            "topics_count": len(_session_topics),
        },
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=cfg.server.host, port=cfg.server.port, log_level=cfg.server.log_level)
