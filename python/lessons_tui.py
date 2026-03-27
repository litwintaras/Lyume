#!/usr/bin/env python3
"""
Lessons TUI — manage Lyume's intuition system.
Browse, search, add, deactivate lessons.
Zero external dependencies (curses).
"""

import asyncio
import curses
import sys
import textwrap

from memory_manager import MemoryManager

mm = MemoryManager()
_loop = asyncio.new_event_loop()


def run(coro):
    """Run async code on persistent event loop."""
    return _loop.run_until_complete(coro)


# ── Data layer ──

def fetch_lessons(active_only: bool = True) -> list[dict]:
    return run(mm.list_lessons(limit=200, active_only=active_only))


def do_search(query: str) -> list[dict]:
    return run(mm.search_lessons(query, limit=10, threshold=0.5))


def add_lesson(trigger: str, content: str, category: str) -> str:
    return run(mm.save_lesson(content=content, trigger_context=trigger, source="manual", category=category))


def deactivate(lesson_id: str) -> bool:
    import uuid as _uuid
    return run(mm.pool.execute(
        "UPDATE lessons SET active = false WHERE id = $1", _uuid.UUID(lesson_id)
    )) == "UPDATE 1"


def activate(lesson_id: str) -> bool:
    import uuid as _uuid
    return run(mm.pool.execute(
        "UPDATE lessons SET active = true WHERE id = $1", _uuid.UUID(lesson_id)
    )) == "UPDATE 1"


