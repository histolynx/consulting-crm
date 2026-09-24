"""Build a fictional demo vault (outside Google Drive) to explore HIVE without touching real data.

    python scripts/make_demo.py            -> %LOCALAPPDATA%/hive/demo-vault (recreated)
All people and companies here are invented.
"""
from __future__ import annotations

import datetime as dt
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

from hive.pipeline import git_commit, init_vault  # noqa: E402
from hive.timetrack import TimeTracker  # noqa: E402
from hive.vault import Vault, slugify  # noqa: E402

T = dt.date.today()


def d(days: int) -> str:
    return (T + dt.timedelta(days=days)).isoformat()


def weekday_back(n: int) -> str:
    """n-th weekday before today (1 = most recent weekday before today)."""
    day, k = T, 0
    while k < n:
        day -= dt.timedelta(days=1)
        if day.weekday() < 5:
            k += 1
    return day.isoformat()


def build(target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    init_vault(target, ROOT / "vault-template")
    for k, val in (("user.name", "HIVE demo"), ("user.email", "demo@example.com")):
        subprocess.run(["git", "config", "--local", k, val], cwd=target, check=True)
    v = Vault(target)
    W = lambda rel, meta, body: v.write(rel, meta, body, actor="demo", action="seed")  # noqa: E731

    W("me.md", {"type": "profile", "name": "Demo Consultant", "business": "Demo AI Engineering LLC",
                "email": "ai.engineer.demo@example.com", "address": "123 Example St, Springfield",
                "payment_instructions": "ACH: Demo Bank ****1234", "invoice_prefix": "INV", "default_terms_days": 30,
                "tags": ["me"]},
      "# Me\n\nSpecialties: [[GraphRAG Pattern]], [[AWS Bedrock Cost Guardrails]], [[dbt Testing Playbook]].\n")

    # ---- clients
    W("clients/Larkspur Analytics.md", {"type": "client", "status": "active", "industry": "Retail analytics",
      "website": "larkspur.example", "aliases": ["Larkspur"], "tags": ["client", "data-platform"]},
      "# Larkspur Analytics\n\nMid-size retail analytics firm modernising their warehouse. Referred by [[Priya Raman]].\n")
    W("clients/Helio Health.md", {"type": "client", "status": "active", "industry": "Healthcare",
      "website": "heliohealth.example", "tags": ["client", "llm", "hipaa"]},
      "# Helio Health\n\nClinical-notes summarisation with LLMs. Strict #hipaa constraints.\n")
    W("clients/Cobalt Freight.md", {"type": "client", "status": "prospect", "industry": "Logistics",
      "tags": ["client", "graph"]}, "# Cobalt Freight\n\nWants a route/partner knowledge graph.\n")
    W("clients/Juniper Robotics.md", {"type": "client", "status": "prospect", "industry": "Robotics",
      "tags": ["client", "llm"]}, "# Juniper Robotics\n\nInternal docs Q&A agent for field technicians.\n")

    # ---- contacts
    people = [
        ("Maya Chen", "Larkspur Analytics", "VP Data", "maya.chen@larkspur.example", "champion", -3),
        ("Tom Alvarez", "Larkspur Analytics", "Staff Data Engineer", "tom@larkspur.example", "technical", -6),
        ("Dr. Anika Rao", "Helio Health", "CMIO", "arao@heliohealth.example", "decision-maker", -2),
        ("Ben Okafor", "Helio Health", "ML Lead", "ben.okafor@heliohealth.example", "technical", -30),
        ("Sofia Lindqvist", "Cobalt Freight", "COO", "sofia@cobaltfreight.example", "decision-maker", -1),
        ("Marcus Webb", "Juniper Robotics", "Head of Field Ops", "mwebb@juniper.example", "champion", -9),
        ("Priya Raman", "", "Former colleague", "priya.raman@example.com", "referrer", -45),
    ]
    for name, org, role, email, rel, last in people:
        meta = {"type": "contact", "name": name, "org": f"[[{org}]]" if org else "", "role": role, "email": email,
                "relationship": rel, "tags": ["contact"]}
        if last <= -30:
            meta["last_contact"] = d(last)
        body = f"# {name}\n\n{role}" + (f" at [[{org}]]." if org else ".") + "\n"
        if name == "Priya Raman":
            body += "\nReferred [[Larkspur Analytics]] and [[Cobalt Freight]]. Send a thank-you. #warm-lead\n"
        W(f"contacts/{name}.md", meta, body)

    # ---- contracts
    W("contracts/Larkspur Lakehouse Migration.md", {
        "type": "contract", "client": "[[Larkspur Analytics]]", "status": "active", "value": 48000, "rate": 175,
        "rate_unit": "hour", "currency": "USD", "start": d(-40), "end": d(21), "budget_hours": 274,
        "payment_terms_days": 30, "stakeholders": ["[[Maya Chen]]", "[[Tom Alvarez]]"], "tags": ["contract", "data-platform", "aws"]},
      "# Larkspur Lakehouse Migration\n\n## Scope\nMigrate Redshift marts to an Iceberg lakehouse on S3 + Athena; dbt tests.\n"
      "Uses [[dbt Testing Playbook]].\n\n## Tasks\n"
      f"- [ ] Deliver cut-over runbook 📅 {d(2)}\n- [ ] Cost review with [[Maya Chen]] 📅 {d(5)}\n"
      f"- [x] Iceberg POC ✅ {d(-12)}\n")
    W("contracts/Helio Clinical Summarizer.md", {
        "type": "contract", "client": "[[Helio Health]]", "status": "active", "value": 60000, "rate": 1400,
        "rate_unit": "day", "currency": "USD", "start": d(-20), "end": d(70), "budget_hours": 340,
        "stakeholders": ["[[Dr. Anika Rao]]", "[[Ben Okafor]]"], "tags": ["contract", "llm", "hipaa", "aws"]},
      "# Helio Clinical Summarizer\n\n## Scope\nBedrock-based clinical note summarisation with eval harness.\n"
      "Patterns: [[GraphRAG Pattern]], [[AWS Bedrock Cost Guardrails]].\n\n## Tasks\n"
      f"- [ ] Eval set v2 signed off by [[Dr. Anika Rao]] 📅 {d(-1)}\n- [ ] PHI redaction test pass 📅 {d(6)}\n")
    W("contracts/Cobalt Partner Graph.md", {
        "type": "contract", "client": "[[Cobalt Freight]]", "status": "negotiating", "value": 36000, "rate": 180,
        "rate_unit": "hour", "probability": 0.7, "expected_close": d(10), "next_step": "Send revised SOW",
        "stakeholders": ["[[Sofia Lindqvist]]"], "tags": ["contract", "graph"]},
      f"# Cobalt Partner Graph\n\nNeo4j-style partner/route graph. Could reuse [[GraphRAG Pattern]].\n\n- [ ] Send revised SOW 📅 {d(1)}\n")
    W("contracts/Juniper Field Assistant.md", {
        "type": "contract", "client": "[[Juniper Robotics]]", "status": "proposal", "value": 25000, "rate": 12500,
        "rate_unit": "fixed", "probability": 0.4, "expected_close": d(20), "next_step": "Demo call",
        "stakeholders": ["[[Marcus Webb]]"], "tags": ["contract", "llm"],
        "milestones": [{"name": "Discovery + prototype", "amount": 12500, "due": d(35), "status": "planned"},
                       {"name": "Production pilot", "amount": 12500, "due": d(70), "status": "planned"}]},
      "# Juniper Field Assistant\n\nRAG over service manuals for field techs.\n")

    # ---- knowledge
    W("knowledge/GraphRAG Pattern.md", {"type": "note", "tags": ["knowledge", "llm", "graph"]},
      "# GraphRAG Pattern\n\nEntity extraction -> graph -> community summaries -> retrieval by subgraph.\n\n"
      "Used in:: [[Helio Clinical Summarizer]]\nCandidate:: [[Cobalt Partner Graph]]\n")
    W("knowledge/AWS Bedrock Cost Guardrails.md", {"type": "note", "tags": ["knowledge", "aws", "llm"]},
      "# AWS Bedrock Cost Guardrails\n\nBudgets + per-model routing (small model for triage). Used in:: [[Helio Clinical Summarizer]]\n")
    W("knowledge/dbt Testing Playbook.md", {"type": "note", "tags": ["knowledge", "data-platform"]},
      "# dbt Testing Playbook\n\nContracts, unit tests, freshness. Used in:: [[Larkspur Lakehouse Migration]]\n"
      "Mentions Juniper Field Assistant as a possible docs-QA eval source.\n")

    # ---- emails & meetings (drive gap detection + last-contact)
    emails = [
        (weekday_back(1), "Cut-over window", "Maya Chen", "Larkspur Analytics", "Larkspur Lakehouse Migration", True),
        (weekday_back(2), "Iceberg partitioning question", "Tom Alvarez", "Larkspur Analytics", "Larkspur Lakehouse Migration", False),
        (weekday_back(1), "Eval set feedback", "Dr. Anika Rao", "Helio Health", "Helio Clinical Summarizer", True),
        (weekday_back(3), "SOW redlines", "Sofia Lindqvist", "Cobalt Freight", "Cobalt Partner Graph", True),
        (weekday_back(7), "Field assistant demo?", "Marcus Webb", "Juniper Robotics", "Juniper Field Assistant", False),
    ]
    for date, subj, who, client, contract, reply in emails:
        W(f"emails/{date} {slugify(subj)}.md", {"type": "email", "date": date, "from": f"[[{who}]]", "client": f"[[{client}]]",
          "contract": f"[[{contract}]]", "summary": f"{who} wrote about {subj.lower()}.", "needs_reply": reply,
          "tags": ["email"]},
          f"# {subj}\n\n## Summary\n{who} wrote about {subj.lower()}.\n\n## Action items\n- [ ] Reply to [[{who}]] 📅 {d(1)}\n")
    W(f"meetings/{weekday_back(2)} Larkspur weekly.md", {"type": "meeting", "date": weekday_back(2), "duration": 45,
      "attendees": ["[[Maya Chen]]", "[[Tom Alvarez]]"], "client": "[[Larkspur Analytics]]",
      "contract": "[[Larkspur Lakehouse Migration]]", "tags": ["meeting"]}, "# Larkspur weekly\n\nAgreed cut-over plan.\n")
    W(f"meetings/{d(2)} Helio steering.md", {"type": "meeting", "date": d(2), "duration": 60,
      "attendees": ["[[Dr. Anika Rao]]", "[[Ben Okafor]]"], "client": "[[Helio Health]]",
      "contract": "[[Helio Clinical Summarizer]]", "tags": ["meeting"]}, f"# Helio steering\n\n- [ ] Prep eval dashboard 📅 {d(1)}\n")

    # ---- time (leave the most recent Helio day unlogged so gap detection has something to find)
    tt = TimeTracker(v)
    for n in range(2, 12):
        day = weekday_back(n)
        tt.add(day, {"contract": "Larkspur Lakehouse Migration", "start": "09:00", "end": "12:30",
                     "description": "Lakehouse migration work", "source": "demo"}, actor="demo")
        if n % 2 == 0:
            tt.add(day, {"contract": "Helio Clinical Summarizer", "start": "13:30", "end": "17:00",
                         "description": "Eval harness + prompt iterations", "source": "demo"}, actor="demo")
    tt.add(weekday_back(1), {"contract": "Larkspur Lakehouse Migration", "start": "09:00", "end": "11:00",
                             "description": "Cut-over rehearsal", "source": "demo"}, actor="demo")

    W("briefings/" + T.isoformat() + ".md", {"type": "briefing", "date": T.isoformat(), "tags": ["briefing"]},
      "# Briefing\n\n## TL;DR\n- Demo vault: run **Brief** to have Claude write a real briefing.\n"
      "- [[Cobalt Partner Graph]] SOW redlines are waiting.\n- [[Ben Okafor]] has gone cold (30 days).\n")
    git_commit(v, "demo seed")
    print(f"demo vault ready: {target}")


if __name__ == "__main__":
    build(Path(os.environ.get("LOCALAPPDATA", Path.home())) / "hive" / "demo-vault")
