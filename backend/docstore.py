"""Database a documenti su un file SQLite, con la parte dell'interfaccia di Motor (MongoDB) usata da SentinelAI.

Serve alla versione Windows (05/11/2026): niente server MongoDB da installare, tutto in un file.
Ogni collezione è una tabella (doc JSON + campi binari a parte); i filtri diventano SQL su json_extract.
Operatori supportati: uguaglianza, $gt/$gte/$lt/$lte/$ne/$in, $regex solo come prefisso ("^...").
Aggiornamenti: $set, $inc (anche su percorsi con il punto), $push, $setOnInsert; upsert.
Limiti noti (06/11/2026, agente di prova; server.py non li usa): l'uguaglianza su un campo lista non cerca
dentro la lista; i bytes sono ammessi solo al primo livello; niente NaN/Infinito."""
import asyncio
import copy
import json
import os
import pickle
import re
import sqlite3
import threading
import uuid
from types import SimpleNamespace

_FIELD = re.compile(r"^[A-Za-z0-9_.]+$")


def _path(field: str) -> str:
    if not _FIELD.fullmatch(field):
        raise ValueError(f"campo non valido: {field!r}")
    return "$." + field


def _jx(field: str) -> str:
    return f"json_extract(doc, '{_path(field)}')"


def _param(v):
    if isinstance(v, bool):
        return int(v)
    return v


def _where(flt: dict, args: list) -> str:
    parts = []
    for field, cond in (flt or {}).items():
        col = _jx(field)
        if isinstance(cond, dict) and any(k.startswith("$") for k in cond):
            for op, v in cond.items():
                if op in ("$gt", "$gte", "$lt", "$lte"):
                    parts.append(f"{col} {dict(zip(('$gt', '$gte', '$lt', '$lte'), ('>', '>=', '<', '<=')))[op]} ?")
                    args.append(_param(v))
                elif op == "$ne":
                    if v is None:
                        parts.append(f"{col} IS NOT NULL")
                    else:
                        parts.append(f"({col} IS NULL OR {col} != ?)")
                        args.append(_param(v))
                elif op == "$in":
                    vals = [x for x in v if x is not None]
                    sub = []
                    if vals:
                        sub.append(f"{col} IN ({','.join('?' * len(vals))})")
                        args.extend(_param(x) for x in vals)
                    if len(vals) != len(v):
                        sub.append(f"{col} IS NULL")
                    parts.append("(" + " OR ".join(sub or ["0"]) + ")")
                elif op == "$regex":
                    if not (isinstance(v, str) and v.startswith("^") and re.fullmatch(r"\^[\w\- ]*", v)):
                        raise NotImplementedError(f"$regex supportato solo come prefisso semplice: {v!r}")
                    # come MongoDB: maiuscole e minuscole contano (LIKE invece non le distingueva)
                    parts.append(f"(typeof({col}) = 'text' AND substr({col}, 1, ?) = ?)")
                    args.extend([len(v) - 1, v[1:]])
                else:
                    raise NotImplementedError(f"operatore non supportato: {op}")
        elif cond is None:
            parts.append(f"{col} IS NULL")
        elif isinstance(cond, (dict, list)):
            raise NotImplementedError("uguaglianza su oggetti o liste non supportata")
        else:
            parts.append(f"{col} = ?")
            args.append(_param(cond))
    return " AND ".join(parts) if parts else "1"


def _json_default(v):
    if isinstance(v, (bytes, bytearray, memoryview)):
        raise ValueError("bytes ammessi solo al primo livello del documento")
    return str(v)   # datetime e simili


def _split(doc: dict):
    """I bytes non stanno nel JSON: vanno nella colonna binaria (solo campi di primo livello)."""
    plain = {k: v for k, v in doc.items() if not isinstance(v, (bytes, bytearray, memoryview))}
    binary = {k: bytes(v) for k, v in doc.items() if isinstance(v, (bytes, bytearray, memoryview))}
    return json.dumps(plain, ensure_ascii=False, default=_json_default, allow_nan=False), (pickle.dumps(binary) if binary else None)


def _join(doc_json: str, blob) -> dict:
    doc = json.loads(doc_json)
    if blob:
        doc.update(pickle.loads(blob))
    return doc


def _project(doc: dict, projection):
    if not projection:
        return doc
    inc = {k for k, v in projection.items() if v and k != "_id"}
    exc = {k for k, v in projection.items() if not v and k != "_id"}
    if not inc and not exc and projection.get("_id"):
        return {"_id": doc["_id"]} if "_id" in doc else {}   # {"_id": 1}: solo l'_id, come MongoDB
    if inc:
        out = {k: doc[k] for k in inc if k in doc}
        if projection.get("_id", 1) and "_id" in doc:
            out["_id"] = doc["_id"]
        return out
    out = {k: v for k, v in doc.items() if k not in exc}
    if projection.get("_id", 1) == 0:
        out.pop("_id", None)
    return out


def _needs_blob(projection) -> bool:
    if not projection:
        return True
    inc = {k for k, v in projection.items() if v and k != "_id"}
    if inc:
        return "data" in inc
    return projection.get("data", 1) != 0


