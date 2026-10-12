"""arXiv 本地文献库:**元数据整份放本机(只有 1.6 GB),全文用到哪篇取哪篇**。

为什么是这个形状
================

所有者想接 Hugging Face 上的 ``secemp9/arxiv-complete``(3,148,796 篇,16.08 TB),担心两件事:
调用要付费、十几 TB 电脑放不下。实际情况:

* 从 Hugging Face 下载不收费(要付费的是 arXiv 官方放在 S3 上的「下载方付流量」批量包);
* 16 TB 里 15.8 TB 是 PDF / 源码包 / PostScript —— 智能体检索与阅读用不上。这个数据集按配置
  分开放:``metadata`` 1.6 GB(标题、作者、摘要、分类、日期、许可),``paper_text`` 70 GB
  (已抽好的全文)。**只拿 metadata**,检索就能离线、毫秒级地覆盖全部 314 万篇。

所以三层:

1. **目录(本机)** —— ``metadata`` 导进一个 SQLite 文件(``$GALAXY_DATA_DIR/arxiv/library.sqlite3``),
   标题 + 摘要 + 作者建 FTS5 全文索引(BM25,标题加权)。分类、日期是**有类型的字段**,按字段过滤
   —— 会改变控制流的读取走确定性查询(``core/semantic_anchoring.py`` 的判据),不让检索去「猜」分类。
2. **全文(按需)** —— 先看本机缓存;再看本机有没有下过 ``paper_text`` 的分片;都没有就向 arXiv
   要**这一篇**(HTML 版优先,没有再 PDF),守它的限速(``core/arxiv_client.py``)。取回来的压缩存盘,
   总量有上限,满了先丢最久没读过的。
3. **增量(每天)** —— 快照之后的新论文走 arXiv 官方 OAI-PMH,不用重下那 1.6 GB。

导入 / 增量在 ``core/arxiv_sync.py``;给智能体的工具在 ``core/academic_tools.py``。

许可:元数据是 CC0(公有领域)。全文按每篇论文自己的许可,很多只授权 arXiv 分发 —— 这里只在本机
检索、阅读,不往外分发。
"""

from __future__ import annotations

import gzip
import logging
import os
import re
import sqlite3
import threading
import time
from typing import Any, Dict, Iterable, List, Optional, Sequence

from core.data_paths import data_path

logger = logging.getLogger("Galaxy.ArxivLibrary")

#: 数据来源与固定版本(2026-08-30 的元数据快照;之后的新论文走 OAI-PMH 增量)。固定版本是因为
#: ``main`` 会变(数据集那边有人提过删分片的 PR),同一份导入要能复现。
DATASET = "secemp9/arxiv-complete"
REVISION = "cee894837962fede5612cccf2a4c7cacf49b4c3a"
SNAPSHOT_DATE = "2026-08-30"

#: 全文缓存的总量上限。超了先丢最久没读过的。
CACHE_LIMIT_BYTES = 2 * 1024**3

