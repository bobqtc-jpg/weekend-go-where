"""Tests for adding emailed digests to the inbox. Every name and URL here is made up."""
import json

import pytest

import refresh.add_article as add_mod

DIGEST = """Test toddler digest - week of 2026-11-10
This weekend
- Test Puppet Hour | 2026-11-14 | 10:00-11:00 | Test Library | Price: Free | Ages: 2-3 | Booking status: Open | Source: https://example.com/p/1
"""


@pytest.fixture
def inbox(tmp_path, monkeypatch):
    monkeypatch.setattr(add_mod, "ARTICLES_DIR", tmp_path / "articles")
    monkeypatch.setattr(add_mod, "MANIFEST_FILE", tmp_path / "manifest.json")
    monkeypatch.setattr(add_mod, "SEEN_FILE", tmp_path / "seen.json")
    return tmp_path


def test_adds_article_and_manifest_entry(inbox):
    key = add_mod.add_article("muse", "Test digest week of 2026-11-10", "https://mail.example.com/t/1", "2026-11-11", DIGEST)
    assert key == "muse__test-digest-week-of-2026-11-10"
    article = json.loads((inbox / "articles" / f"{key}.json").read_text())
    assert article["source_id"] == "muse" and "Test Puppet Hour" in article["text"]
    manifest = json.loads((inbox / "manifest.json").read_text())
    assert manifest[key]["url"] == "https://mail.example.com/t/1"


def test_keeps_articles_already_in_the_manifest(inbox):
    (inbox / "manifest.json").write_text(json.dumps({"bykido__x": {"url": "https://example.com/x"}}))
    add_mod.add_article("muse", "Digest", "https://mail.example.com/t/2", None, DIGEST)
    assert set(json.loads((inbox / "manifest.json").read_text())) == {"bykido__x", "muse__digest"}


def test_skips_text_already_merged(inbox):
    url = "https://mail.example.com/t/3"
    from refresh.common import content_hash

    (inbox / "seen.json").write_text(json.dumps({url: {"hash": content_hash(DIGEST.strip())}}))
    assert add_mod.add_article("muse", "Digest", url, None, DIGEST) is None
    assert add_mod.add_article("muse", "Digest", url, None, DIGEST, force=True) == "muse__digest"


def test_rejects_bad_input(inbox):
    with pytest.raises(ValueError):
        add_mod.add_article("muse", "Digest", "mailto:someone", None, DIGEST)
    with pytest.raises(ValueError):
        add_mod.add_article("muse", "Digest", "https://mail.example.com/t/4", "11 Nov", DIGEST)
    with pytest.raises(ValueError):
        add_mod.add_article("muse", "Digest", "https://mail.example.com/t/5", None, "   ")
