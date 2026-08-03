"""Tests for the RAG chunking and file text extraction utilities."""
from __future__ import annotations

from app.ai.rag import chunk_text
from app.services.files import _extract_text, _guess_file_type


def test_chunk_text_small_text_is_single_chunk():
    assert chunk_text("hello world", chunk_size=100) == ["hello world"]


def test_chunk_text_empty_returns_none():
    assert chunk_text("") == []
    assert chunk_text("   \n  ") == []


def test_chunk_text_splits_on_size():
    chunks = chunk_text("a" * 500, chunk_size=100, chunk_overlap=10)
    assert len(chunks) > 1
    assert all(len(c) <= 100 for c in chunks)


def test_chunk_text_prefers_sentence_boundary():
    text = " ".join(["This is sentence number %d." % i for i in range(1, 30)])
    chunks = chunk_text(text, chunk_size=120, chunk_overlap=10)
    assert len(chunks) >= 2
    assert all(len(c) <= 120 for c in chunks)


def test_chunk_text_reassembles_content():
    text = ("paragraph one with enough words to fill several chunks here. " * 10) + "final trailing bit."
    chunks = chunk_text(text, chunk_size=80, chunk_overlap=10)
    joined = "".join(chunks)
    assert "paragraph" in joined


def test_extract_text_plain():
    text = _extract_text("readme.md", "text/markdown", b"# Heading\nSome body text")
    assert "# Heading" in text
    assert "Some body text" in text


def test_extract_text_csv():
    text = _extract_text("data.csv", "text/csv", b"name,value\none,1\n")
    assert "name,value" in text


def test_extract_text_json_prettifies():
    text = _extract_text("config.json", "application/json", b'{"a":1,"b":[2,3]}')
    assert '"a": 1' in text


def test_extract_text_utf16():
    content = "héllo wörld".encode("utf-16")
    text = _extract_text("notes.txt", "text/plain", content)
    assert "héllo wörld" in text


def test_extract_text_unknown_returns_empty():
    assert _extract_text("image.bin", "application/octet-stream", b"\x00\x01\x02") == ""


def test_guess_file_type():
    assert _guess_file_type("photo.png", "image/png").value == "image"
    assert _guess_file_type("doc.pdf", "application/pdf").value == "pdf"
    assert _guess_file_type("sheet.csv", "text/csv").value == "spreadsheet"
    assert _guess_file_type("main.py", "text/x-python").value == "code"
    assert _guess_file_type("report.docx", "application/vnd.openxmlformats").value == "document"
    assert _guess_file_type("data.bin", "application/octet-stream").value == "other"
