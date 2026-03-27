#!/usr/bin/env python3
"""
Lyume ASCII Status Dashboard — v3
Interactive operational tool: status + memory/lesson management.
"""

import argparse
import asyncio
import json as json_lib
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

# Ensure workspace imports work
WORKSPACE = Path(__file__).parent
LYUME_PY = Path.home() / ".openclaw/workspace-lyume/python"
for p in (str(WORKSPACE), str(LYUME_PY)):
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from memory_manager import MemoryManager, EMBED_MODEL_PATH, get_embed_model
except ImportError as e:
    print(f"\033[91m✗ memory_manager import failed: {e}\033[0m")
    sys.exit(2)

import httpx

from config import cfg


# ── Config ──

LM_STUDIO_URL    = cfg.llm.url
MEMORY_PROXY_URL = f"http://{cfg.server.host}:{cfg.server.port}"
LM_STUDIO_API_KEY = getattr(cfg.llm, "api_key", "")
STATUS_TIMEOUT   = float(os.environ.get("STATUS_TIMEOUT", "3"))
EDITOR           = os.environ.get("EDITOR", "nano")
VERBOSE          = False  # set by --verbose flag
mm_ref           = None   # reference to MemoryManager for verbose DB pool info


# ── Status levels ──

class Status:
    ONLINE   = "ONLINE"
    DEGRADED = "DEGRADED"
    OFFLINE  = "OFFLINE"
    ERROR    = "ERROR"
    LOADING  = "LOADING"


# ── ANSI ──

class C:
    RST = "\033[0m"
    G   = "\033[92m"
    R   = "\033[91m"
    Y   = "\033[93m"
    B   = "\033[94m"
    CY  = "\033[96m"
    DIM = "\033[2m"
    BD  = "\033[1m"
    UL  = "\033[4m"

    @classmethod
    def disable(cls):
        for attr in ("RST", "G", "R", "Y", "B", "CY", "DIM", "BD", "UL"):
            setattr(cls, attr, "")


def _vlen(s: str) -> int:
    return len(re.sub(r"\033\[[0-9;]*m", "", s))


def _clear():
    print("\x1b[2J\x1b[H", end="", flush=True)


def _status_color(status: str) -> str:
    return {
        Status.ONLINE: C.G, Status.DEGRADED: C.Y,
        Status.LOADING: C.Y, Status.OFFLINE: C.R, Status.ERROR: C.R,
    }.get(status, C.DIM)


def _health_color(label: str) -> str:
    return {"READY": C.G, "DEGRADED": C.Y, "PARTIAL": C.Y, "BROKEN": C.R}.get(label, C.DIM)


# ── Box drawing ──

W = 60

def _row(text: str) -> str:
    pad = W - 2 - _vlen(text)
    return f"║ {text}{' ' * max(0, pad)} ║"

def _row_empty():
    return f"║{' ' * W}║"

def _section(title: str) -> str:
    t = f" {title} "
    side = (W - len(t)) // 2
    rem = W - side - len(t)
    return f"╟{'─' * side}{C.BD}{C.CY}{t}{C.RST}{'─' * rem}╢"

def _box_top():
    return f"╔{'═' * W}╗"

def _box_bottom():
    return f"╚{'═' * W}╝"


# ── ServiceResult ──

class ServiceResult:
    __slots__ = ("name", "status", "detail", "latency_ms", "error", "traceback")
    def __init__(self, name, status, detail="", latency_ms=0, error="", traceback=""):
        self.name, self.status, self.detail = name, status, detail
        self.latency_ms, self.error, self.traceback = latency_ms, error, traceback

    def to_dict(self):
        d = {"name": self.name, "status": self.status, "latency_ms": round(self.latency_ms, 1)}
        if self.detail: d["detail"] = self.detail
        if self.error:  d["error"] = self.error
        if self.traceback and VERBOSE: d["traceback"] = self.traceback
        return d


# ── Checks ──

import traceback as _tb


def _capture_tb() -> str:
    """Capture traceback string for verbose mode."""
    return _tb.format_exc()


async def check_http(url: str, name: str) -> ServiceResult:
    t0 = time.monotonic()
    try:
        headers = {"Authorization": f"Bearer {LM_STUDIO_API_KEY}"} if "1234" in url else {}
        async with httpx.AsyncClient(timeout=STATUS_TIMEOUT) as client:
            r = await client.get(f"{url}/v1/models", headers=headers)
            ms = (time.monotonic() - t0) * 1000
            if r.status_code == 200:
                models = r.json().get("data", [])
                model_id = models[0].get("id", "") if models else ""
                st = Status.DEGRADED if ms > 1000 else Status.ONLINE
                return ServiceResult(name, st, model_id, ms)
            return ServiceResult(name, Status.ERROR, f"HTTP {r.status_code}", ms)
    except httpx.ConnectError:
        return ServiceResult(name, Status.OFFLINE, "", (time.monotonic()-t0)*1000,
                             "connection refused", _capture_tb())
    except httpx.TimeoutException:
        return ServiceResult(name, Status.OFFLINE, "", (time.monotonic()-t0)*1000,
                             f"timeout ({STATUS_TIMEOUT}s)", _capture_tb())
    except Exception as e:
        return ServiceResult(name, Status.ERROR, "", (time.monotonic()-t0)*1000,
                             str(e)[:40], _capture_tb())


