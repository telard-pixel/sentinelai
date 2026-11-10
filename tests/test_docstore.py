import tempfile

import pytest

import docstore
from conftest import esegui


@pytest.fixture
def d():
    return docstore.Client(f"sqlite:///{tempfile.mkdtemp()}")["x"]


def test_inserisci_trova_ordina(d):
    async def f():
        for i in range(5):
            await d.c.insert_one({"id": str(i), "n": i, "cat": "a" if i % 2 else "b"})
        assert await d.c.count_documents({}) == 5
        assert [x["n"] for x in await d.c.find({"cat": "a"}, {"_id": 0}).sort("n", -1).to_list(10)] == [3, 1]
        assert [x["n"] for x in await d.c.find({"n": {"$gte": 3}}, {"_id": 0, "n": 1}).sort("n", 1).to_list(10)] == [3, 4]
        assert (await d.c.find_one({"id": "2"}, {"_id": 0}))["n"] == 2
        assert await d.c.find_one({"id": "99"}) is None
    esegui(f())


def test_aggiornamenti(d):
    async def f():
        await d.c.update_one({"k": "a"}, {"$inc": {"celle.3": 2, "tot": 1}}, upsert=True)
        await d.c.update_one({"k": "a"}, {"$inc": {"celle.3": 1}, "$push": {"lista": "x"}, "$set": {"s": True}}, upsert=True)
        doc = await d.c.find_one({"k": "a"}, {"_id": 0})
        assert doc == {"k": "a", "celle": {"3": 3}, "tot": 1, "lista": ["x"], "s": True}
        await d.c.update_one({"k": "a"}, {"$unset": {"s": ""}})
        assert "s" not in await d.c.find_one({"k": "a"})
        await d.c.replace_one({"k": "a"}, {"k": "a", "nuovo": 1})
        assert await d.c.find_one({"k": "a"}, {"_id": 0}) == {"k": "a", "nuovo": 1}
        assert (await d.c.delete_many({"k": "a"})).deleted_count == 1
    esegui(f())


def test_binari_e_filtri(d):
    async def f():
        await d.c.insert_one({"id": "1", "data": b"\x00\x01video", "file": None})
        await d.c.insert_one({"id": "2", "file": "/x.mp4", "tipo": "zona_sosta"})
        assert bytes((await d.c.find_one({"id": "1"}))["data"]) == b"\x00\x01video"
        assert "data" not in await d.c.find_one({"id": "1"}, {"_id": 0, "data": 0})
        assert [x["id"] for x in await d.c.find({"file": {"$ne": None}}).to_list(9)] == ["2"]
        assert [x["id"] for x in await d.c.find({"tipo": {"$regex": "^zona"}}).to_list(9)] == ["2"]
        assert [x["id"] for x in await d.c.find({"id": {"$in": ["1", "7"]}}).to_list(9)] == ["1"]
    esegui(f())


def test_campo_non_valido_rifiutato(d):
    with pytest.raises(ValueError):
        esegui(d.c.find({"a'); DROP TABLE c;--": 1}).to_list(1))


def test_binari_formato_nuovo_e_righe_vecchie(d):
    import pickle

    async def f():
        await d.c.insert_one({"id": "n", "data": b"nuovo", "altro": b"\x00" * 10})
        riga = d._query("c", 'SELECT bin FROM "c"', [])[0][0]
        assert bytes(riga)[:3] == b"SB1"
        doc = await d.c.find_one({"id": "n"})
        assert doc["data"] == b"nuovo" and doc["altro"] == b"\x00" * 10
        # riga scritta da una versione prima della 1.0.22 (pickle): si legge ancora
        d._exec('INSERT INTO "c" (doc, bin) VALUES (?, ?)', ('{"id": "v"}', pickle.dumps({"data": b"vecchio"})))
        assert (await d.c.find_one({"id": "v"}))["data"] == b"vecchio"
        # un pickle che prova a eseguire qualcosa viene rifiutato
        class Cattivo:
            def __reduce__(self):
                import os
                return (os.system, ("true",))
        d._exec('INSERT INTO "c" (doc, bin) VALUES (?, ?)', ('{"id": "x"}', pickle.dumps({"data": Cattivo()})))
        with pytest.raises(pickle.UnpicklingError):
            await d.c.find_one({"id": "x"})
    esegui(f())