def _get_parent(doc: dict, dotted: str, create: bool):
    keys = dotted.split(".")
    cur = doc
    for k in keys[:-1]:
        if k not in cur or not isinstance(cur[k], dict):
            if not create:
                return None, keys[-1]
            cur[k] = {}
        cur = cur[k]
    return cur, keys[-1]


def _apply(doc: dict, update: dict, inserting: bool) -> dict:
    if not any(k.startswith("$") for k in update):
        raise ValueError("update senza operatori: usare replace_one")
    for op, fields in update.items():
        if op == "$setOnInsert" and not inserting:
            continue
        for k, v in fields.items():
            parent, last = _get_parent(doc, k, create=True)
            if op in ("$set", "$setOnInsert"):
                parent[last] = v
            elif op == "$inc":
                parent[last] = (parent.get(last) or 0) + v
            elif op == "$push":
                parent.setdefault(last, []).append(v)
            elif op == "$unset":
                parent.pop(last, None)
            else:
                raise NotImplementedError(f"update non supportato: {op}")
    return doc


class _Cursor:
    def __init__(self, coll, flt, projection):
        self.coll, self.flt, self.projection = coll, flt, projection
        self._sort, self._limit = None, 0

    def sort(self, key, direction=1):
        self._sort = (key, direction)
        return self

    def limit(self, n):
        self._limit = int(n or 0)
        return self

    def _run(self, length=None):
        args: list = []
        cols = "doc, bin" if _needs_blob(self.projection) else "doc, NULL"
        sql = f'SELECT {cols} FROM "{self.coll.name}" WHERE {_where(self.flt, args)}'
        if self._sort:
            key, d = self._sort
            sql += f" ORDER BY {_jx(key)} {'DESC' if d in (-1, 'desc') else 'ASC'}, rowid {'DESC' if d in (-1, 'desc') else 'ASC'}"
        n = min(x for x in (self._limit, length or 0) if x) if (self._limit or length) else 0
        if n:
            sql += f" LIMIT {int(n)}"
        rows = self.coll.db._query(self.coll.name, sql, args)
        return [_project(_join(d, b), self.projection) for d, b in rows]

    async def to_list(self, length=None):
        return await asyncio.to_thread(self._run, length)

    def __aiter__(self):
        async def gen():
            for d in await self.to_list(None):
                yield d
        return gen()