async def check_embedding() -> ServiceResult:
    t0 = time.monotonic()
    try:
        if not Path(EMBED_MODEL_PATH).exists():
            return ServiceResult("Embedding", Status.ERROR, "", 0,
                                 f"file missing: {Path(EMBED_MODEL_PATH).name}")
        model = get_embed_model()
        ms = (time.monotonic() - t0) * 1000
        st = Status.DEGRADED if ms > 2000 else Status.ONLINE
        return ServiceResult("Embedding", st, "Loaded", ms) if model else \
               ServiceResult("Embedding", Status.ERROR, "Not loaded", ms)
    except Exception as e:
        return ServiceResult("Embedding", Status.ERROR, "", (time.monotonic()-t0)*1000,
                             str(e)[:40], _capture_tb())


async def check_postgres(mm: MemoryManager) -> ServiceResult:
    t0 = time.monotonic()
    try:
        await mm.connect()
        ms = (time.monotonic() - t0) * 1000
        st = Status.DEGRADED if ms > 500 else Status.ONLINE
        return ServiceResult("PostgreSQL", st, "Connected", ms)
    except Exception as e:
        return ServiceResult("PostgreSQL", Status.OFFLINE, "", (time.monotonic()-t0)*1000,
                             str(e)[:40], _capture_tb())


# ── Module health ──

MODULE_LABELS = {
    "mood_parser": "Mood Parser",
    "memory_engine": "Memory Engine",
    "lesson_engine": "Lesson Engine",
    "marker_processing": "Markers",
    "auto_learn": "Auto-learn",
    "proactive": "Proactive",
}

async def check_modules() -> dict:
    """Fetch module health from proxy /health endpoint."""
    try:
        async with httpx.AsyncClient(timeout=STATUS_TIMEOUT) as client:
            r = await client.get(f"{MEMORY_PROXY_URL}/health")
            if r.status_code == 200:
                return r.json()
    except Exception:
        pass
    return {}


# ── Readiness checks ──

class ReadinessCheck:
    __slots__ = ("name", "ok", "detail")
    def __init__(self, name: str, ok: bool, detail: str = ""):
        self.name, self.ok, self.detail = name, ok, detail


async def run_readiness(mm: MemoryManager) -> list[ReadinessCheck]:
    checks = []

    # 1. venv
    in_venv = sys.prefix != sys.base_prefix
    checks.append(ReadinessCheck("venv", in_venv,
                                 "active" if in_venv else "not in virtualenv"))

    # 2. imports
    try:
        import asyncpg, httpx as _hx, llama_cpp  # noqa: F401
        checks.append(ReadinessCheck("imports", True, "asyncpg, httpx, llama_cpp"))
    except ImportError as e:
        checks.append(ReadinessCheck("imports", False, str(e)[:40]))

    # 3. DB reachable
    try:
        await mm.connect()
        checks.append(ReadinessCheck("database", True, "PostgreSQL connected"))
    except Exception as e:
        checks.append(ReadinessCheck("database", False, str(e)[:40]))

    # 4. Model file
    exists = Path(EMBED_MODEL_PATH).exists()
    fname = Path(EMBED_MODEL_PATH).name
    checks.append(ReadinessCheck("model_file", exists,
                                 fname if exists else "file not found"))

    # 5. Embedding loads
    try:
        model = get_embed_model()
        checks.append(ReadinessCheck("embedding", model is not None,
                                     "loaded" if model else "returned None"))
    except Exception as e:
        checks.append(ReadinessCheck("embedding", False, str(e)[:40]))

    # 6. LM Studio reachable
    try:
        lm_headers = {"Authorization": f"Bearer {LM_STUDIO_API_KEY}"}
        async with httpx.AsyncClient(timeout=STATUS_TIMEOUT) as client:
            r = await client.get(f"{LM_STUDIO_URL}/v1/models", headers=lm_headers)
            checks.append(ReadinessCheck("lm_studio", r.status_code == 200,
                                         "reachable" if r.status_code == 200 else f"HTTP {r.status_code}"))
    except Exception:
        checks.append(ReadinessCheck("lm_studio", False, "unreachable"))

    # 7. Proxy reachable
    try:
        async with httpx.AsyncClient(timeout=STATUS_TIMEOUT) as client:
            r = await client.get(f"{MEMORY_PROXY_URL}/health")
            checks.append(ReadinessCheck("proxy", r.status_code == 200,
                                         "reachable" if r.status_code == 200 else f"HTTP {r.status_code}"))
    except Exception:
        checks.append(ReadinessCheck("proxy", False, "unreachable"))

    return checks


READINESS_LABELS = {
    "venv": "Virtual Env",
    "imports": "Imports",
    "database": "PostgreSQL",
    "model_file": "Model File",
    "embedding": "Embedding",
    "lm_studio": "LM Studio",
    "proxy": "Proxy",
}


def render_readiness(checks: list[ReadinessCheck]) -> str:
    all_ok = all(c.ok for c in checks)
    lines = []
    lines.append(_section("Readiness"))
    lines.append(_row_empty())
    for c in checks:
        label = READINESS_LABELS.get(c.name, c.name)
        if c.ok:
            mark = f"{C.G}OK{C.RST}"
        else:
            mark = f"{C.R}FAIL{C.RST}"
        detail = f"  {C.DIM}{c.detail}{C.RST}" if c.detail else ""
        lines.append(_row(f"  [{mark}]  {label:<14s}{detail}"))
    lines.append(_row_empty())
    return "\n".join(lines), all_ok