def delete_lesson(lesson_id: str) -> bool:
    import uuid as _uuid
    return run(mm.pool.execute(
        "DELETE FROM lessons WHERE id = $1", _uuid.UUID(lesson_id)
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
    """Simple text input with prompt."""
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


# ── Screens ──

class App:
    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.lessons: list[dict] = []
        self.filtered: list[dict] = []
        self.cursor = 0
        self.scroll = 0
        self.show_inactive = False
        self.status = ""
        self.mode = "list"  # list, detail, search, add

    def load(self):
        self.lessons = fetch_lessons(active_only=not self.show_inactive)
        self.filtered = self.lessons
        self.cursor = min(self.cursor, max(0, len(self.filtered) - 1))

    def content_height(self):
        h, _ = self.stdscr.getmaxyx()
        return h - 4  # header(2) + footer(2)

    def draw_header(self):
        _, w = self.stdscr.getmaxyx()
        title = " LYUME INTUITION — Lessons Manager "
        pad = "═" * ((w - len(title)) // 2)
        safe_addstr(self.stdscr, 0, 0, pad + title + pad, curses.A_BOLD | curses.color_pair(1))

        count_text = f" {len(self.filtered)} lessons"
        if self.show_inactive:
            count_text += " (+ inactive)"
        safe_addstr(self.stdscr, 1, 2, count_text, curses.color_pair(2))

    def draw_footer(self):
        h, w = self.stdscr.getmaxyx()
        if self.mode == "list":
            keys = " ↑↓ Navigate  Enter Details  /Search  a Add  i Toggle inactive  q Quit "
        elif self.mode == "detail":
            keys = " d Deactivate  D Delete  r Reactivate  Esc Back "
        elif self.mode == "search":
            keys = " Esc Back to list "
        else:
            keys = " Esc Cancel "

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
            y = i + 2
            if idx >= len(self.filtered):
                safe_addstr(self.stdscr, y, 0, " " * (w - 1))
                continue

            lesson = self.filtered[idx]
            is_selected = idx == self.cursor
            attr = curses.A_REVERSE if is_selected else 0

            status = "●" if lesson["active"] else "○"
            cat = lesson["category"][:12].ljust(12)
            triggered = f"×{lesson['trigger_count']}" if lesson["trigger_count"] else " —"
            trigger = lesson["trigger_context"][:25].ljust(25)
            content = lesson["content"][:w - 50]

            line = f" {status} [{cat}] {triggered:>4s}  {trigger} │ {content}"
            line = line[:w - 1].ljust(w - 1)

            if not lesson["active"]:
                attr |= curses.color_pair(3)
            elif is_selected:
                attr |= curses.color_pair(1)

            safe_addstr(self.stdscr, y, 0, line, attr)

    def draw_detail(self):
        if not self.filtered:
            return
        lesson = self.filtered[self.cursor]
        _, w = self.stdscr.getmaxyx()
        col_w = w - 6

        y = 2
        safe_addstr(self.stdscr, y, 2, "─" * col_w, curses.color_pair(3))
        y += 1

        fields = [
            ("Status", "● Active" if lesson["active"] else "○ Inactive"),
            ("Category", lesson["category"]),
            ("Source", lesson["source"]),
            ("Trigger", ""),
            ("Content", ""),
            ("Triggered", f"{lesson['trigger_count']} times"),
            ("Last", lesson["last_triggered"] or "never"),
            ("Created", lesson["created_at"][:16]),
            ("ID", lesson["id"]),
        ]

        for label, value in fields:
            if label == "Trigger":
                safe_addstr(self.stdscr, y, 2, f" {label}: ", curses.A_BOLD)
                y += 1
                for line in textwrap.wrap(lesson["trigger_context"], col_w - 4):
                    safe_addstr(self.stdscr, y, 4, line, curses.color_pair(2))
                    y += 1
            elif label == "Content":
                safe_addstr(self.stdscr, y, 2, f" {label}: ", curses.A_BOLD)
                y += 1
                for line in textwrap.wrap(lesson["content"], col_w - 4):
                    safe_addstr(self.stdscr, y, 4, line, curses.color_pair(1))
                    y += 1
            else:
                safe_addstr(self.stdscr, y, 2, f" {label}: ", curses.A_BOLD)
                safe_addstr(self.stdscr, y, 2 + len(label) + 3, value)
                y += 1

        y += 1
        safe_addstr(self.stdscr, y, 2, "─" * col_w, curses.color_pair(3))

    def screen_search(self):
        self.stdscr.clear()
        self.draw_header()
        h, w = self.stdscr.getmaxyx()

        query = text_input(self.stdscr, "Search: ", 3)
        if not query:
            self.mode = "list"
            return

        self.status = f"Searching: {query}..."
        self.stdscr.clear()
        self.draw_header()
        self.draw_footer()
        self.stdscr.refresh()

        results = do_search(query)
        if results:
            self.filtered = results
            self.cursor = 0
            self.scroll = 0
            self.status = f"Found {len(results)} for '{query}'"
        else:
            self.status = f"Nothing found for '{query}'"
            self.filtered = self.lessons

        self.mode = "list"

    def screen_add(self):
        self.stdscr.clear()
        self.draw_header()

        safe_addstr(self.stdscr, 3, 2, "── New Lesson ──", curses.A_BOLD | curses.color_pair(1))

        trigger = text_input(self.stdscr, "Trigger context: ", 5)
        if not trigger:
            self.mode = "list"
            return

        content = text_input(self.stdscr, "Lesson content:  ", 6)
        if not content:
            self.mode = "list"
            return

        category = text_input(self.stdscr, "Category [general]: ", 7)
        if not category:
            category = "general"

        if confirm(self.stdscr, "Save?", 9):
            lesson_id = add_lesson(trigger, content, category)
            self.status = f"Saved: {lesson_id[:8]}..."
            self.load()
        else:
            self.status = "Cancelled"

        self.mode = "list"

    def handle_detail_keys(self, key):
        if not self.filtered:
            self.mode = "list"
            return

        lesson = self.filtered[self.cursor]

        if key == 27:  # Esc
            self.mode = "list"
            self.status = ""
        elif key == ord("d"):
            self.stdscr.clear()
            self.draw_header()
            self.draw_detail()
            if confirm(self.stdscr, "Deactivate this lesson?", self.content_height() + 1):
                deactivate(lesson["id"])
                self.status = "Deactivated"
                self.load()
            self.mode = "list"
        elif key == ord("D"):
            self.stdscr.clear()
            self.draw_header()
            self.draw_detail()
            if confirm(self.stdscr, "DELETE permanently?", self.content_height() + 1):
                delete_lesson(lesson["id"])
                self.status = "Deleted"
                self.load()
            self.mode = "list"
        elif key == ord("r"):
            activate(lesson["id"])
            self.status = "Reactivated"
            self.load()
            self.mode = "list"

    def run(self):
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
                    self.screen_search()
                elif key == ord("a"):
                    self.screen_add()
                elif key == ord("i"):
                    self.show_inactive = not self.show_inactive
                    self.load()
                    self.status = "Showing inactive" if self.show_inactive else "Active only"
                elif key == 27:  # Esc — reset filter
                    self.filtered = self.lessons
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
    app.run()


if __name__ == "__main__":
    try:
        run(mm.connect())
        curses.wrapper(main)
    finally:
        run(mm.close())
        _loop.close()