_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS papers(
        rowid INTEGER PRIMARY KEY,
        paper_id TEXT UNIQUE NOT NULL,
        title TEXT, abstract TEXT, authors TEXT,
        categories TEXT, primary_category TEXT,
        first_date TEXT, updated TEXT,
        license TEXT, doi TEXT, journal_ref TEXT)""",
    "CREATE INDEX IF NOT EXISTS papers_primary ON papers(primary_category)",
    "CREATE INDEX IF NOT EXISTS papers_first_date ON papers(first_date)",
    # 外部内容表:正文只存一份(papers 里),索引只存词项。detail=column 不存词的位置 ——
    # 没有短语查询,但 BM25 与按列加权照常,索引小一半。
    """CREATE VIRTUAL TABLE IF NOT EXISTS papers_fts USING fts5(
        title, abstract, authors,
        content='papers', content_rowid='rowid',
        tokenize='porter unicode61 remove_diacritics 2', detail=column)""",
    "CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT)",
    """CREATE TABLE IF NOT EXISTS fulltext(
        paper_id TEXT PRIMARY KEY, file TEXT, bytes INTEGER, source TEXT,
        fetched_at REAL, used_at REAL)""",
    "CREATE TABLE IF NOT EXISTS text_index(paper_id TEXT PRIMARY KEY, shard TEXT, row_group INTEGER)",
)

#: 增量更新时让全文索引跟着正文表走。整批导入时先拆掉、导完 ``rebuild`` 一次再装回来(快得多)。
_TRIGGERS = (
    """CREATE TRIGGER IF NOT EXISTS papers_ai AFTER INSERT ON papers BEGIN
        INSERT INTO papers_fts(rowid, title, abstract, authors)
        VALUES (new.rowid, new.title, new.abstract, new.authors); END""",
    """CREATE TRIGGER IF NOT EXISTS papers_ad AFTER DELETE ON papers BEGIN
        INSERT INTO papers_fts(papers_fts, rowid, title, abstract, authors)
        VALUES ('delete', old.rowid, old.title, old.abstract, old.authors); END""",
    """CREATE TRIGGER IF NOT EXISTS papers_au AFTER UPDATE ON papers BEGIN
        INSERT INTO papers_fts(papers_fts, rowid, title, abstract, authors)
        VALUES ('delete', old.rowid, old.title, old.abstract, old.authors);
        INSERT INTO papers_fts(rowid, title, abstract, authors)
        VALUES (new.rowid, new.title, new.abstract, new.authors); END""",
)

_COLUMNS = (
    "paper_id",
    "title",
    "abstract",
    "authors",
    "categories",
    "primary_category",
    "first_date",
    "updated",
    "license",
    "doi",
    "journal_ref",
)

_ID_RE = re.compile(r"(\d{4}\.\d{4,5}|[a-z\-]+(?:\.[A-Z]{2})?/\d{7})", re.I)
_WORD = re.compile(r"[A-Za-z0-9]+(?:[-.][A-Za-z0-9]+)*")


def library_dir() -> str:
    return data_path("arxiv")


def normalize_id(raw: str) -> str:
    """``arXiv:2401.01234v2`` / ``https://arxiv.org/abs/2401.01234`` / ``hep-th/9901001`` → 不带版本号的编号。"""
    m = _ID_RE.search(raw or "")
    return m.group(1) if m else (raw or "").strip()


def fts_query(text: str, *, any_word: bool = False) -> str:
    """把一句自然语言变成 FTS5 能吃的查询:每个词加引号(标点、关键字都不会被当成语法),默认全都要有。"""
    words = [w for w in _WORD.findall(text or "") if len(w) > 1][:16]
    return (" OR " if any_word else " ").join(f'"{w}"' for w in words)


def _category_clause(categories: Sequence[str]) -> tuple:
    """``["cs.CL", "stat"]`` → 命中 cs.CL 这一类,或 stat 下面任何一类(``stat.ML`` 之类)。"""
    parts, args = [], []
    for c in categories:
        c = (c or "").strip()
        if not c:
            continue
        parts.append("(instr(' ' || p.categories || ' ', ?) > 0 OR instr(' ' || p.categories, ?) > 0)")
        args.extend([f" {c} ", f" {c}."])
    return (" AND (" + " OR ".join(parts) + ")", args) if parts else ("", [])


def to_paper(row: sqlite3.Row) -> Dict[str, Any]:
    """一行 → 与 ``academic__search`` 同形的论文 dict。"""
    cats = (row["categories"] or "").split()
    return {
        "paper_id": row["paper_id"],
        "title": row["title"] or "",
        "authors": [a.strip() for a in (row["authors"] or "").split(";") if a.strip()],
        "abstract": row["abstract"] or "",
        "published_date": row["first_date"] or "",
        "updated": row["updated"] or "",
        "url": f"https://arxiv.org/abs/{row['paper_id']}",
        "source": "arXiv",
        "primary_category": row["primary_category"] or (cats[0] if cats else ""),
        "tags": ["arXiv", *cats],
        "doi": row["doi"] or "",
        "license": row["license"] or "",
        "journal_ref": row["journal_ref"] or "",
    }


