"""
LYUME MEMORY CORTEX - Terminal UI
Cyberpunk memory manager for Lyume's semantic memory.
"""

import sys
from datetime import datetime

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    DataTable,
    Footer,
    Input,
    Label,
    Static,
    TextArea,
)

from memory_manager import MemoryManager

mm = MemoryManager()

BANNER = (
    "+----- . . . -------------------------------------------------------- . . . -----+\n"
    "|                                                                                  |\n"
    "|          .---.                                                                    |\n"
    "|         / . . \\     ##    ##  ##  ##  ##   ## ###### ######                        |\n"
    "|        | \\_^_/ |    ##    ##  ##  ##  ##  ##  ##  ## ##                            |\n"
    "|         \\_---_/     ##     ####   ##  ##  ####   ####  ####                        |\n"
    "|        ./ | | \\.    ##      ##    ##  ##  ## ##  ##       ##                        |\n"
    "|       /  (| |)  \\   ######  ##     ####   ##  ## ###### ######                     |\n"
    "|      '---' '---'                                                                  |\n"
    "|                            M E M O R Y    C O R T E X                             |\n"
    "|                                                                                   |\n"
    "+---- . . . --------------------------------------------------------- . . . ------+\n"
    "|  /search    n/new    e/edit    a/archive    DEL/delete    TAB/archived    r/fresh  |\n"
    "+---- . . . --------------------------------------------------------- . . . ------+"
)

# -- Styles ---------------------------------------------------------------
CSS = """
Screen {
    background: #0a0a12;
}

#banner {
    dock: top;
    height: auto;
    background: #0a0a12;
    color: #3a5a7a;
    text-align: center;
    padding: 0 2;
}

Footer {
    background: #0d0d1a;
    color: #4a5a6a;
}

FooterKey {
    background: #0d0d1a;
    color: #7088a0;
    .footer-key--key {
        background: #1a1a2e;
        color: #8ca8c4;
    }
}

#stats-bar {
    dock: top;
    height: 3;
    background: #0d0d1a;
    color: #4a6a8a;
    padding: 0 2;
    border-bottom: solid #1a1a2e;
}

#stats-bar Label {
    width: auto;
    margin: 0 2;
    color: #7088a0;
}

#stats-bar .stat-value {
    color: #8ca8c4;
    text-style: bold;
}

#main-container {
    height: 1fr;
}

DataTable {
    height: 1fr;
    background: #0a0a12;
    scrollbar-background: #0d0d1a;
    scrollbar-color: #1a2a3a;
    scrollbar-color-hover: #2a3a4a;
    scrollbar-color-active: #3a4a5a;
}

DataTable > .datatable--header {
    background: #121222;
    color: #8ca8c4;
    text-style: bold;
}

DataTable > .datatable--cursor {
    background: #1a2a3a;
    color: #c0d0e0;
}

DataTable > .datatable--even-row {
    background: #0a0a12;
    color: #607080;
}

DataTable > .datatable--odd-row {
    background: #0c0c16;
    color: #607080;
}

#detail-panel {
    dock: right;
    width: 45;
    background: #0d0d1a;
    border-left: solid #1a1a2e;
    padding: 1 2;
    display: none;
}

#detail-panel.visible {
    display: block;
}

#detail-title {
    color: #8ca8c4;
    text-style: bold;
    margin-bottom: 1;
}

#detail-content {
    color: #a0b0c0;
    margin-bottom: 1;
}

#detail-meta {
    color: #4a5a6a;
}

.archived-tag {
    color: #8a4a2a;
    text-style: bold;
}

/* -- Modal screens -- */

ModalScreen {
    align: center middle;
}

#dialog-container {
    width: 60;
    height: auto;
    max-height: 80%;
    background: #0d0d1a;
    border: solid #1a2a3a;
    padding: 1 2;
}

#dialog-container.wide {
    width: 80;
}

#dialog-title {
    color: #8ca8c4;
    text-style: bold;
    text-align: center;
    margin-bottom: 1;
}

#dialog-input {
    background: #0a0a12;
    color: #a0b0c0;
    border: solid #1a1a2e;
    margin-bottom: 1;
}

#dialog-textarea {
    background: #0a0a12;
    color: #a0b0c0;
    border: solid #1a1a2e;
    height: 8;
    margin-bottom: 1;
}

#dialog-hint {
    color: #4a5a6a;
    text-align: center;
}

#confirm-text {
    color: #c07070;
    text-align: center;
    margin: 1 0;
}

#search-results-info {
    color: #4a6a8a;
    margin-bottom: 1;
    text-align: center;
}
"""