class Collection:
    def __init__(self, db, name):
        self.db, self.name = db, name
        db._ensure_table(name)

    # --- lettura
    def find(self, flt=None, projection=None):
        return _Cursor(self, flt or {}, projection)

    async def find_one(self, flt=None, projection=None):
        rows = await _Cursor(self, flt or {}, projection).limit(1).to_list(1)
        return rows[0] if rows else None

    async def count_documents(self, flt=None):
        def run():
            args: list = []
            return self.db._query(self.name, f'SELECT COUNT(*) FROM "{self.name}" WHERE {_where(flt, args)}', args)[0][0]
        return await asyncio.to_thread(run)

    # --- scrittura
    async def insert_one(self, doc):
        doc = dict(doc)
        doc.setdefault("_id", uuid.uuid4().hex)
        j, b = _split(doc)
        try:
            await asyncio.to_thread(self.db._exec, f'INSERT INTO "{self.name}" (doc, bin) VALUES (?, ?)', (j, b))
        except sqlite3.IntegrityError as exc:
            try:
                from pymongo.errors import DuplicateKeyError
            except ImportError:
                raise
            raise DuplicateKeyError(str(exc)) from exc
        return SimpleNamespace(inserted_id=doc["_id"])

    def _matching(self, flt, one):
        args: list = []
        sql = f'SELECT rowid, doc, bin FROM "{self.name}" WHERE {_where(flt, args)}' + (" LIMIT 1" if one else "")
        return self.db._query(self.name, sql, args)

    def _seed(self, flt):
        doc: dict = {}
        for k, v in (flt or {}).items():
            if not isinstance(v, dict):
                parent, last = _get_parent(doc, k, create=True)   # "a.b" -> {"a": {"b": ...}} come MongoDB
                parent[last] = copy.deepcopy(v)
        return doc

    def _update(self, flt, update, upsert, one):
        with self.db._lock:
            rows = self._matching(flt, one)
            if not rows:
                if not upsert:
                    return SimpleNamespace(matched_count=0, modified_count=0, upserted_id=None)
                doc = _apply(self._seed(flt), update, inserting=True)
                doc.setdefault("_id", uuid.uuid4().hex)
                j, b = _split(doc)
                self.db._conn.execute(f'INSERT INTO "{self.name}" (doc, bin) VALUES (?, ?)', (j, b))
                self.db._conn.commit()
                return SimpleNamespace(matched_count=0, modified_count=0, upserted_id=doc["_id"])
            for rowid, d, bl in rows:
                doc = _apply(_join(d, bl), update, inserting=False)
                j, b = _split(doc)
                self.db._conn.execute(f'UPDATE "{self.name}" SET doc = ?, bin = ? WHERE rowid = ?', (j, b, rowid))
            self.db._conn.commit()
            return SimpleNamespace(matched_count=len(rows), modified_count=len(rows), upserted_id=None)

    async def update_one(self, flt, update, upsert=False):
        return await asyncio.to_thread(self._update, flt, update, upsert, True)

    async def update_many(self, flt, update, upsert=False):
        return await asyncio.to_thread(self._update, flt, update, upsert, False)

    def _replace(self, flt, doc, upsert):
        with self.db._lock:
            rows = self._matching(flt, True)
            new = dict(doc)
            if rows:
                old_id = json.loads(rows[0][1]).get("_id")
                new.setdefault("_id", old_id)
                j, b = _split(new)
                self.db._conn.execute(f'UPDATE "{self.name}" SET doc = ?, bin = ? WHERE rowid = ?', (j, b, rows[0][0]))
                self.db._conn.commit()
                return SimpleNamespace(matched_count=1, modified_count=1, upserted_id=None)
            if not upsert:
                return SimpleNamespace(matched_count=0, modified_count=0, upserted_id=None)
            new = {**self._seed(flt), **new}
            new.setdefault("_id", uuid.uuid4().hex)
            j, b = _split(new)
            self.db._conn.execute(f'INSERT INTO "{self.name}" (doc, bin) VALUES (?, ?)', (j, b))
            self.db._conn.commit()
            return SimpleNamespace(matched_count=0, modified_count=0, upserted_id=new["_id"])

    async def replace_one(self, flt, doc, upsert=False):
        return await asyncio.to_thread(self._replace, flt, doc, upsert)

    def _delete(self, flt, one):
        with self.db._lock:
            args: list = []
            where = _where(flt, args)
            if one:
                sql = f'DELETE FROM "{self.name}" WHERE rowid IN (SELECT rowid FROM "{self.name}" WHERE {where} LIMIT 1)'
            else:
                sql = f'DELETE FROM "{self.name}" WHERE {where}'
            n = self.db._conn.execute(sql, args).rowcount
            self.db._conn.commit()
            return SimpleNamespace(deleted_count=n)

    async def delete_one(self, flt):
        return await asyncio.to_thread(self._delete, flt, True)

    async def delete_many(self, flt):
        return await asyncio.to_thread(self._delete, flt, False)

    async def create_indexes(self, models):
        def run():
            for m in models:
                d = m.document
                keys = list(d["key"].keys())
                name = re.sub(r"\W", "_", f"{self.name}_{d.get('name', '_'.join(keys))}")
                cols = ", ".join(_jx(k) for k in keys)
                unique = "UNIQUE " if d.get("unique") else ""
                try:
                    self.db._exec(f'CREATE {unique}INDEX IF NOT EXISTS "{name}" ON "{self.name}" ({cols})', ())
                except sqlite3.IntegrityError:
                    self.db._exec(f'CREATE INDEX IF NOT EXISTS "{name}" ON "{self.name}" ({cols})', ())
            return [m.document.get("name") for m in models]
        return await asyncio.to_thread(run)


class Database:
    def __init__(self, path):
        self.path = path
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")   # autocommit: ogni istruzione si conferma da sola
        self._lock = threading.RLock()
        self._tables: set = set()
        self._colls: dict = {}

    def _ensure_table(self, name):
        if name in self._tables:
            return
        if not re.fullmatch(r"[A-Za-z0-9_]+", name):
            raise ValueError(f"nome collezione non valido: {name!r}")
        self._exec(f'CREATE TABLE IF NOT EXISTS "{name}" (doc TEXT NOT NULL, bin BLOB)', ())
        self._tables.add(name)

    def _exec(self, sql, args):
        with self._lock:
            self._conn.execute(sql, args)
            self._conn.commit()

    def _query(self, _name, sql, args):
        with self._lock:
            return self._conn.execute(sql, args).fetchall()

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self[name]

    def __getitem__(self, name):
        if name not in self._colls:
            self._colls[name] = Collection(self, name)
        return self._colls[name]

    async def command(self, cmd):
        if cmd != "dbstats":
            raise NotImplementedError(cmd)
        size = sum(os.path.getsize(p) for p in (self.path, self.path + "-wal") if os.path.exists(p))
        return {"dataSize": size, "indexSize": 0}

    def compact(self):
        """Ricompatta il file (VACUUM): dopo aver tolto i video dal database lo spazio torna libero."""
        with self._lock:
            self._conn.execute("VACUUM")
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def close(self):
        with self._lock:
            try:
                self._conn.commit()
            finally:
                self._conn.close()


class Client:
    """Al posto di AsyncIOMotorClient: client[nome] -> Database su <cartella>/<nome>.sqlite3."""

    def __init__(self, url: str):
        # sqlite:///C:/Users/.../dati  (Windows)   oppure   sqlite:////percorso/assoluto  (Linux)
        rest = url[len("sqlite:"):]
        self.folder = rest[3:] if rest.startswith("///") else rest
        self._dbs: dict = {}

    def __getitem__(self, name):
        if name not in self._dbs:
            self._dbs[name] = Database(os.path.join(self.folder, f"{name}.sqlite3"))
        return self._dbs[name]

    def close(self):
        for d in self._dbs.values():
            d.close()
