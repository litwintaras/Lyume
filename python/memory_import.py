"""Import memory from external AI agent markdown files into Lyume DB."""

import re
from pathlib import Path


def scan_markdown_files(directory: str) -> list[Path]:
    """Recursively find all .md and .mdc files in directory."""
    root = Path(directory)
    files = []
    for pattern in ("**/*.md", "**/*.mdc"):
        files.extend(root.glob(pattern))
    return sorted(set(files))


def parse_blocks(content: str) -> list[str]:
    """Split markdown content into logical blocks."""
    # Try splitting by ## headers first
    header_parts = re.split(r"(?=^## )", content, flags=re.MULTILINE)
    if len(header_parts) > 1:
        blocks = [p.strip() for p in header_parts if p.strip()]
        return [b for b in blocks if b]

    # Try splitting by --- separators
    sep_parts = re.split(r"^---+$", content, flags=re.MULTILINE)
    if len(sep_parts) > 1:
        blocks = [p.strip() for p in sep_parts if p.strip()]
        return [b for b in blocks if b]

    # Return whole content as single block
    stripped = content.strip()
    return [stripped] if stripped else []


class ImportPipeline:
    """Import parsed memory blocks into Lyume database."""

    def __init__(self, memory_manager, embedding_client, dedup_threshold: float = 0.9):
        self._mm = memory_manager
        self._embed = embedding_client
        self._threshold = dedup_threshold

    async def import_block(self, text: str, source: str = "") -> str:
        """Import a single block. Returns 'imported', 'duplicate', or 'error'."""
        try:
            embedding = await self._embed.embed(text)

            # Check for duplicates
            existing = await self._mm.search_semantic(
                query=text, limit=1, embedding=embedding
            )
            if existing and existing[0].get("similarity", 0) > self._threshold:
                return "duplicate"

            # Save as semantic memory
            await self._mm.save_semantic(
                content=text,
                category="imported",
                source_info={"file": source, "type": "import"},
            )
            return "imported"
        except Exception:
            return "error"

    async def import_file(self, file_path: Path) -> dict:
        """Import all blocks from a single file. Returns stats."""
        content = file_path.read_text(encoding="utf-8", errors="replace")
        blocks = parse_blocks(content)
        stats = {"imported": 0, "duplicate": 0, "error": 0, "total": len(blocks)}

        for block in blocks:
            if len(block.strip()) < 10:  # skip tiny blocks
                stats["total"] -= 1
                continue
            result = await self.import_block(block, source=str(file_path))
            stats[result] += 1

        return stats

    async def import_directory(self, directory: str) -> dict:
        """Import all markdown files from directory. Returns aggregate stats."""
        files = scan_markdown_files(directory)
        total = {"files": len(files), "imported": 0, "duplicate": 0, "error": 0, "total": 0}

        for f in files:
            stats = await self.import_file(f)
            for key in ("imported", "duplicate", "error", "total"):
                total[key] += stats[key]

        return total