# -- Modal Screens --------------------------------------------------------

class SearchScreen(ModalScreen[str]):
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Container(id="dialog-container"):
            yield Label("[MEMORY SEARCH]", id="dialog-title")
            yield Input(placeholder="search query...", id="dialog-input")
            yield Label("ENTER = search  |  ESC = cancel", id="dialog-hint")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    def action_cancel(self) -> None:
        self.dismiss("")


class EditScreen(ModalScreen[str]):
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, content: str, **kwargs):
        super().__init__(**kwargs)
        self._content = content

    def compose(self) -> ComposeResult:
        with Container(id="dialog-container", classes="wide"):
            yield Label("[EDIT MEMORY]", id="dialog-title")
            yield TextArea(self._content, id="dialog-textarea")
            yield Label("CTRL+S = save  |  ESC = cancel", id="dialog-hint")

    def on_key(self, event) -> None:
        if event.key == "ctrl+s":
            ta = self.query_one("#dialog-textarea", TextArea)
            self.dismiss(ta.text)

    def action_cancel(self) -> None:
        self.dismiss("")


class NewMemoryScreen(ModalScreen[tuple]):
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Container(id="dialog-container", classes="wide"):
            yield Label("[NEW MEMORY]", id="dialog-title")
            yield Label("Category:", classes="stat-value")
            yield Input(placeholder="fact / preference / person / event", id="new-cat")
            yield Label("Content:", classes="stat-value")
            yield TextArea("", id="dialog-textarea")
            yield Label("CTRL+S = save  |  ESC = cancel", id="dialog-hint")

    def on_key(self, event) -> None:
        if event.key == "ctrl+s":
            cat = self.query_one("#new-cat", Input).value or "general"
            content = self.query_one("#dialog-textarea", TextArea).text
            if content.strip():
                self.dismiss((cat, content))
            else:
                self.dismiss(())

    def action_cancel(self) -> None:
        self.dismiss(())


class ConfirmScreen(ModalScreen[bool]):
    BINDINGS = [
        Binding("y", "yes", "Yes"),
        Binding("n", "no", "No"),
        Binding("escape", "no", "Cancel"),
    ]

    def __init__(self, message: str, **kwargs):
        super().__init__(**kwargs)
        self._message = message

    def compose(self) -> ComposeResult:
        with Container(id="dialog-container"):
            yield Label("[CONFIRM]", id="dialog-title")
            yield Label(self._message, id="confirm-text")
            yield Label("Y = confirm  |  N / ESC = cancel", id="dialog-hint")

    def action_yes(self) -> None:
        self.dismiss(True)

    def action_no(self) -> None:
        self.dismiss(False)


# -- Main App -------------------------------------------------------------