# ── Data collection ──

async def get_memory_info(mm: MemoryManager) -> dict:
    info = {"active": 0, "archived": 0, "total": 0, "lessons": 0,
            "last_memory": None, "last_lesson": None, "last_recall": None}
    try:
        stats = await mm.stats()
        info.update(stats)
        info["lessons"] = await mm.lesson_stats()
        row = await mm.pool.fetchrow(
            "SELECT max(last_updated) AS lw, max(last_accessed) AS lr FROM memories_semantic")
        if row:
            info["last_memory"] = row["lw"]
            info["last_recall"] = row["lr"]
        row2 = await mm.pool.fetchrow("SELECT max(created_at) AS lc FROM lessons")
        if row2:
            info["last_lesson"] = row2["lc"]
    except Exception:
        pass
    return info


async def get_model_info() -> dict:
    info = {"id": "—", "context_length": None}
    try:
        lm_headers = {"Authorization": f"Bearer {LM_STUDIO_API_KEY}"}
        async with httpx.AsyncClient(timeout=STATUS_TIMEOUT) as client:
            r = await client.get(f"{LM_STUDIO_URL}/v1/models", headers=lm_headers)
            if r.status_code == 200:
                models = r.json().get("data", [])
                if models:
                    m = models[0]
                    info["id"] = m.get("id", "—")
                    info["context_length"] = m.get("context_length") or m.get("max_model_len")
    except Exception:
        pass
    return info


def compute_health(services):
    weights = {"LM Studio": 35, "Memory Proxy": 25, "PostgreSQL": 25, "Embedding": 15}
    score = 0
    for svc in services:
        w = weights.get(svc.name, 10)
        if svc.status == Status.ONLINE: score += w
        elif svc.status == Status.DEGRADED: score += w * 0.6
        elif svc.status == Status.LOADING: score += w * 0.3
    score = int(score)
    if score >= 90: label = "READY"
    elif score >= 60: label = "DEGRADED"
    elif score >= 30: label = "PARTIAL"
    else: label = "BROKEN"
    return score, label


async def collect(mm, with_readiness=False):
    t0 = time.monotonic()
    lm, proxy, embed, pg = await asyncio.gather(
        check_http(LM_STUDIO_URL, "LM Studio"),
        check_http(MEMORY_PROXY_URL, "Memory Proxy"),
        check_embedding(),
        check_postgres(mm),
    )
    services = [lm, proxy, embed, pg]
    mem_info = await get_memory_info(mm)
    model_info = await get_model_info() if lm.status != Status.OFFLINE else {"id": "—"}
    modules = await check_modules() if proxy.status != Status.OFFLINE else {}
    readiness = await run_readiness(mm) if with_readiness else []
    collect_ms = (time.monotonic() - t0) * 1000
    return services, mem_info, model_info, modules, readiness, collect_ms


# ── Time formatting ──

def _fmt_ts(dt):
    if dt is None: return "—"
    if hasattr(dt, "astimezone"):
        return dt.astimezone().strftime("%H:%M:%S")
    return str(dt)

def _fmt_ago(dt):
    if dt is None: return ""
    now = datetime.now(timezone.utc)
    if hasattr(dt, "tzinfo") and dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    secs = int((now - dt).total_seconds())
    if secs < 60: return f"{secs}s ago"
    elif secs < 3600: return f"{secs//60}m ago"
    elif secs < 86400: return f"{secs//3600}h ago"
    else: return f"{secs//86400}d ago"

def _fmt_ms(ms):
    if ms < 1: return "<1ms"
    elif ms < 1000: return f"{ms:.0f}ms"
    else: return f"{ms/1000:.1f}s"


# ── Render status dashboard ──

# ── Hints engine ──

