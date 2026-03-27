#!/usr/bin/env python3
"""
Lyume Brain — Memory & Intuition Manager.
Tab 1: Memories (semantic)
Tab 2: Lessons (intuition)
Zero external dependencies (curses).
"""

import asyncio
import curses
import textwrap
import uuid as _uuid

from memory_manager import MemoryManager

mm = MemoryManager()
_loop = asyncio.new_event_loop()


def run(coro):
    return _loop.run_until_complete(coro)


# ── Data: Memories ──

def fetch_memories(include_archived: bool = False) -> list[dict]:
    return run(mm.list_semantic(limit=200, include_archived=include_archived))


def search_memories(query: str) -> list[dict]:
    return run(mm.search_semantic(query, limit=10, threshold=0.2, include_archived=True))


def add_memory(content: str, category: str) -> str:
    return run(mm.save_semantic(content=content, category=category))


def archive_memory(mem_id: str) -> bool:
    return run(mm.pool.execute(
        "UPDATE memories_semantic SET archived = true WHERE id = $1",
        _uuid.UUID(mem_id),
    )) == "UPDATE 1"


def unarchive_memory(mem_id: str) -> bool:
    return run(mm.unarchive(mem_id))


def delete_memory(mem_id: str) -> bool:
    return run(mm.delete_semantic(mem_id))


# ── Data: Lessons ──

def fetch_lessons(active_only: bool = True) -> list[dict]:
    return run(mm.list_lessons(limit=200, active_only=active_only))


def search_lessons(query: str) -> list[dict]:
    return run(mm.search_lessons(query, limit=10, threshold=0.5))


def add_lesson(trigger: str, content: str, category: str) -> str:
    return run(mm.save_lesson(content=content, trigger_context=trigger, source="manual", category=category))


def deactivate_lesson(lesson_id: str) -> bool:
    return run(mm.pool.execute(
        "UPDATE lessons SET active = false WHERE id = $1", _uuid.UUID(lesson_id),
    )) == "UPDATE 1"


def activate_lesson(lesson_id: str) -> bool:
    return run(mm.pool.execute(
        "UPDATE lessons SET active = true WHERE id = $1", _uuid.UUID(lesson_id),
    )) == "UPDATE 1"


def delete_lesson_db(lesson_id: str) -> bool:
    return run(mm.pool.execute(
        "DELETE FROM lessons WHERE id = $1", _uuid.UUID(lesson_id),
    )) == "DELETE 1"


# ── UI helpers ──

def safe_addstr(win, y, x, text, attr=0):
    h, w = win.getmaxyx()
    if y < 0 or y >= h or x >= w:
        return
    text = str(text)[:w - x - 1]
    try:
        win.addstr(y, x, text, attr)
    except curses.error:
        pass


def text_input(stdscr, prompt: str, y: int, x: int = 2) -> str:
    h, w = stdscr.getmaxyx()
    safe_addstr(stdscr, y, x, prompt, curses.A_BOLD)
    stdscr.refresh()
    curses.echo()
    curses.curs_set(1)
    try:
        inp = stdscr.getstr(y, x + len(prompt), w - x - len(prompt) - 2)
        return inp.decode("utf-8").strip()
    except (curses.error, UnicodeDecodeError):
        return ""
    finally:
        curses.noecho()
        curses.curs_set(0)


def confirm(stdscr, message: str, y: int) -> bool:
    safe_addstr(stdscr, y, 2, f"{message} (y/n) ", curses.A_BOLD)
    stdscr.refresh()
    while True:
        key = stdscr.getch()
        if key in (ord("y"), ord("Y")):
            return True
        if key in (ord("n"), ord("N"), 27):
            return False


# ── App ──

