from email.message import EmailMessage

from hive import pipeline
from hive.__main__ import main
from hive.ideas import address, owner_addresses, parse_idea_subject, route_idea_emails
from hive.mail import parse_message, to_note
from hive.vault import Vault


def test_address_handles_hive_style_from():
    assert address("me@home.test <me@home.test>") == "me@home.test"       # no display name: parseaddr gives ''
    assert address("Jane Doe <Jane@Acme.test>") == "jane@acme.test" and address("x@y.test") == "x@y.test"


def test_parse_idea_subject():
    assert parse_idea_subject("Idea: Outbreak graph #aws #Neptune") == ("Outbreak graph", ["aws", "neptune"])
    assert parse_idea_subject("idea - tiny thing") == ("tiny thing", [])
    assert parse_idea_subject("Fwd: Idea: Fwd: Great article") == ("Great article", [])
    assert parse_idea_subject("Bike lanes #idea") == ("Bike lanes", [])
    assert parse_idea_subject("Ideas for the offsite") is None          # 'Ideas' is not the prefix
    assert parse_idea_subject("Re: invoice") is None


def mail(vault, uid, sender, subject, body, forward_of=None):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"], m["Date"] = sender, "hive@x.test", subject, "Sun, 01 Nov 2026 09:00:00 -0600"
    if forward_of:
        body = (f"{body}\n\n---------- Forwarded message ---------\nFrom: {forward_of} <writer@news.test>\n"
                "Date: Sat, Oct 31, 2026 at 8:00 AM\nSubject: Outbreak maps are broken\nTo: me\n\nArticle text here.")
    m.set_content(body)
    rel, meta, text = to_note(parse_message(m.as_bytes()), uid)
    vault.write(rel, meta, text)
    return rel


def test_owner_idea_emails_become_ideas(vault: Vault):
    vault.write("me.md", {"type": "profile", "email": "me@home.test", "other_emails": ["Me <me@work.test>"]}, "# Me\n")
    owner = owner_addresses(vault, ["hive@x.test", None])
    assert owner == {"me@home.test", "me@work.test", "hive@x.test"}
    direct = mail(vault, "1", "Me <me@home.test>", "Idea: Perimenopause MCP #mcp", "Cite DOIs only.\n\nUse NAMS guidelines.")
    fwd = mail(vault, "2", "Me <me@work.test>", "Idea: Fwd: Outbreak maps are broken", "worth building?", forward_of="A Writer")
    stranger = mail(vault, "3", "Spam <x@evil.test>", "Idea: wire me money", "click")
    normal = mail(vault, "4", "Me <me@home.test>", "Lunch Tuesday?", "?")

    made = sorted(route_idea_emails(vault, owner), key=lambda r: "Outbreak" in r)
    assert made == ["library/Ideas/Perimenopause MCP/Perimenopause MCP.md",
                    "library/Ideas/Outbreak maps are broken/Outbreak maps are broken.md"]
    idea = vault.read(made[0])
    assert idea.meta["tags"] == ["idea", "mcp"] and "Use NAMS guidelines." in idea.body
    assert idea.meta["source"] == f"[[{direct.rsplit('/', 1)[1][:-3]}]]"
    f = vault.read(made[1])
    assert "worth building?" in f.body and "Article text here." in f.body   # forwarder's note + the article
    assert vault.read(direct).meta["status"] == "processed"
    assert vault.read(direct).meta["processed_into"] == ["[[Perimenopause MCP]]"]
    assert vault.read(fwd).meta["status"] == "processed"
    assert vault.read(stranger).meta["status"] == "new" and vault.read(normal).meta["status"] == "new"
    assert route_idea_emails(vault, owner) == []                              # processed mail is not re-filed


def test_sync_routes_ideas_before_ingest(vault: Vault, monkeypatch):
    vault.write("me.md", {"type": "profile", "email": "me@home.test"}, "# Me\n")
    mail(vault, "9", "me@home.test", "Idea: Quick one", "body")
    monkeypatch.setattr(pipeline, "gmail_login", lambda: ("hive@x.test", "pw", "test"))
    report = pipeline.sync(vault, fetch=False, push=False, gaps=False)          # nothing left for the agent to ingest
    steps = {s["step"]: s for s in report["steps"]}
    assert steps["ideas"]["result"] == ["library/Ideas/Quick one/Quick one.md"]
    assert steps["ingest"]["result"] == "inbox empty"


def test_cli_idea(vault: Vault, tmp_path, monkeypatch, capsys):
    from hive import __main__ as cli
    monkeypatch.setattr(cli, "load_settings", lambda: type("S", (), {"vault": vault.root})())
    f = tmp_path / "idea.md"
    f.write_text("A **markdown** body.", encoding="utf-8")
    assert main(["idea", "CLI idea", "--file", str(f), "--tags", "a, b"]) == 0
    n = vault.read("library/Ideas/CLI idea/CLI idea.md")
    assert n.meta["tags"] == ["a", "b", "idea"] and "A **markdown** body." in n.body
    assert '"path"' in capsys.readouterr().out
