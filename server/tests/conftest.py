import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hive.vault import Vault  # noqa: E402


@pytest.fixture
def vault(tmp_path: Path) -> Vault:
    return Vault(tmp_path / "vault")


def write(v: Vault, rel: str, text: str) -> None:
    p = v.root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


@pytest.fixture
def crm_vault(vault: Vault) -> Vault:
    """Small realistic graph: two clients, contacts, contracts, an email and a knowledge note."""
    write(vault, "me.md", "---\ntype: profile\nname: Me\ninvoice_prefix: INV\ndefault_terms_days: 15\n---\n# Me\n")
    write(vault, "clients/Acme.md", "---\ntype: client\naliases: [Acme Corp]\n---\n# Acme\n")
    write(vault, "clients/Globex.md", "---\ntype: client\n---\n# Globex\n")
    write(vault, "contacts/Jane Doe.md", '---\ntype: contact\norg: "[[Acme]]"\nemail: jane@acme.test\n---\n# Jane\n')
    write(vault, "contacts/Hank Scorpio.md", '---\ntype: contact\norg: "[[Globex]]"\nlast_contact: 2026-01-01\n---\n# Hank\n')
    write(vault, "contracts/Acme Platform.md",
          '---\ntype: contract\nclient: "[[Acme Corp]]"\nstatus: active\nrate: 150\nrate_unit: hour\nvalue: 30000\n'
          'budget_hours: 10\nend: 2026-10-10\n---\n# Acme Platform\n- [ ] Send SOW 📅 2026-09-25\n- [x] Kickoff\n')
    write(vault, "contracts/Globex Graph.md",
          '---\ntype: contract\nclient: "[[Globex]]"\nstatus: negotiating\nvalue: 20000\nrate: 1000\nrate_unit: day\n---\n# Globex Graph\n')
    write(vault, "emails/2026-09-22 Hello.md",
          '---\ntype: email\ndate: 2026-09-22\nfrom: "[[Jane Doe]]"\n---\n# Hello\nAbout Acme Platform scope.\n')
    write(vault, "knowledge/Graph tricks.md", "---\ntype: note\n---\nUsed in:: [[Globex Graph]]\nSee [[Missing Note]] #graph\n")
    return vault