class App:
    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.tab = 0  # 0=memories, 1=lessons
        self.items: list[dict] = []
        self.filtered: list[dict] = []
        self.cursor = 0
        self.scroll = 0
        self.show_hidden = False  # archived memories / inactive lessons
        self.status = ""
        self.mode = "list"  # list, detail

    @property
    def tab_name(self):
        return ["MEMORIES", "LESSONS"][self.tab]

    def load(self):
        if self.tab == 0:
            self.items = fetch_memories(include_archived=self.show_hidden)
        else:
            self.items = fetch_lessons(active_only=not self.show_hidden)
        self.filtered = self.items
        self.cursor = min(self.cursor, max(0, len(self.filtered) - 1))

    def content_height(self):
        h, _ = self.stdscr.getmaxyx()
        return h - 5  # header(3) + footer(2)

    def switch_tab(self):
        self.tab = 1 - self.tab
        self.cursor = 0
        self.scroll = 0
        self.show_hidden = False
        self.status = ""
        self.mode = "list"
        self.load()

    # ── Drawing ──

    def draw_header(self):
        _, w = self.stdscr.getmaxyx()
        title = " LYUME BRAIN "
        pad = "═" * ((w - len(title)) // 2)
        safe_addstr(self.stdscr, 0, 0, pad + title + pad, curses.A_BOLD | curses.color_pair(1))

        # Tabs
        for i, name in enumerate(["  MEMORIES  ", "  LESSONS  "]):
            x = i * 14 + 2
            if i == self.tab:
                safe_addstr(self.stdscr, 1, x, name, curses.A_BOLD | curses.A_REVERSE | curses.color_pair(1))
            else:
                safe_addstr(self.stdscr, 1, x, name, curses.A_DIM)

        count = len(self.filtered)
        label = "memories" if self.tab == 0 else "lessons"
        extra = " (+ archived)" if self.tab == 0 and self.show_hidden else ""
        extra = " (+ inactive)" if self.tab == 1 and self.show_hidden else extra
        safe_addstr(self.stdscr, 2, 2, f" {count} {label}{extra}", curses.color_pair(2))

    def draw_footer(self):
        h, w = self.stdscr.getmaxyx()
        if self.mode == "list":
            keys = " ↑↓ Navigate  Tab Switch  Enter Details  /Search  a Add  i Toggle hidden  q Quit "
        elif self.mode == "detail":
            if self.tab == 0:
                keys = " x Archive  D Delete  r Unarchive  Esc Back "
            else:
                keys = " d Deactivate  D Delete  r Reactivate  Esc Back "

        safe_addstr(self.stdscr, h - 2, 0, "─" * w, curses.color_pair(3))
        safe_addstr(self.stdscr, h - 1, 0, keys[:w - 1], curses.A_DIM)

        if self.status:
            safe_addstr(self.stdscr, h - 2, 2, f" {self.status} ", curses.color_pair(4))

    def draw_list(self):
        ch = self.content_height()
        _, w = self.stdscr.getmaxyx()

        if self.cursor < self.scroll:
            self.scroll = self.cursor
        if self.cursor >= self.scroll + ch:
            self.scroll = self.cursor - ch + 1

        for i in range(ch):
            idx = self.scroll + i
            y = i + 3
            if idx >= len(self.filtered):
                safe_addstr(self.stdscr, y, 0, " " * (w - 1))
                continue

            item = self.filtered[idx]
            is_selected = idx == self.cursor
            attr = curses.A_REVERSE if is_selected else 0

            if self.tab == 0:
                line = self._format_memory_line(item, w)
                is_hidden = item.get("archived", False)
            else:
                line = self._format_lesson_line(item, w)
                is_hidden = not item.get("active", True)

            if is_hidden:
                attr |= curses.color_pair(3)
            elif is_selected:
                attr |= curses.color_pair(1)

            safe_addstr(self.stdscr, y, 0, line, attr)

    def _format_memory_line(self, m, w):
        status = "○" if m.get("archived") else "●"
        cat = m.get("category", "")[:10].ljust(10)
        hits = f"×{m['access_count']}" if m.get("access_count") else " —"
        content = m["content"][:w - 25]
        line = f" {status} [{cat}] {hits:>4s}  {content}"
        return line[:w - 1].ljust(w - 1)

    def _format_lesson_line(self, l, w):
        status = "●" if l["active"] else "○"
        cat = l["category"][:12].ljust(12)
        hits = f"×{l['trigger_count']}" if l["trigger_count"] else " —"
        trigger = l["trigger_context"][:25].ljust(25)
        content = l["content"][:w - 52]
        line = f" {status} [{cat}] {hits:>4s}  {trigger} │ {content}"
        return line[:w - 1].ljust(w - 1)

    def draw_detail(self):
        if not self.filtered:
            return
        item = self.filtered[self.cursor]
        _, w = self.stdscr.getmaxyx()
        col_w = w - 6

        y = 3
        safe_addstr(self.stdscr, y, 2, "─" * col_w, curses.color_pair(3))
        y += 1

        if self.tab == 0:
            fields = self._memory_detail_fields(item)
        else:
            fields = self._lesson_detail_fields(item)

        for label, value, wrap_text, color in fields:
            if wrap_text:
                safe_addstr(self.stdscr, y, 2, f" {label}: ", curses.A_BOLD)
                y += 1
                for line in textwrap.wrap(value, col_w - 4):
                    safe_addstr(self.stdscr, y, 4, line, curses.color_pair(color))
                    y += 1
            else:
                safe_addstr(self.stdscr, y, 2, f" {label}: ", curses.A_BOLD)
                safe_addstr(self.stdscr, y, 2 + len(label) + 3, str(value))
                y += 1

        y += 1
        safe_addstr(self.stdscr, y, 2, "─" * col_w, curses.color_pair(3))

    def _memory_detail_fields(self, m):
        # (label, value, is_wrapped, color_pair)
        return [
            ("Status", "● Active" if not m.get("archived") else "○ Archived", False, 0),
            ("Category", m.get("category", ""), False, 0),
            ("Name", m.get("concept_name", "") or "—", False, 0),
            ("Content", m["content"], True, 1),
            ("Keywords", ", ".join(m.get("keywords", [])) or "—", False, 0),
            ("Accessed", f"{m.get('access_count', 0)} times", False, 0),
            ("Updated", str(m.get("last_updated", ""))[:16], False, 0),
            ("Last access", str(m.get("last_accessed", "") or "never")[:16], False, 0),
            ("ID", m["id"], False, 0),
        ]

    def _lesson_detail_fields(self, l):
        return [
            ("Status", "● Active" if l["active"] else "○ Inactive", False, 0),
            ("Category", l["category"], False, 0),
            ("Source", l["source"], False, 0),
            ("Trigger", l["trigger_context"], True, 2),
            ("Content", l["content"], True, 1),
            ("Triggered", f"{l['trigger_count']} times", False, 0),
            ("Last", str(l["last_triggered"] or "never")[:16], False, 0),
            ("Created", l["created_at"][:16], False, 0),
            ("ID", l["id"], False, 0),
        ]

    # ── Actions ──

    def do_search(self):
        self.stdscr.clear()
        self.draw_header()

        query = text_input(self.stdscr, "Search: ", 4)
        if not query:
            self.mode = "list"
            return

        self.status = f"Searching: {query}..."
        self.stdscr.clear()
        self.draw_header()
        self.draw_footer()
        self.stdscr.refresh()

        if self.tab == 0:
            results = search_memories(query)
        else:
            results = search_lessons(query)

        if results:
            self.filtered = results
            self.cursor = 0
            self.scroll = 0
            self.status = f"Found {len(results)} for '{query}'"
        else:
            self.status = f"Nothing found for '{query}'"
            self.filtered = self.items

        self.mode = "list"

    def do_add(self):
        self.stdscr.clear()
        self.draw_header()

        if self.tab == 0:
            safe_addstr(self.stdscr, 4, 2, "── New Memory ──", curses.A_BOLD | curses.color_pair(1))

            content = text_input(self.stdscr, "Content:  ", 6)
            if not content:
                self.mode = "list"
                return

            category = text_input(self.stdscr, "Category [general]: ", 7)
            if not category:
                category = "general"

            if confirm(self.stdscr, "Save?", 9):
                mem_id = add_memory(content, category)
                self.status = f"Saved: {mem_id[:8]}..."
                self.load()
            else:
                self.status = "Cancelled"
        else:
            safe_addstr(self.stdscr, 4, 2, "── New Lesson ──", curses.A_BOLD | curses.color_pair(1))

            trigger = text_input(self.stdscr, "Trigger context: ", 6)
            if not trigger:
                self.mode = "list"
                return

            content = text_input(self.stdscr, "Lesson content:  ", 7)
            if not content:
                self.mode = "list"
                return

            category = text_input(self.stdscr, "Category [general]: ", 8)
            if not category:
                category = "general"

            if confirm(self.stdscr, "Save?", 10):
                lid = add_lesson(trigger, content, category)
                self.status = f"Saved: {lid[:8]}..."
                self.load()
            else:
                self.status = "Cancelled"

        self.mode = "list"

    def handle_detail_keys(self, key):
        if not self.filtered:
            self.mode = "list"
            return

        item = self.filtered[self.cursor]

        if key == 27:  # Esc
            self.mode = "list"
            self.status = ""
            return

        if self.tab == 0:
            self._handle_memory_detail(key, item)
        else:
            self._handle_lesson_detail(key, item)

    def _handle_memory_detail(self, key, m):
        if key == ord("x"):
            self.stdscr.clear()
            self.draw_header()
            self.draw_detail()
            if confirm(self.stdscr, "Archive this memory?", self.content_height() + 2):
                archive_memory(m["id"])
                self.status = "Archived"
                self.load()
            self.mode = "list"
        elif key == ord("D"):
            self.stdscr.clear()
            self.draw_header()
            self.draw_detail()
            if confirm(self.stdscr, "DELETE permanently?", self.content_height() + 2):
                delete_memory(m["id"])
                self.status = "Deleted"
                self.load()
            self.mode = "list"
        elif key == ord("r"):
            unarchive_memory(m["id"])
            self.status = "Unarchived"
            self.load()
            self.mode = "list"

    def _handle_lesson_detail(self, key, l):
        if key == ord("d"):
            self.stdscr.clear()
            self.draw_header()
            self.draw_detail()
            if confirm(self.stdscr, "Deactivate this lesson?", self.content_height() + 2):
                deactivate_lesson(l["id"])
                self.status = "Deactivated"
                self.load()
            self.mode = "list"
        elif key == ord("D"):
            self.stdscr.clear()
            self.draw_header()
            self.draw_detail()
            if confirm(self.stdscr, "DELETE permanently?", self.content_height() + 2):
                delete_lesson_db(l["id"])
                self.status = "Deleted"
                self.load()
            self.mode = "list"
        elif key == ord("r"):
            activate_lesson(l["id"])
            self.status = "Reactivated"
            self.load()
            self.mode = "list"

    # ── Main loop ──

    def run_app(self):
        self.load()

        while True:
            self.stdscr.clear()
            self.draw_header()

            if self.mode == "list":
                self.draw_list()
            elif self.mode == "detail":
                self.draw_detail()

            self.draw_footer()
            self.stdscr.refresh()

            key = self.stdscr.getch()

            if self.mode == "list":
                if key == ord("q"):
                    break
                elif key == ord("\t") or key == curses.KEY_BTAB:
                    self.switch_tab()
                elif key == curses.KEY_UP and self.cursor > 0:
                    self.cursor -= 1
                elif key == curses.KEY_DOWN and self.cursor < len(self.filtered) - 1:
                    self.cursor += 1
                elif key == curses.KEY_PPAGE:
                    self.cursor = max(0, self.cursor - self.content_height())
                elif key == curses.KEY_NPAGE:
                    self.cursor = min(len(self.filtered) - 1, self.cursor + self.content_height())
                elif key in (curses.KEY_ENTER, 10, 13):
                    if self.filtered:
                        self.mode = "detail"
                elif key == ord("/"):
                    self.do_search()
                elif key == ord("a"):
                    self.do_add()
                elif key == ord("i"):
                    self.show_hidden = not self.show_hidden
                    self.load()
                    if self.tab == 0:
                        self.status = "Showing archived" if self.show_hidden else "Active only"
                    else:
                        self.status = "Showing inactive" if self.show_hidden else "Active only"
                elif key == 27:  # Esc — reset filter
                    self.filtered = self.items
                    self.cursor = 0
                    self.scroll = 0
                    self.status = ""

            elif self.mode == "detail":
                self.handle_detail_keys(key)


def main(stdscr):
    curses.curs_set(0)
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_CYAN, -1)
    curses.init_pair(2, curses.COLOR_GREEN, -1)
    curses.init_pair(3, 8, -1)  # dim gray
    curses.init_pair(4, curses.COLOR_YELLOW, -1)

    app = App(stdscr)
    app.run_app()


if __name__ == "__main__":
    try:
        run(mm.connect())
        curses.wrapper(main)
    finally:
        run(mm.close())
        _loop.close()
