from hive.graph import Graph
from hive.vault import parse_note


def g_of(crm_vault):
    return Graph.build(crm_vault.load_all())


def test_resolution_aliases_and_ghosts(crm_vault):
    g = g_of(crm_vault)
    assert g.resolve("acme corp") == "clients/Acme.md"
    assert g.resolve("Jane Doe") == "contacts/Jane Doe.md"
    assert "ghost:missing note" in g.nodes
    labels = {(e.source, e.target, e.label) for e in g.edges}
    assert ("contracts/Acme Platform.md", "clients/Acme.md", "client") in labels
    assert ("knowledge/Graph tricks.md", "contracts/Globex Graph.md", "Used in") in labels
    assert ("knowledge/Graph tricks.md", "#graph", "tagged") in labels


def test_pagerank_is_distribution_and_hubs_rank_high(crm_vault):
    g = g_of(crm_vault)
    pr = g.pagerank()
    assert abs(sum(pr.values()) - 1.0) < 1e-6
    assert pr["clients/Acme.md"] > pr["me.md"]


def test_communities_split_clusters():
    notes = [parse_note(t, p) for p, t in [
        ("a.md", "[[b]] [[c]]"), ("b.md", "[[c]]"), ("c.md", ""),
        ("x.md", "[[y]] [[z]]"), ("y.md", "[[z]]"), ("z.md", ""),
    ]]
    comm = Graph.build(notes, include_tags=False).communities()
    assert comm["a.md"] == comm["b.md"] == comm["c.md"]
    assert comm["x.md"] == comm["y.md"] == comm["z.md"]
    assert comm["a.md"] != comm["x.md"]


def test_shortest_path_and_ego(crm_vault):
    g = g_of(crm_vault)
    path = g.shortest_path("contacts/Jane Doe.md", "contracts/Acme Platform.md")
    assert path[0] == "contacts/Jane Doe.md" and path[-1] == "contracts/Acme Platform.md" and len(path) == 3
    ego = g.ego("clients/Acme.md", 1)
    assert {"contacts/Jane Doe.md", "contracts/Acme Platform.md"} <= ego
    assert "clients/Globex.md" not in ego


def test_link_suggestions_are_unlinked_pairs(crm_vault):
    g = g_of(crm_vault)
    sugg = g.suggest_links("contacts/Jane Doe.md")
    targets = [s["b"] for s in sugg]
    assert "contracts/Acme Platform.md" in targets  # shares Acme + the email
    assert all(t not in g.adj["contacts/Jane Doe.md"] for t in targets)


def test_unlinked_mentions(crm_vault):
    g = g_of(crm_vault)
    assert g.unlinked_mentions("contracts/Acme Platform.md") == ["emails/2026-09-22 Hello.md"]


def test_to_json_subset(crm_vault):
    g = g_of(crm_vault)
    data = g.to_json({"clients/Acme.md", "contacts/Jane Doe.md"})
    assert len(data["nodes"]) == 2
    assert data["links"] == [{"source": "contacts/Jane Doe.md", "target": "clients/Acme.md", "label": "org"}]