def generate_hints(services, mem_info, modules, readiness) -> list[str]:
    """Generate contextual hints based on collected data."""
    hints = []

    # Service latency hints
    for svc in services:
        if svc.status == Status.ONLINE and svc.latency_ms > 500:
            hints.append(f"{C.Y}{svc.name} latency {_fmt_ms(svc.latency_ms)}{C.RST}"
                         f" {C.DIM}-- можливо VRAM перевантажена{C.RST}")
        if svc.status == Status.DEGRADED:
            hints.append(f"{C.Y}{svc.name} DEGRADED{C.RST}"
                         f" {C.DIM}-- працює, але повільно{C.RST}")

    # Embedding slow init (> 2s is normal on first load)
    for svc in services:
        if svc.name == "Embedding" and svc.latency_ms > 2000 and svc.status == Status.ONLINE:
            hints.append(f"{C.DIM}Embedding init > 2s -- норма при першому запуску{C.RST}")

    # Memory hints
    active = mem_info.get("active", 0)
    total = mem_info.get("total", 0)
    lessons = mem_info.get("lessons", 0)
    archived = mem_info.get("archived", 0)

    if total == 0:
        hints.append(f"{C.R}0 memories{C.RST} {C.DIM}-- база порожня{C.RST}")
    if lessons == 0:
        hints.append(f"{C.Y}0 active lessons{C.RST} {C.DIM}-- перевір seed або створи вручну{C.RST}")
    if archived > active * 3 and active > 0:
        hints.append(f"{C.DIM}Archived ({archived}) >> Active ({active}) -- можливо варто почистити{C.RST}")

    # Last activity hints
    last_mem = mem_info.get("last_memory")
    last_recall = mem_info.get("last_recall")
    if last_mem:
        now = datetime.now(timezone.utc)
        if hasattr(last_mem, "tzinfo") and last_mem.tzinfo is None:
            last_mem = last_mem.replace(tzinfo=timezone.utc)
        hours_ago = (now - last_mem).total_seconds() / 3600
        if hours_ago > 24:
            hints.append(f"{C.Y}Last save {int(hours_ago)}h ago{C.RST}"
                         f" {C.DIM}-- Lyume давно нічого не запамʼятала{C.RST}")
    if last_recall is None and total > 0:
        hints.append(f"{C.DIM}Жодного recall -- памʼять не використовується?{C.RST}")

    # Module hints
    mods = modules.get("modules", {})
    failed_mods = [k for k, v in mods.items() if v.get("status") != "OK"]
    if failed_mods:
        names = ", ".join(MODULE_LABELS.get(m, m) for m in failed_mods)
        hints.append(f"{C.R}Modules з помилками: {names}{C.RST}")

    # Readiness hints
    if readiness:
        failed_r = [c for c in readiness if not c.ok]
        if len(failed_r) == 1:
            c = failed_r[0]
            label = READINESS_LABELS.get(c.name, c.name)
            hints.append(f"{C.Y}{label} FAIL{C.RST} {C.DIM}-- {c.detail}{C.RST}")
        elif len(failed_r) > 1:
            hints.append(f"{C.R}{len(failed_r)} readiness checks failed{C.RST}"
                         f" {C.DIM}-- дивись блок Readiness{C.RST}")

    # All green
    if not hints:
        hints.append(f"{C.G}Все працює штатно{C.RST}")

    return hints


def render_status(services, mem_info, model_info, modules, readiness, health_score, health_label, collect_ms):
    now_str = datetime.now().strftime("%H:%M:%S")
    L = []
    L.append(_box_top())
    L.append(_row_empty())
    L.append(_row(f"{C.BD}— Lyume —{C.RST}"))
    hc = _health_color(health_label)
    L.append(_row(f"Health: {hc}{health_label} ({health_score}%){C.RST}    {C.DIM}{now_str}  ({_fmt_ms(collect_ms)}){C.RST}"))
    L.append(_row_empty())

    # Services
    L.append(_section("Services"))
    L.append(_row_empty())
    for svc in services:
        sc = _status_color(svc.status)
        dot = f"{sc}●{C.RST}"
        st = f"{sc}{svc.status}{C.RST}"
        det = f" — {svc.detail}" if svc.detail else ""
        lat = f"{C.DIM}{_fmt_ms(svc.latency_ms):>6s}{C.RST}"
        L.append(_row(f"  {dot} {svc.name:<14s} {st}{det}  {lat}"))
    L.append(_row_empty())

    # Modules
    mods = modules.get("modules", {})
    if mods:
        L.append(_section("Modules"))
        L.append(_row_empty())
        for key, info in mods.items():
            label = MODULE_LABELS.get(key, key)
            st = info.get("status", "?")
            if st == "OK":
                dot = f"{C.G}●{C.RST}"
                detail = info.get("detail", "")
                txt = f"{C.G}OK{C.RST}" + (f"  {C.DIM}{detail}{C.RST}" if detail else "")
            else:
                dot = f"{C.R}●{C.RST}"
                err = info.get("error", "unknown")
                txt = f"{C.R}ERROR — {err}{C.RST}"
            L.append(_row(f"  {dot} {label:<16s} {txt}"))
        L.append(_row_empty())

    # Model
    if model_info.get("id", "—") != "—":
        L.append(_section("Model"))
        L.append(_row_empty())
        L.append(_row(f"  {C.CY}{model_info['id']}{C.RST}"))
        if model_info.get("context_length"):
            L.append(_row(f"  Context: {model_info['context_length']:,}"))
        L.append(_row_empty())

    # Memory
    L.append(_section("Memory"))
    L.append(_row_empty())
    a, ar, t, les = mem_info.get("active",0), mem_info.get("archived",0), mem_info.get("total",0), mem_info.get("lessons",0)
    L.append(_row(f"  Active    {C.G}{a:>6,}{C.RST}    Lessons  {C.Y}{les:>5,}{C.RST}"))
    L.append(_row(f"  Archived  {C.DIM}{ar:>6,}{C.RST}    Total    {C.BD}{t:>5,}{C.RST}"))
    L.append(_row_empty())

    # Activity
    lm, lr, ll = mem_info.get("last_memory"), mem_info.get("last_recall"), mem_info.get("last_lesson")
    if any([lm, lr, ll]):
        L.append(_section("Activity"))
        L.append(_row_empty())
        if lm: L.append(_row(f"  Last save    {_fmt_ts(lm)}  {C.DIM}{_fmt_ago(lm)}{C.RST}"))
        if lr: L.append(_row(f"  Last recall  {_fmt_ts(lr)}  {C.DIM}{_fmt_ago(lr)}{C.RST}"))
        if ll: L.append(_row(f"  Last lesson  {_fmt_ts(ll)}  {C.DIM}{_fmt_ago(ll)}{C.RST}"))
        L.append(_row_empty())

    # Readiness (show only if something failed, or always in verbose)
    if readiness:
        show_readiness = VERBOSE or any(not c.ok for c in readiness)
        if show_readiness:
            rblock, _ = render_readiness(readiness)
            L.append(rblock)

    # Errors
    errors = [s for s in services if s.error]
    if errors:
        L.append(_section("Errors"))
        L.append(_row_empty())
        for s in errors:
            L.append(_row(f"  {C.R}{s.name}: {s.error}{C.RST}"))
        L.append(_row_empty())

    # Hints
    hints = generate_hints(services, mem_info, modules, readiness)
    if hints:
        L.append(_section("Hints"))
        L.append(_row_empty())
        for hint in hints:
            L.append(_row(f"  {hint}"))
        L.append(_row_empty())

    # Verbose: config + details + tracebacks
    if VERBOSE:
        L.append(_section("Config"))
        L.append(_row_empty())
        L.append(_row(f"  {C.DIM}LM Studio:{C.RST}    {LM_STUDIO_URL}"))
        L.append(_row(f"  {C.DIM}Proxy:{C.RST}        {MEMORY_PROXY_URL}"))
        L.append(_row(f"  {C.DIM}Timeout:{C.RST}      {STATUS_TIMEOUT}s"))
        L.append(_row(f"  {C.DIM}Editor:{C.RST}       {EDITOR}"))
        L.append(_row(f"  {C.DIM}Embed model:{C.RST}  {Path(EMBED_MODEL_PATH).name}"))
        L.append(_row(f"  {C.DIM}Python:{C.RST}       {sys.executable}"))
        in_venv = sys.prefix != sys.base_prefix
        L.append(_row(f"  {C.DIM}Venv:{C.RST}         {'yes' if in_venv else 'no'} ({sys.prefix})"))
        L.append(_row_empty())

        # DB pool info
        try:
            pool = mm_ref.pool if mm_ref and mm_ref.pool else None
            if pool:
                L.append(_section("DB Pool"))
                L.append(_row_empty())
                L.append(_row(f"  {C.DIM}Min size:{C.RST}  {pool.get_min_size()}"))
                L.append(_row(f"  {C.DIM}Max size:{C.RST}  {pool.get_max_size()}"))
                L.append(_row(f"  {C.DIM}Current:{C.RST}   {pool.get_size()}"))
                L.append(_row(f"  {C.DIM}Free:{C.RST}      {pool.get_idle_size()}"))
                L.append(_row_empty())
        except Exception:
            pass

        # Tracebacks
        tb_services = [s for s in services if s.traceback and s.error]
        if tb_services:
            L.append(_section("Tracebacks"))
            L.append(_row_empty())
            for s in tb_services:
                L.append(_row(f"  {C.R}{C.BD}{s.name}{C.RST}"))
                for line in s.traceback.strip().split("\n")[-6:]:
                    truncated = line[:W - 4] if len(line) > W - 4 else line
                    L.append(_row(f"  {C.DIM}{truncated}{C.RST}"))
                L.append(_row_empty())

    L.append(_box_bottom())

    online = sum(1 for s in services if s.status in (Status.ONLINE, Status.DEGRADED))
    total = len(services)
    sc = C.G if online == total else (C.Y if online >= 2 else C.R)
    L.append(f"\n  {sc}{online}/{total} services{C.RST}  {C.DIM}│{C.RST}  {t:,} memories  {C.DIM}│{C.RST}  {les} lessons")
    return "\n".join(L)


