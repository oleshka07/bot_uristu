"""Semantic search: embedding, cosine ranking, and NL-search routing."""


def _contact(db, name, **kw):
    from app.modules.contacts.models import Contact

    c = Contact(first_name=name, **kw)
    db.add(c); db.commit(); db.refresh(c)
    return c


def test_embed_pending_and_semantic_rank(client, monkeypatch):
    from app.core.database import SessionLocal
    from app.modules.search import service as ss

    # Fake embeddings: map keyword → axis so cosine is deterministic.
    def fake_embed(texts, input_type="document"):
        vecs = []
        for t in texts:
            low = t.lower()
            vecs.append([
                1.0 if "crypto" in low or "блокчейн" in low else 0.0,
                1.0 if "surf" in low or "серф" in low else 0.0,
                0.1,
            ])
        return vecs

    monkeypatch.setattr("app.modules.insights.llm.embeddings_enabled", lambda: True)
    monkeypatch.setattr("app.modules.insights.llm.embeddings_model", lambda: "test")
    monkeypatch.setattr("app.modules.insights.llm.embed", fake_embed)

    with SessionLocal() as db:
        crypto = _contact(db, "Cryptoguy", notes="deep into crypto and blockchain")
        surfer = _contact(db, "Surfer", notes="loves surf and the ocean")

        n = ss.embed_pending(db)
        assert n == 2
        assert ss.pending_count(db) == 0

        hits = ss.semantic_search(db, "хто шарить у crypto?", k=5)
        assert hits and hits[0][0] == crypto.id  # crypto contact ranks first


def test_semantic_search_empty_without_embeddings(client, monkeypatch):
    from app.core.database import SessionLocal
    from app.modules.search import service as ss

    monkeypatch.setattr("app.modules.insights.llm.embeddings_enabled", lambda: False)
    with SessionLocal() as db:
        assert ss.semantic_search(db, "anything") == []
        assert ss.embed_pending(db) == 0