class ArxivLibrary:
    """一个 SQLite 文件。每次操作开一个连接(便宜,也就天然线程安全);写由一把锁排队。"""

    def __init__(self, path: Optional[str] = None) -> None:
        self.path = path or os.path.join(library_dir(), "library.sqlite3")
        self._write = threading.Lock()
        self._inited = False

    # ── 连接与元信息 ──────────────────────────────────────────────────────

    def connect(self) -> sqlite3.Connection:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        if not self._inited:
            conn.execute("PRAGMA journal_mode=WAL")
            for stmt in _SCHEMA:
                conn.execute(stmt)
            conn.commit()
            self._inited = True
        return conn

    def meta(self, key: str, default: str = "") -> str:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_meta(self, key: str, value: Any) -> None:
        with self._write, self.connect() as conn:
            conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", (key, str(value)))

    def count(self) -> int:
        with self.connect() as conn:
            return int(conn.execute("SELECT count(*) FROM papers").fetchone()[0])

    def ready(self) -> bool:
        """目录建好了吗(导入完成、全文索引建好)。没建好时检索走在线兜底。"""
        if not os.path.exists(self.path):
            return False
        try:
            return self.meta("fts_ready") == "1"
        except sqlite3.Error:
            return False

    # ── 写 ────────────────────────────────────────────────────────────────

    def upsert(self, rows: Iterable[Dict[str, Any]]) -> int:
        """写入 / 更新一批(同一个事务)。增量更新时触发器会顺带更新全文索引。"""
        cols = ", ".join(_COLUMNS)
        marks = ", ".join("?" for _ in _COLUMNS)
        sets = ", ".join(f"{c}=excluded.{c}" for c in _COLUMNS[1:])
        sql = f"INSERT INTO papers({cols}) VALUES ({marks}) ON CONFLICT(paper_id) DO UPDATE SET {sets}"
        batch = [tuple((r.get(c) or "") for c in _COLUMNS) for r in rows if r.get("paper_id")]
        if not batch:
            return 0
        with self._write, self.connect() as conn:
            conn.executemany(sql, batch)
        return len(batch)

    def delete(self, paper_ids: Iterable[str]) -> None:
        with self._write, self.connect() as conn:
            conn.executemany("DELETE FROM papers WHERE paper_id=?", [(p,) for p in paper_ids])

    def bulk_mode(self, on: bool) -> None:
        """整批导入:拆掉触发器(导完一次性 ``rebuild``);导完装回来。"""
        with self._write, self.connect() as conn:
            if on:
                for name in ("papers_ai", "papers_ad", "papers_au"):
                    conn.execute(f"DROP TRIGGER IF EXISTS {name}")
                conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('fts_ready', '0')")
            else:
                conn.execute("INSERT INTO papers_fts(papers_fts) VALUES ('rebuild')")
                for stmt in _TRIGGERS:
                    conn.execute(stmt)
                conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('fts_ready', '1')")

    # ── 读 ────────────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        *,
        categories: Sequence[str] = (),
        since: str = "",
        until: str = "",
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """BM25(标题 ×10、作者 ×2、摘要 ×1) + 分类 / 日期的字段过滤。所有词都要有;一篇都没有再放宽成任一词。"""
        limit = max(1, min(int(limit or 10), 50))
        where, args = _category_clause(categories)
        if since:
            where += " AND p.first_date >= ?"
            args.append(since)
        if until:
            where += " AND p.first_date <= ?"
            args.append(until)
        sql = (
            "SELECT p.*, bm25(papers_fts, 10.0, 1.0, 2.0) AS score FROM papers_fts "
            "JOIN papers p ON p.rowid = papers_fts.rowid "
            f"WHERE papers_fts MATCH ?{where} ORDER BY score LIMIT ?"
        )
        with self.connect() as conn:
            for any_word in (False, True):
                q = fts_query(query, any_word=any_word)
                if not q:
                    return []
                rows = conn.execute(sql, [q, *args, limit]).fetchall()
                if rows:
                    return [{**to_paper(r), "score": round(-float(r["score"]), 3), "origin": "local"} for r in rows]
        return []

    def get(self, paper_id: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM papers WHERE paper_id=?", (normalize_id(paper_id),)).fetchone()
        return to_paper(row) if row else None

    # ── 全文缓存 ──────────────────────────────────────────────────────────

    def _text_dir(self) -> str:
        return os.path.join(os.path.dirname(self.path), "fulltext")

    def cached_text(self, paper_id: str) -> Optional[Dict[str, Any]]:
        pid = normalize_id(paper_id)
        with self.connect() as conn:
            row = conn.execute("SELECT file, source FROM fulltext WHERE paper_id=?", (pid,)).fetchone()
        if not row or not os.path.exists(row["file"]):
            return None
        with gzip.open(row["file"], "rt", encoding="utf-8") as fh:
            text = fh.read()
        with self._write, self.connect() as conn:
            conn.execute("UPDATE fulltext SET used_at=? WHERE paper_id=?", (time.time(), pid))
        return {"text": text, "source": row["source"]}

    def store_text(self, paper_id: str, text: str, source: str) -> None:
        pid = normalize_id(paper_id)
        os.makedirs(self._text_dir(), exist_ok=True)
        path = os.path.join(self._text_dir(), re.sub(r"[^A-Za-z0-9.\-]", "_", pid) + ".txt.gz")
        with gzip.open(path, "wt", encoding="utf-8") as fh:
            fh.write(text)
        now = time.time()
        with self._write, self.connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO fulltext(paper_id, file, bytes, source, fetched_at, used_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (pid, path, os.path.getsize(path), source, now, now),
            )
        self.evict()

    def evict(self, limit: int = CACHE_LIMIT_BYTES) -> int:
        """缓存超过上限就从最久没读过的开始丢。返回丢了几篇。"""
        with self.connect() as conn:
            rows = conn.execute("SELECT paper_id, file, bytes FROM fulltext ORDER BY used_at DESC").fetchall()
        total, dropped = 0, []
        for r in rows:
            total += int(r["bytes"] or 0)
            if total > limit:
                dropped.append(r)
        for r in dropped:
            try:
                os.remove(r["file"])
            except OSError:
                pass
        if dropped:
            with self._write, self.connect() as conn:
                conn.executemany("DELETE FROM fulltext WHERE paper_id=?", [(r["paper_id"],) for r in dropped])
        return len(dropped)

    def status(self) -> Dict[str, Any]:
        if not os.path.exists(self.path):
            return {"ready": False, "papers": 0, "path": self.path}
        with self.connect() as conn:
            cached = conn.execute("SELECT count(*), coalesce(sum(bytes), 0) FROM fulltext").fetchone()
            shards = conn.execute("SELECT count(*) FROM text_index").fetchone()[0]
        return {
            "ready": self.ready(),
            "papers": self.count(),
            "path": self.path,
            "db_bytes": os.path.getsize(self.path),
            "snapshot": self.meta("snapshot_date", ""),
            "updated_through": self.meta("oai_through", ""),
            "categories": self.meta("categories", "") or "全部",
            "fulltext_cached": int(cached[0]),
            "fulltext_cache_bytes": int(cached[1]),
            "local_fulltext_papers": int(shards),
        }


_library: Optional[ArxivLibrary] = None
_lock = threading.Lock()


def get_library() -> ArxivLibrary:
    global _library
    with _lock:
        if _library is None or _library.path != os.path.join(library_dir(), "library.sqlite3"):
            _library = ArxivLibrary()
        return _library


def read_fulltext(paper_id: str) -> Dict[str, Any]:
    """一篇的全文:本机缓存 → 本机 ``paper_text`` 分片 → 向 arXiv 要这一篇。同步函数,调用方放线程里。"""
    lib = get_library()
    pid = normalize_id(paper_id)
    hit = lib.cached_text(pid)
    if hit:
        return {"success": True, "paper_id": pid, "text": hit["text"], "source": hit["source"], "cached": True}
    try:
        from core.arxiv_sync import local_shard_text

        text = local_shard_text(lib, pid)
    except Exception as exc:  # noqa: BLE001 — 本机分片读不出来就去问 arXiv
        logger.debug("本机全文分片读不出 %s: %s", pid, exc)
        text = ""
    source = "local_paper_text"
    if not text:
        from core.arxiv_client import fetch_text

        text, source = fetch_text(pid)
        if not text:
            return {"success": False, "paper_id": pid, "error": source}
    lib.store_text(pid, text, source)
    return {"success": True, "paper_id": pid, "text": text, "source": source, "cached": False}
