from email.message import EmailMessage

from hive.mail import html_to_text, parse_message, to_note, unwrap_forward

GMAIL_FWD = """Please log this one.

---------- Forwarded message ---------
From: Jane Doe <Jane@Acme.test>
Date: Tue, Sep 22, 2026 at 10:15 AM
Subject: Re: SOW v2
To: Me <me@gmail.com>
Cc: Bob <bob@acme.test>

Hi! Rate of $150/h works. Start Oct 1.
"""

OUTLOOK_FWD = """FYI

________________________________
From: Sofia Lindqvist <sofia@cobalt.test>
Sent: Monday, September 21, 2026 3:02 PM
To: Me <me@gmail.com>
Subject: Redlines

See attached.
"""


def test_unwrap_gmail_forward():
    f = unwrap_forward(GMAIL_FWD)
    assert f["from_email"] == "jane@acme.test" and f["from_name"] == "Jane Doe"
    assert f["subject"] == "Re: SOW v2" and f["cc"] == "Bob <bob@acme.test>"
    assert f["note"] == "Please log this one."
    assert f["body"].startswith("Hi! Rate of $150/h")


def test_unwrap_outlook_forward():
    f = unwrap_forward(OUTLOOK_FWD)
    assert f["from_email"] == "sofia@cobalt.test" and f["date_raw"].startswith("Monday")
    assert f["body"] == "See attached."


def test_not_a_forward():
    assert unwrap_forward("just a normal email\nFrom: nobody") is None


def _msg(body: str, attach: bool = False) -> bytes:
    m = EmailMessage()
    m["From"] = "Me Personal <me@gmail.com>"
    m["To"] = "ai.engineer@example.com"
    m["Subject"] = "Fwd: Re: SOW v2"
    m["Date"] = "Wed, 23 Sep 2026 08:00:00 -0500"
    m["Message-ID"] = "<abc@mail>"
    m.set_content(body)
    if attach:
        m.add_attachment(b"%PDF-1.4 fake", maintype="application", subtype="pdf", filename="SOW v2.pdf")
    return m.as_bytes()


def test_parse_forwarded_message_to_note():
    parsed = parse_message(_msg(GMAIL_FWD, attach=True))
    assert parsed["attachments"][0][0] == "SOW v2.pdf"
    rel, meta, body = to_note(parsed, "42")
    assert meta["from"] == "Jane Doe <jane@acme.test>" and meta["forwarded"] is True
    assert meta["forwarded_by"] == "Me Personal <me@gmail.com>"
    assert meta["date"] == "2026-09-22" and meta["subject"] == "Re: SOW v2" and meta["status"] == "new"
    assert rel == "inbox/2026-09-22 Re SOW v2 (42).md"
    assert "Forwarder's note" in body and "Rate of $150/h" in body


def test_direct_message_to_note():
    m = EmailMessage()
    m["From"] = "Client <c@x.test>"
    m["Subject"] = "Hello"
    m["Date"] = "Wed, 23 Sep 2026 08:00:00 -0500"
    m.add_alternative("<p>Hi<br>there &amp; you</p>", subtype="html")
    rel, meta, body = to_note(parse_message(m.as_bytes()), "7")
    assert meta["from"] == "Client <c@x.test>" and meta["forwarded"] is False and meta["date"] == "2026-09-23"
    assert "Hi\nthere & you" in body


def test_html_to_text_strips_scripts():
    assert html_to_text("<style>x{}</style><ul><li>a</li><li>b</li></ul>") == "- a\n- b"
