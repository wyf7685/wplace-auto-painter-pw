from pathlib import Path

import pytest

from app.exception import ResolveFailed
from app.wplace.resolver import Chunks, find_patch_version


def make_chunks(tmp_path: Path, source: str) -> Chunks:
    root = tmp_path / "chunks"
    chunk_dir = root / "chunks"
    chunk_dir.mkdir(parents=True)
    (chunk_dir / "fixture.js").write_text(source, encoding="utf-8")
    return Chunks(root)


def test_find_patch_version_uses_markdown_map_and_numeric_order(tmp_path: Path) -> None:
    chunks = make_chunks(
        tmp_path,
        """
        const releaseProse = "See ./markdown/99.99.99.md; version 99.99.99 is mentioned here.";
        const unrelated = { version: "100.0.0" };
        var renamedResult = renamedHelper(Object.entries(Object.assign({
            './markdown/1.9.9 - Earlier.md': earlierPatch,
            "./markdown/1.10.0 - Latest.md": latestPatch
        })));
        """,
    )

    assert find_patch_version(chunks) == "1.10.0"


def test_find_patch_version_accepts_declaration_start_and_single_entry_map(tmp_path: Path) -> None:
    chunks = make_chunks(
        tmp_path,
        """
        var arbitraryResult = arbitraryHelper(Object.assign({
            `./markdown/1.7.5 - WPlace.md`: patchModule,
          }
        }));
        """,
    )

    assert find_patch_version(chunks) == "1.7.5"


def test_find_patch_version_ignores_quoted_map_examples(tmp_path: Path) -> None:
    chunks = make_chunks(
        tmp_path,
        r"""
        const example = `Object.assign({"./markdown/99.0.0.md": prose})`;
        const patches = Object.assign({
            "./markdown/1.7.5 - \"Quoted\" title.md": patch
        });
        """,
    )

    assert find_patch_version(chunks) == "1.7.5"


@pytest.mark.parametrize(
    "source",
    [
        'const release = "version 1.7.5";',
        'const unrelated = Object.assign({"./other/1.7.5.md": patch});',
        'const malformed = Object.assign({"./markdown/not-a-version.md": patch});',
        'const malformed = Object.assign({"./markdown/1.7.md": patch});',
    ],
)
def test_find_patch_version_rejects_missing_or_malformed_sources(tmp_path: Path, source: str) -> None:
    with pytest.raises(ResolveFailed):
        find_patch_version(make_chunks(tmp_path, source))
