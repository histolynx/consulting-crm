import pytest

from hive.vault import Vault, extract_tasks, parse_note, render_note, slugify, split_frontmatter


def test_frontmatter_roundtrip():
    text = render_note({"type": "contact", "org": "[[Acme]]", "tags": ["a"]}, "# Hi\n")
    meta, body = split_frontmatter(text)
    assert meta == {"type": "contact", "org": "[[Acme]]", "tags": ["a"]}
    assert body == "# Hi\n"


def test_bad_yaml_is_reported_not_raised():
    meta, _ = split_frontmatter("---\nfoo: [unclosed\n---\nbody")
    assert "_yaml_error" in meta


def test_links_are_typed_by_location():
    n = parse_note(
        '---\ntype: contract\nclient: "[[Acme]]"\nstakeholders: ["[[Jane]]", "[[Bob|Bobby]]"]\n'
        'entries:\n  - contract: "[[X]]"\n---\n'
        "Plain [[Mention]] and [[Heading#Section]].\nused_in:: [[Proj]]\n```\n[[InCode]]\n```\n`[[Inline]]`\n",
        "contracts/c.md",
    )
    got = {(l.target, l.label) for l in n.links}
    assert ("Acme", "client") in got
    assert ("Jane", "stakeholders") in got and ("Bob", "stakeholders") in got
    assert ("X", "contract") in got  # nested list-of-dicts uses inner key
    assert ("Mention", "mentions") in got and ("Heading", "mentions") in got
    assert ("Proj", "used_in") in got
    assert not any(t in ("InCode", "Inline") for t, _ in got)


def test_tags_from_frontmatter_and_body_but_not_headings_or_code():
    n = parse_note("---\ntags: [Client, data-platform]\n---\n# Heading\nText #warm-lead and #aws/bedrock `#nope` c#sharp\n", "a.md")
    assert n.tags == ["client", "data-platform", "warm-lead", "aws/bedrock"]


def test_tasks_with_due_dates():
    ts = extract_tasks("- [ ] Send SOW 📅 2026-10-01\n- [x] Done thing\n* [ ] due:: 2026-11-02 other\nnot a task")
    assert [(t.done, t.due) for t in ts] == [(False, "2026-10-01"), (True, None), (False, "2026-11-02")]


def test_slugify_keeps_readable_names():
    assert slugify('Re: SOW "v2" / final?') == "Re SOW v2 final"


def test_safe_path_blocks_escape(vault: Vault):
    with pytest.raises(ValueError):
        vault.safe_path("../outside.md")


def test_write_audits_and_unique_path(vault: Vault):
    vault.write("contacts/A.md", {"type": "contact"}, "# A")
    assert vault.unique_path("contacts", "A") == "contacts/A 2.md"
    log = vault.read_audit()
    assert log[0]["target"] == "contacts/A.md" and log[0]["actor"] == "ui"


def test_hidden_and_template_dirs_skipped(vault: Vault):
    vault.write("_templates/t.md", {"type": "x"}, "")
    vault.write(".hive/x.md", {"type": "x"}, "")
    vault.write("_intake/unprocessed.md", {"type": "x"}, "")
    vault.write("notes/real.md", {"type": "note"}, "")
    vault.write("CLAUDE.md", {"type": "system"}, 'org: "[[Client]]"')
    assert [n.path for n in vault.load_all()] == ["notes/real.md"]