# ── Editor helper ──

def edit_in_editor(text: str, suffix=".md") -> str | None:
    """Open text in $EDITOR, return edited content or None if unchanged/cancelled."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False) as f:
        f.write(text)
        f.flush()
        path = f.name
    try:
        ret = subprocess.call([EDITOR, path])
        if ret != 0:
            return None
        with open(path) as f:
            new_text = f.read()
        return new_text if new_text.strip() != text.strip() else None
    finally:
        os.unlink(path)


# ── Interactive: Memory management ──

async def memory_menu(mm: MemoryManager):
    while True:
        _clear()
        print(f"\n  {C.BD}{C.CY}Memory Management{C.RST}\n")
        print(f"  {C.BD}[l]{C.RST} List memories     {C.BD}[s]{C.RST} Search")
        print(f"  {C.BD}[a]{C.RST} List archived     {C.BD}[n]{C.RST} New memory")
        print(f"  {C.BD}[q]{C.RST} Back\n")

        choice = input(f"  {C.DIM}>{C.RST} ").strip().lower()

        if choice == "q":
            return
        elif choice == "l":
            await memory_list(mm, include_archived=False)
        elif choice == "a":
            await memory_list(mm, include_archived=True)
        elif choice == "s":
            await memory_search(mm)
        elif choice == "n":
            await memory_create(mm)


async def memory_list(mm: MemoryManager, include_archived=False):
    memories = await mm.list_semantic(limit=50, include_archived=include_archived)
    if not memories:
        print(f"\n  {C.DIM}Порожньо.{C.RST}")
        input(f"\n  {C.DIM}Enter...{C.RST}")
        return

    while True:
        _clear()
        label = "All Memories" if include_archived else "Active Memories"
        print(f"\n  {C.BD}{label}{C.RST}  ({len(memories)})\n")
        for i, m in enumerate(memories):
            arch = f" {C.DIM}[archived]{C.RST}" if m.get("archived") else ""
            cat = f"{C.DIM}{m['category']}{C.RST}"
            name = m.get("concept_name") or m["content"][:40]
            print(f"  {C.Y}{i+1:>3}{C.RST}  {name:<40s}  {cat}{arch}")

        print(f"\n  {C.DIM}Номер для деталей, [q] назад{C.RST}")
        choice = input(f"  {C.DIM}>{C.RST} ").strip()
        if choice == "q":
            return
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(memories):
                await memory_detail(mm, memories[idx])
                # Refresh list
                memories = await mm.list_semantic(limit=50, include_archived=include_archived)
        except ValueError:
            pass


async def memory_detail(mm: MemoryManager, mem: dict):
    while True:
        _clear()
        mid = mem["id"]
        print(f"\n  {C.BD}{C.CY}Memory{C.RST}  {C.DIM}{mid}{C.RST}\n")
        print(f"  {C.BD}Name:{C.RST}     {mem.get('concept_name', '—')}")
        print(f"  {C.BD}Category:{C.RST} {mem['category']}")
        print(f"  {C.BD}Keywords:{C.RST} {', '.join(mem.get('keywords') or [])}")
        print(f"  {C.BD}Archived:{C.RST} {'Yes' if mem.get('archived') else 'No'}")
        print(f"  {C.BD}Accessed:{C.RST} {mem.get('access_count', 0)}x")
        print(f"\n  {C.BD}Content:{C.RST}")
        for line in mem["content"].split("\n"):
            print(f"    {line}")

        print(f"\n  {C.BD}[e]{C.RST} Edit  {C.BD}[a]{C.RST} Archive/Unarchive  {C.BD}[d]{C.RST} Delete  {C.BD}[q]{C.RST} Back")
        choice = input(f"\n  {C.DIM}>{C.RST} ").strip().lower()

        if choice == "q":
            return
        elif choice == "e":
            new_content = edit_in_editor(mem["content"])
            if new_content:
                ok = await mm.update_semantic(mid, new_content.strip())
                if ok:
                    mem["content"] = new_content.strip()
                    print(f"\n  {C.G}Збережено.{C.RST}")
                else:
                    print(f"\n  {C.R}Помилка збереження.{C.RST}")
                input(f"  {C.DIM}Enter...{C.RST}")
        elif choice == "a":
            if mem.get("archived"):
                ok = await mm.unarchive(mid)
                if ok:
                    mem["archived"] = False
                    print(f"\n  {C.G}Відновлено.{C.RST}")
            else:
                ok = await mm.archive_semantic(mid)
                if ok:
                    mem["archived"] = True
                    print(f"\n  {C.Y}Заархівовано.{C.RST}")
            input(f"  {C.DIM}Enter...{C.RST}")
        elif choice == "d":
            confirm = input(f"\n  {C.R}Видалити назавжди? [y/N]{C.RST} ").strip().lower()
            if confirm == "y":
                ok = await mm.delete_semantic(mid)
                if ok:
                    print(f"\n  {C.R}Видалено.{C.RST}")
                    input(f"  {C.DIM}Enter...{C.RST}")
                    return
            else:
                print(f"  {C.DIM}Скасовано.{C.RST}")
                input(f"  {C.DIM}Enter...{C.RST}")


async def memory_search(mm: MemoryManager):
    _clear()
    print(f"\n  {C.BD}Memory Search{C.RST}\n")
    query = input(f"  Запит: ").strip()
    if not query:
        return
    results = await mm.search_semantic(query, limit=10, threshold=0.2)
    if not results:
        print(f"\n  {C.DIM}Нічого не знайдено.{C.RST}")
        input(f"\n  {C.DIM}Enter...{C.RST}")
        return

    print(f"\n  {C.G}Знайдено: {len(results)}{C.RST}\n")
    for i, m in enumerate(results):
        sim = m.get("similarity", 0)
        name = m.get("concept_name") or m["content"][:40]
        print(f"  {C.Y}{i+1:>3}{C.RST}  {sim:.0%}  {name}")

    print(f"\n  {C.DIM}Номер для деталей, [q] назад{C.RST}")
    choice = input(f"  {C.DIM}>{C.RST} ").strip()
    if choice == "q":
        return
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(results):
            await memory_detail(mm, results[idx])
    except ValueError:
        pass


async def memory_create(mm: MemoryManager):
    _clear()
    print(f"\n  {C.BD}New Memory{C.RST}\n")
    concept = input(f"  Назва: ").strip()
    category = input(f"  Категорія {C.DIM}[general]{C.RST}: ").strip() or "general"
    print(f"\n  {C.DIM}Відкриваю редактор...{C.RST}")
    content = edit_in_editor("", suffix=".md")
    if not content or not content.strip():
        print(f"  {C.DIM}Скасовано.{C.RST}")
        input(f"  {C.DIM}Enter...{C.RST}")
        return

    mid = await mm.save_semantic(content.strip(), concept_name=concept, category=category)
    print(f"\n  {C.G}Збережено: {mid}{C.RST}")
    input(f"  {C.DIM}Enter...{C.RST}")


# ── Interactive: Lesson management ──

async def lesson_menu(mm: MemoryManager):
    while True:
        _clear()
        print(f"\n  {C.BD}{C.CY}Lesson Management{C.RST}\n")
        print(f"  {C.BD}[l]{C.RST} Active lessons    {C.BD}[s]{C.RST} Search")
        print(f"  {C.BD}[a]{C.RST} All lessons       {C.BD}[n]{C.RST} New lesson")
        print(f"  {C.BD}[q]{C.RST} Back\n")

        choice = input(f"  {C.DIM}>{C.RST} ").strip().lower()

        if choice == "q":
            return
        elif choice == "l":
            await lesson_list(mm, active_only=True)
        elif choice == "a":
            await lesson_list(mm, active_only=False)
        elif choice == "s":
            await lesson_search(mm)
        elif choice == "n":
            await lesson_create(mm)


async def lesson_list(mm: MemoryManager, active_only=True):
    lessons = await mm.list_lessons(limit=100, active_only=active_only)
    if not lessons:
        print(f"\n  {C.DIM}Порожньо.{C.RST}")
        input(f"\n  {C.DIM}Enter...{C.RST}")
        return

    while True:
        _clear()
        label = "Active Lessons" if active_only else "All Lessons"
        print(f"\n  {C.BD}{label}{C.RST}  ({len(lessons)})\n")
        for i, l in enumerate(lessons):
            active_mark = "" if l["active"] else f" {C.DIM}[inactive]{C.RST}"
            cat = f"{C.DIM}{l['category']}{C.RST}"
            content_preview = l["content"][:45].replace("\n", " ")
            print(f"  {C.Y}{i+1:>3}{C.RST}  {content_preview:<45s}  {cat}{active_mark}")

        print(f"\n  {C.DIM}Номер для деталей, [q] назад{C.RST}")
        choice = input(f"  {C.DIM}>{C.RST} ").strip()
        if choice == "q":
            return
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(lessons):
                await lesson_detail(mm, lessons[idx])
                lessons = await mm.list_lessons(limit=100, active_only=active_only)
        except ValueError:
            pass


async def lesson_detail(mm: MemoryManager, les: dict):
    while True:
        _clear()
        lid = les["id"]
        print(f"\n  {C.BD}{C.CY}Lesson{C.RST}  {C.DIM}{lid}{C.RST}\n")
        print(f"  {C.BD}Category:{C.RST}  {les['category']}")
        print(f"  {C.BD}Source:{C.RST}    {les['source']}")
        print(f"  {C.BD}Active:{C.RST}    {'Yes' if les['active'] else 'No'}")
        print(f"  {C.BD}Triggered:{C.RST} {les['trigger_count']}x")
        print(f"  {C.BD}Created:{C.RST}   {les['created_at'][:19]}")

        print(f"\n  {C.BD}Trigger:{C.RST}")
        for line in (les.get("trigger_context") or "—").split("\n"):
            print(f"    {line}")
        print(f"\n  {C.BD}Content:{C.RST}")
        for line in les["content"].split("\n"):
            print(f"    {line}")

        act_label = "Deactivate" if les["active"] else "Activate"
        print(f"\n  {C.BD}[e]{C.RST} Edit  {C.BD}[t]{C.RST} {act_label}  {C.BD}[d]{C.RST} Delete  {C.BD}[q]{C.RST} Back")
        choice = input(f"\n  {C.DIM}>{C.RST} ").strip().lower()

        if choice == "q":
            return
        elif choice == "e":
            text = f"# Trigger\n{les.get('trigger_context','')}\n\n# Content\n{les['content']}"
            new_text = edit_in_editor(text)
            if new_text:
                parts = new_text.split("# Content")
                if len(parts) == 2:
                    trigger = parts[0].replace("# Trigger", "").strip()
                    content = parts[1].strip()
                else:
                    trigger = None
                    content = new_text.strip()
                ok = await mm.update_lesson(lid, content, trigger)
                if ok:
                    les["content"] = content
                    if trigger: les["trigger_context"] = trigger
                    print(f"\n  {C.G}Збережено.{C.RST}")
                else:
                    print(f"\n  {C.R}Помилка.{C.RST}")
                input(f"  {C.DIM}Enter...{C.RST}")
        elif choice == "t":
            if les["active"]:
                ok = await mm.deactivate_lesson(lid)
                if ok:
                    les["active"] = False
                    print(f"\n  {C.Y}Деактивовано.{C.RST}")
            else:
                ok = await mm.activate_lesson(lid)
                if ok:
                    les["active"] = True
                    print(f"\n  {C.G}Активовано.{C.RST}")
            input(f"  {C.DIM}Enter...{C.RST}")
        elif choice == "d":
            confirm = input(f"\n  {C.R}Видалити назавжди? [y/N]{C.RST} ").strip().lower()
            if confirm == "y":
                ok = await mm.delete_lesson(lid)
                if ok:
                    print(f"\n  {C.R}Видалено.{C.RST}")
                    input(f"  {C.DIM}Enter...{C.RST}")
                    return
            else:
                print(f"  {C.DIM}Скасовано.{C.RST}")
                input(f"  {C.DIM}Enter...{C.RST}")


async def lesson_search(mm: MemoryManager):
    _clear()
    print(f"\n  {C.BD}Lesson Search{C.RST}\n")
    query = input(f"  Запит: ").strip()
    if not query:
        return
    results = await mm.search_lessons(query, limit=10, threshold=0.2)
    if not results:
        print(f"\n  {C.DIM}Нічого не знайдено.{C.RST}")
        input(f"\n  {C.DIM}Enter...{C.RST}")
        return

    print(f"\n  {C.G}Знайдено: {len(results)}{C.RST}\n")
    for i, l in enumerate(results):
        sim = l.get("similarity", 0)
        preview = l["content"][:45].replace("\n", " ")
        print(f"  {C.Y}{i+1:>3}{C.RST}  {sim:.0%}  {preview}")

    print(f"\n  {C.DIM}Номер для деталей, [q] назад{C.RST}")
    choice = input(f"  {C.DIM}>{C.RST} ").strip()
    if choice == "q":
        return
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(results):
            await lesson_detail(mm, results[idx])
    except ValueError:
        pass


async def lesson_create(mm: MemoryManager):
    _clear()
    print(f"\n  {C.BD}New Lesson{C.RST}\n")
    trigger = input(f"  Trigger context: ").strip()
    category = input(f"  Категорія {C.DIM}[general]{C.RST}: ").strip() or "general"
    print(f"\n  {C.DIM}Відкриваю редактор...{C.RST}")
    content = edit_in_editor("", suffix=".md")
    if not content or not content.strip():
        print(f"  {C.DIM}Скасовано.{C.RST}")
        input(f"  {C.DIM}Enter...{C.RST}")
        return
    lid = await mm.save_lesson(content.strip(), trigger_context=trigger, source="manual", category=category)
    print(f"\n  {C.G}Збережено: {lid}{C.RST}")
    input(f"  {C.DIM}Enter...{C.RST}")


# ── Main interactive loop ──

async def interactive(mm: MemoryManager):
    first_run = True
    while True:
        _clear()
        services, mem_info, model_info, modules, readiness, collect_ms = \
            await collect(mm, with_readiness=first_run)
        first_run = False
        score, label = compute_health(services)
        print(render_status(services, mem_info, model_info, modules, readiness, score, label, collect_ms))

        print(f"\n  {C.BD}[m]{C.RST} Memories  {C.BD}[l]{C.RST} Lessons  {C.BD}[r]{C.RST} Refresh  {C.BD}[q]{C.RST} Quit")
        choice = input(f"\n  {C.DIM}>{C.RST} ").strip().lower()

        if choice == "q":
            print(f"\n  {C.DIM}Бувай.{C.RST}\n")
            return
        elif choice == "m":
            await memory_menu(mm)
        elif choice == "l":
            await lesson_menu(mm)
        elif choice == "r":
            continue


# ── Non-interactive modes ──

def render_json(services, mem_info, model_info, modules, score, label, collect_ms):
    data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "health": {"score": score, "label": label},
        "collect_ms": round(collect_ms, 1),
        "services": [s.to_dict() for s in services],
        "modules": modules.get("modules", {}),
        "memory": {
            "active": mem_info.get("active", 0), "archived": mem_info.get("archived", 0),
            "total": mem_info.get("total", 0), "lessons": mem_info.get("lessons", 0),
        },
        "model": model_info,
    }
    return json_lib.dumps(data, indent=2, default=str)


def render_compact(services, mem_info, score, label):
    hc = _health_color(label)
    parts = [f"{hc}{label}({score}%){C.RST}"]
    for s in services:
        parts.append(f"{_status_color(s.status)}●{C.RST} {s.name}:{_fmt_ms(s.latency_ms)}")
    parts.append(f"mem:{mem_info.get('total',0)}")
    parts.append(f"les:{mem_info.get('lessons',0)}")
    return "  ".join(parts)


# ── CLI ──

def parse_args():
    p = argparse.ArgumentParser(description="Lyume Status Dashboard")
    p.add_argument("--watch", action="store_true", help="Auto-refresh (non-interactive)")
    p.add_argument("--interval", type=float, default=3, help="Refresh interval (with --watch)")
    p.add_argument("--json", action="store_true", help="JSON output")
    p.add_argument("--compact", action="store_true", help="Single-line output")
    p.add_argument("--no-color", action="store_true", help="Disable ANSI colors")
    p.add_argument("--verbose", "-v", action="store_true", help="Show config, DB pool, tracebacks")
    p.add_argument("--once", action="store_true", help="One-shot status (no interactive menu)")
    return p.parse_args()


def exit_code(label):
    if label == "READY": return 0
    elif label in ("DEGRADED", "PARTIAL"): return 1
    return 2


async def run_once(mm, args):
    services, mem_info, model_info, modules, readiness, collect_ms = \
        await collect(mm, with_readiness=True)
    score, label = compute_health(services)
    if args.json:
        print(render_json(services, mem_info, model_info, modules, score, label, collect_ms))
    elif args.compact:
        print(render_compact(services, mem_info, score, label))
    else:
        print()
        print(render_status(services, mem_info, model_info, modules, readiness, score, label, collect_ms))
        print()
    return exit_code(label)


async def run_watch(mm, args):
    try:
        while True:
            _clear()
            await run_once(mm, args)
            print(f"  {C.DIM}Ctrl+C to exit  │  refresh: {args.interval}s{C.RST}")
            await asyncio.sleep(args.interval)
    except KeyboardInterrupt:
        print(f"\n  {C.DIM}Stopped.{C.RST}\n")


async def async_main():
    args = parse_args()
    global VERBOSE
    if args.no_color:
        C.disable()
    if args.verbose:
        VERBOSE = True

    global mm_ref
    mm = MemoryManager()
    mm_ref = mm
    try:
        if args.watch:
            await run_watch(mm, args)
        elif args.json or args.compact or args.once:
            code = await run_once(mm, args)
            await mm.close()
            sys.exit(code)
        else:
            # Default: interactive
            await interactive(mm)
    finally:
        try:
            await mm.close()
        except Exception:
            pass


def main():
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