class MemoryCortex(App):
    TITLE = "LYUME MEMORY CORTEX"
    CSS = CSS

    BINDINGS = [
        Binding("slash", "search", "/ Search", priority=True),
        Binding("n", "new_memory", "New", priority=True),
        Binding("e", "edit", "Edit", priority=True),
        Binding("a", "toggle_archive", "Arch/Restore", priority=True),
        Binding("delete", "delete", "DEL Delete", priority=True),
        Binding("r", "refresh", "Refresh", priority=True),
        Binding("tab", "toggle_show_archived", "TAB Archived", priority=True),
        Binding("escape", "close_detail", "Close Detail", show=False),
        Binding("q", "quit", "Quit", priority=True),
    ]

    show_archived = False
    memories: list[dict] = []
    search_query: str = ""

    def compose(self) -> ComposeResult:
        yield Static(BANNER, id="banner")
        with Horizontal(id="stats-bar"):
            yield Label("* ACTIVE: ", classes="stat-label")
            yield Label("--", id="stat-active", classes="stat-value")
            yield Label("* ARCHIVED: ", classes="stat-label")
            yield Label("--", id="stat-archived", classes="stat-value")
            yield Label("* TOTAL: ", classes="stat-label")
            yield Label("--", id="stat-total", classes="stat-value")
            yield Label("", id="stat-filter")
        with Horizontal(id="main-container"):
            yield DataTable(id="memory-table")
            with Vertical(id="detail-panel"):
                yield Label("", id="detail-title")
                yield Static("", id="detail-content")
                yield Static("", id="detail-meta")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#memory-table", DataTable)
        table.cursor_type = "row"
        table.zebra_stripes = True
        table.add_column("ID", width=8)
        table.add_column("CATEGORY", width=12)
        table.add_column("CONTENT")
        table.add_column("ACCESSED", width=12)
        table.add_column("HITS", width=6)
        table.add_column("STATUS", width=8)
        self.load_memories()

    @work(exclusive=True)
    async def load_memories(self) -> None:
        await mm.connect()
        if self.search_query:
            self.memories = await mm.search_semantic(
                self.search_query,
                limit=50,
                threshold=0.1,
                include_archived=self.show_archived,
            )
        else:
            self.memories = await mm.list_semantic(
                limit=100, include_archived=self.show_archived
            )

        stats = await mm.stats()
        self._update_stats(stats)
        self._update_table()

    def _update_stats(self, stats: dict) -> None:
        self.query_one("#stat-active", Label).update(str(stats.get("active", 0)))
        self.query_one("#stat-archived", Label).update(str(stats.get("archived", 0)))
        self.query_one("#stat-total", Label).update(str(stats.get("total", 0)))

        filter_text = ""
        if self.search_query:
            filter_text = f'* SEARCH: "{self.search_query}"'
        elif self.show_archived:
            filter_text = "* FILTER: +archived"
        self.query_one("#stat-filter", Label).update(filter_text)

    def _update_table(self) -> None:
        table = self.query_one("#memory-table", DataTable)
        table.clear()

        for mem in self.memories:
            content = mem["content"]
            if len(content) > 60:
                content = content[:57] + "..."

            accessed = mem.get("last_accessed") or mem.get("similarity")
            if isinstance(accessed, float):
                accessed = f"{accessed:.0%} match"
            elif isinstance(accessed, str):
                try:
                    dt = datetime.fromisoformat(accessed)
                    accessed = dt.strftime("%m-%d %H:%M")
                except ValueError:
                    accessed = "--"
            else:
                accessed = "--"

            hits = str(mem.get("access_count", "--"))
            status = "ARCHIVED" if mem.get("archived") else "ACTIVE"
            short_id = mem["id"][:8]

            table.add_row(
                short_id,
                mem.get("category", "--"),
                content,
                accessed,
                hits,
                status,
                key=mem["id"],
            )

        panel = self.query_one("#detail-panel")
        panel.remove_class("visible")

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self._show_detail(event.row_key.value)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key:
            self._show_detail(event.row_key.value)

    def _show_detail(self, mem_id: str) -> None:
        mem = next((m for m in self.memories if m["id"] == mem_id), None)
        if not mem:
            return

        panel = self.query_one("#detail-panel")
        panel.add_class("visible")

        status = "[ ARCHIVED ]" if mem.get("archived") else "[ ACTIVE ]"
        self.query_one("#detail-title", Label).update(status)
        self.query_one("#detail-content", Static).update(mem["content"])

        meta_lines = [
            f"ID: {mem['id']}",
            f"Category: {mem.get('category', '--')}",
        ]
        if mem.get("concept_name"):
            meta_lines.append(f"Concept: {mem['concept_name']}")
        if mem.get("keywords"):
            meta_lines.append(f"Keywords: {', '.join(mem['keywords'])}")
        if mem.get("last_updated"):
            meta_lines.append(f"Updated: {mem['last_updated']}")
        if mem.get("last_accessed"):
            if isinstance(mem["last_accessed"], str):
                meta_lines.append(f"Accessed: {mem['last_accessed']}")
        if mem.get("access_count") is not None:
            meta_lines.append(f"Hits: {mem['access_count']}")
        if mem.get("similarity") is not None:
            meta_lines.append(f"Similarity: {mem['similarity']:.2%}")

        self.query_one("#detail-meta", Static).update("\n".join(meta_lines))

    def _get_selected_id(self) -> str | None:
        table = self.query_one("#memory-table", DataTable)
        if table.row_count == 0:
            return None
        try:
            row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
            return row_key.value
        except Exception:
            return None

    # -- Actions -----------------------------------------------------------

    def action_search(self) -> None:
        self.push_screen(SearchScreen(), self._on_search_result)

    def _on_search_result(self, query: str) -> None:
        self.search_query = query
        self.load_memories()

    def action_refresh(self) -> None:
        self.search_query = ""
        self.load_memories()

    def action_toggle_show_archived(self) -> None:
        self.show_archived = not self.show_archived
        self.load_memories()

    def action_close_detail(self) -> None:
        panel = self.query_one("#detail-panel")
        panel.remove_class("visible")

    def action_new_memory(self) -> None:
        self.push_screen(NewMemoryScreen(), self._on_new_memory)

    @work(exclusive=True)
    async def _on_new_memory(self, result: tuple) -> None:
        if not result:
            return
        cat, content = result
        await mm.connect()
        await mm.save_semantic(content=content, category=cat)
        self.notify(f"Saved to [{cat}]", severity="information")
        self.load_memories()

    def action_edit(self) -> None:
        mem_id = self._get_selected_id()
        if not mem_id:
            return
        mem = next((m for m in self.memories if m["id"] == mem_id), None)
        if mem:
            self.push_screen(EditScreen(mem["content"]), lambda r: self._on_edit(mem_id, r))

    @work(exclusive=True)
    async def _on_edit(self, mem_id: str, new_content: str) -> None:
        if not new_content:
            return
        await mm.connect()
        from memory_manager import get_embedding
        import json
        embedding = get_embedding(new_content)
        await mm.pool.execute(
            """
            UPDATE memories_semantic
            SET content = $1, embedding = $2::vector, last_updated = now()
            WHERE id = $3
            """,
            new_content,
            json.dumps(embedding),
            __import__("uuid").UUID(mem_id),
        )
        self.notify("Memory updated", severity="information")
        self.load_memories()

    def action_toggle_archive(self) -> None:
        mem_id = self._get_selected_id()
        if not mem_id:
            return
        mem = next((m for m in self.memories if m["id"] == mem_id), None)
        if not mem:
            return
        if mem.get("archived"):
            self._do_unarchive(mem_id)
        else:
            self._do_archive(mem_id)

    @work(exclusive=True)
    async def _do_archive(self, mem_id: str) -> None:
        await mm.connect()
        await mm.pool.execute(
            "UPDATE memories_semantic SET archived = true WHERE id = $1",
            __import__("uuid").UUID(mem_id),
        )
        self.notify("Archived", severity="information")
        self.load_memories()

    @work(exclusive=True)
    async def _do_unarchive(self, mem_id: str) -> None:
        await mm.connect()
        await mm.unarchive(mem_id)
        self.notify("Restored", severity="information")
        self.load_memories()

    def action_delete(self) -> None:
        mem_id = self._get_selected_id()
        if not mem_id:
            return
        mem = next((m for m in self.memories if m["id"] == mem_id), None)
        if not mem:
            return
        preview = mem["content"][:50]
        self.push_screen(
            ConfirmScreen(f'DELETE: "{preview}..."?'),
            lambda ok: self._on_delete(mem_id, ok),
        )

    @work(exclusive=True)
    async def _on_delete(self, mem_id: str, confirmed: bool) -> None:
        if not confirmed:
            return
        await mm.connect()
        await mm.delete_semantic(mem_id)
        self.notify("Deleted", severity="warning")
        self.load_memories()

    def action_quit(self) -> None:
        self.exit()


if __name__ == "__main__":
    app = MemoryCortex()
    app.run()
