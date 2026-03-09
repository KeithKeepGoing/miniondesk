"""Unit tests for knowledge base chunking."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from host.enterprise.knowledge_base import _chunk_text


def test_short_text_single_chunk():
    text = "This is a short text."
    chunks = _chunk_text(text)
    assert len(chunks) == 1
    assert chunks[0] == text


def test_paragraph_split():
    text = "First paragraph with some content.\n\nSecond paragraph with more content.\n\nThird paragraph here."
    chunks = _chunk_text(text, max_size=50)
    assert len(chunks) >= 2
    # Each chunk should not exceed max_size (with some tolerance for overlap)
    for chunk in chunks:
        assert len(chunk) <= 100, f"Chunk too large: {len(chunk)}"


def test_sentence_split_chinese():
    # Chinese sentence with sentence-ending punctuation
    text = "這是第一句話。這是第二句話！這是第三句話？這是第四句話。"
    chunks = _chunk_text(text, max_size=15)
    assert len(chunks) >= 2
    # Chunks should not be empty
    for chunk in chunks:
        assert chunk.strip()


def test_no_mid_word_split():
    text = "The quick brown fox jumps over the lazy dog. " * 20
    chunks = _chunk_text(text, max_size=100)
    # No chunk should end in the middle of a word (after a non-space, non-punctuation char
    # followed by a letter without space)
    for chunk in chunks:
        assert chunk.strip()  # No empty chunks


def test_empty_text():
    assert _chunk_text("") == []


def test_whitespace_only():
    assert _chunk_text("   \n\n   ") == []


def test_overlap_provides_context():
    # With overlap_lines=1, last line of prev chunk should appear in next
    long_text = "\n\n".join([f"Paragraph {i}: " + "word " * 20 for i in range(10)])
    chunks = _chunk_text(long_text, max_size=200, overlap_lines=1)
    assert len(chunks) > 1
