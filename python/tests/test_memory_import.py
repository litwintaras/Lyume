import pytest
import tempfile
import os
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock
from memory_import import scan_markdown_files, parse_blocks, ImportPipeline


def test_scan_finds_md_files():
    """scan_markdown_files() finds .md and .mdc files."""
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "notes.md").write_text("# Hello")
        (Path(d) / "rules.mdc").write_text("---\nrule: test\n---")
        (Path(d) / "readme.txt").write_text("ignore me")
        (Path(d) / "sub").mkdir()
        (Path(d) / "sub" / "deep.md").write_text("# Deep")

        files = scan_markdown_files(d)
        assert len(files) == 3
        names = {f.name for f in files}
        assert "notes.md" in names
        assert "rules.mdc" in names
        assert "deep.md" in names


def test_parse_blocks_by_headers():
    """parse_blocks() splits markdown by ## headers."""
    content = """# Main Title

Some intro text.

## Section One

Content of section one.

## Section Two

Content of section two.
"""
    blocks = parse_blocks(content)
    assert len(blocks) == 3  # intro + section one + section two
    assert "intro text" in blocks[0]
    assert "section one" in blocks[1].lower()
    assert "section two" in blocks[2].lower()


def test_parse_blocks_by_separator():
    """parse_blocks() splits by --- if no headers found."""
    content = """First block of text.

---

Second block of text.

---

Third block of text.
"""
    blocks = parse_blocks(content)
    assert len(blocks) == 3


def test_parse_blocks_single():
    """parse_blocks() returns whole content if no separators."""
    content = "Just a single paragraph of memory."
    blocks = parse_blocks(content)
    assert len(blocks) == 1
    assert blocks[0] == content


def test_parse_blocks_skips_empty():
    """parse_blocks() skips empty blocks."""
    content = """## Header

Content here.

##

## Another

More content.
"""
    blocks = parse_blocks(content)
    assert all(b.strip() for b in blocks)


@pytest.mark.asyncio
async def test_import_pipeline_dedup():
    """ImportPipeline skips blocks with similarity > 0.9 to existing memories."""
    mock_mm = AsyncMock()
    mock_mm.search_semantic = AsyncMock(return_value=[{"similarity": 0.95, "content": "existing"}])

    mock_embed = AsyncMock()
    mock_embed.embed = AsyncMock(return_value=[0.1] * 768)

    pipeline = ImportPipeline(memory_manager=mock_mm, embedding_client=mock_embed)

    result = await pipeline.import_block("duplicate content", source="test.md")
    assert result == "duplicate"


@pytest.mark.asyncio
async def test_import_pipeline_saves_new():
    """ImportPipeline saves blocks with no similar existing memories."""
    mock_mm = AsyncMock()
    mock_mm.search_semantic = AsyncMock(return_value=[])
    mock_mm.save_semantic = AsyncMock()

    mock_embed = AsyncMock()
    mock_embed.embed = AsyncMock(return_value=[0.1] * 768)

    pipeline = ImportPipeline(memory_manager=mock_mm, embedding_client=mock_embed)

    result = await pipeline.import_block("brand new memory", source="test.md")
    assert result == "imported"
    mock_mm.save_semantic.assert_called_once()
