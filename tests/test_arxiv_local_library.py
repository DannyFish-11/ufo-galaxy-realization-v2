"""本机 arXiv 文献库:元数据整份在本机(检索离线、全库),全文用到哪篇取哪篇,arXiv 那边守限速。

所有者:「GitHub / Hugging Face 上那个 arXiv 的、十几 TB ……调用好像要付费,电脑也塞不下」。
做法见 core/arxiv_library.py 文件头;这里钉住每一层真的是那样工作的。
"""

from __future__ import annotations

import asyncio
import os

import pytest

from core import arxiv_client, arxiv_library, arxiv_sync
from core.arxiv_library import ArxivLibrary, fts_query, normalize_id


def _row(pid, title, abstract="", cats="cs.CL", first="2024-01-02", authors="Ada Lovelace; Alan Turing"):
    return {
        "paper_id": pid,
        "title": title,
        "abstract": abstract,
        "authors": authors,
        "categories": cats,
        "primary_category": cats.split()[0],
        "first_date": first,
        "updated": first,
        "license": "http://creativecommons.org/licenses/by/4.0/",
    }


@pytest.fixture
def lib(tmp_path):
    lib = ArxivLibrary(str(tmp_path / "arxiv" / "library.sqlite3"))
    lib.bulk_mode(True)
    lib.upsert(
        [
            _row("2401.00001", "Retrieval augmented generation for open domain QA", "We study retrieval."),
            _row("2401.00002", "A survey of diffusion models", "Retrieval is mentioned once.", "cs.CV cs.LG"),
            _row("2301.00003", "Graph neural networks", "message passing", "stat.ML cs.LG", "2023-01-05"),
            _row("hep-th/9901001", "Strings and branes", "dualities", "hep-th", "1999-01-01"),
        ]
    )
    lib.bulk_mode(False)
    return lib


# ── 编号与查询 ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,want",
    [
        ("arXiv:2401.01234v2", "2401.01234"),
        ("https://arxiv.org/abs/2401.01234v3", "2401.01234"),
        ("https://arxiv.org/pdf/2401.01234", "2401.01234"),
        ("hep-th/9901001", "hep-th/9901001"),
        ("math.GT/0309136v1", "math.GT/0309136"),
    ],
)
def test_ids_are_normalized_without_the_version(raw, want):
    assert normalize_id(raw) == want


def test_query_words_are_quoted_so_punctuation_is_not_syntax():
    assert fts_query('NOT "AND" OR c++ (x)') == '"NOT" "AND" "OR"'
    assert fts_query("rag survey", any_word=True) == '"rag" OR "survey"'


# ── 检索 ────────────────────────────────────────────────────────────────────


def test_a_title_hit_ranks_above_an_abstract_hit(lib):
    papers = lib.search("retrieval")
    assert [p["paper_id"] for p in papers[:2]] == ["2401.00001", "2401.00002"]
    top = papers[0]
    assert top["url"] == "https://arxiv.org/abs/2401.00001" and top["origin"] == "local"
    assert top["authors"] == ["Ada Lovelace", "Alan Turing"] and "cs.CL" in top["tags"]


def test_categories_are_filtered_by_field_not_guessed(lib):
    assert [p["paper_id"] for p in lib.search("retrieval", categories=["cs.CV"])] == ["2401.00002"]
    # 只给大类:cs 下面任何一类都算;hep-th 这种没有点的分类按整名
    assert {p["paper_id"] for p in lib.search("models networks", categories=["cs"])} >= {"2301.00003"}
    assert [p["paper_id"] for p in lib.search("strings", categories=["hep-th"])] == ["hep-th/9901001"]
    assert lib.search("strings", categories=["cs"]) == []


def test_dates_are_filtered_by_field(lib):
    assert [p["paper_id"] for p in lib.search("graph", since="2023-01-01", until="2023-12-31")] == ["2301.00003"]
    assert lib.search("graph", since="2024-01-01") == []


def test_all_words_first_then_any_word(lib):
    """所有词都要有;一篇都没有就放宽成任一词 —— 不让一个罕见词把整个检索清零。"""
    assert [p["paper_id"] for p in lib.search("diffusion zebrafish")] == ["2401.00002"]


def test_incremental_updates_keep_the_index_in_step(lib):
    lib.upsert([_row("2410.00009", "Mixture of experts routing")])
    assert [p["paper_id"] for p in lib.search("experts routing")] == ["2410.00009"]
    lib.upsert([_row("2410.00009", "Sparse gating revisited")])  # 新版本改了标题
    assert lib.search("experts routing") == []
    assert [p["paper_id"] for p in lib.search("sparse gating")] == ["2410.00009"]
    lib.delete(["2410.00009"])  # 撤稿
    assert lib.search("sparse gating") == []


def test_status_says_what_is_there(lib):
    st = lib.status()
    assert st["ready"] is True and st["papers"] == 4 and st["db_bytes"] > 0


# ── 全文缓存 ────────────────────────────────────────────────────────────────


def test_fulltext_is_cached_compressed_and_evicted_least_recently_read(lib):
    lib.store_text("2401.00001", "A" * 5000, "arxiv_html")
    lib.store_text("2401.00002", "B" * 5000, "arxiv_pdf")
    assert lib.cached_text("2401.00001")["text"] == "A" * 5000  # 读一下:它变成最近读过的
    sizes = sum(os.path.getsize(os.path.join(lib._text_dir(), f)) for f in os.listdir(lib._text_dir()))
    assert sizes < 2 * 5000, "存盘不是压缩的"
    one = os.path.getsize(os.path.join(lib._text_dir(), "2401.00001.txt.gz"))
    assert lib.evict(limit=one) == 1
    assert lib.cached_text("2401.00002") is None and lib.cached_text("2401.00001") is not None


def test_reading_goes_cache_then_arxiv_and_caches_what_it_got(lib, monkeypatch):
    monkeypatch.setattr(arxiv_library, "get_library", lambda: lib)
    calls = []
    monkeypatch.setattr(arxiv_client, "fetch_text", lambda pid: calls.append(pid) or ("full text body", "arxiv_html"))
    first = arxiv_library.read_fulltext("arXiv:2401.00001v2")
    again = arxiv_library.read_fulltext("2401.00001")
    assert first["text"] == again["text"] == "full text body"
    assert calls == ["2401.00001"], "第二次又去问了 arXiv —— 缓存没用上"
    assert again["cached"] is True


# ── 导入:列名映射与分类筛选 ────────────────────────────────────────────────


def test_columns_are_recognised_by_their_usual_names():
    cols = arxiv_sync.map_columns(
        ["paper_id", "title", "abstract", "primary_category", "license", "first_version_date"]
    )
    assert cols["first_date"] == "first_version_date" and "authors" not in cols


def test_rows_are_normalised_and_filtered_by_category():
    batch = {
        "paper_id": ["1", "2"],
        "title": ["  A   title ", "B"],
        "categories": [["cs.CL", "cs.AI"], "math.GT"],
        "authors": [[["Lovelace", "Ada"]], "Bob"],
        "first_version_date": ["2024-01-02T10:00:00", None],
    }
    cols = arxiv_sync.map_columns(list(batch))
    rows = arxiv_sync.to_rows(batch, cols, categories=["cs"])
    assert [r["paper_id"] for r in rows] == ["1"]
    r = rows[0]
    assert r["title"] == "A title" and r["categories"] == "cs.CL cs.AI" and r["primary_category"] == "cs.CL"
    assert r["first_date"] == "2024-01-02" and r["authors"] == "Lovelace Ada"


def test_the_whole_metadata_import_runs_end_to_end(tmp_path, monkeypatch):
    """假的 Hugging Face:两个 metadata 分片 → 导入、建索引、导完删掉分片、接着补增量。"""
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")
    monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path))
    src = tmp_path / "src"
    src.mkdir()
    for k, ids in enumerate((["2401.00001", "2401.00002"], ["2402.00003"])):
        pq.write_table(
            pa.table(
                {
                    "paper_id": ids,
                    "title": [f"Paper about transformers {i}" for i in ids],
                    "abstract": ["attention" for _ in ids],
                    "primary_category": ["cs.CL" for _ in ids],
                    "first_version_date": ["2024-01-02" for _ in ids],
                    "license": ["" for _ in ids],
                }
            ),
            src / f"part-{k}.parquet",
        )
    lib = ArxivLibrary(str(tmp_path / "arxiv" / "library.sqlite3"))
    monkeypatch.setattr(arxiv_sync, "_hf", lambda: object())
    monkeypatch.setattr(
        arxiv_sync, "_files", lambda api, prefix: ["metadata/part-0.parquet", "metadata/part-1.parquet"]
    )
    downloaded = []

    def fake_download(api, name):
        local = tmp_path / "dl" / os.path.basename(name)
        local.parent.mkdir(exist_ok=True)
        local.write_bytes((src / os.path.basename(name)).read_bytes())
        downloaded.append(local)
        return str(local)

    monkeypatch.setattr(arxiv_sync, "_download", fake_download)
    monkeypatch.setattr(arxiv_sync, "NEED_BYTES_METADATA", 1)
    new_row = {**_row("2410.00007", "Transformers revisited"), "categories": "cs.CL"}
    monkeypatch.setattr(arxiv_client, "list_records", lambda since: iter([("2410.00007", new_row, "2026-09-03")]))

    arxiv_sync._import_metadata(lib, [])
    assert lib.ready() and lib.count() == 4
    assert {p["paper_id"] for p in lib.search("transformers", limit=10)} == {
        "2401.00001",
        "2401.00002",
        "2402.00003",
        "2410.00007",
    }
    assert not any(p.exists() for p in downloaded), "导完的分片还留在硬盘上(同时占两份)"
    assert lib.meta("oai_through") == "2026-09-02"


def test_an_interrupted_import_resumes_from_the_file_it_stopped_at(tmp_path, monkeypatch):
    lib = ArxivLibrary(str(tmp_path / "library.sqlite3"))
    lib.set_meta("metadata_done", "metadata/part-0.parquet")
    lib.set_meta("categories", "")
    seen = []
    monkeypatch.setattr(arxiv_sync, "_ensure_pyarrow", lambda: None)
    monkeypatch.setattr(arxiv_sync, "_hf", lambda: object())
    monkeypatch.setattr(
        arxiv_sync, "_files", lambda api, prefix: ["metadata/part-0.parquet", "metadata/part-1.parquet"]
    )
    monkeypatch.setattr(arxiv_sync, "NEED_BYTES_METADATA", 1)

    def stop_after_seeing(api, name):
        seen.append(name)
        raise RuntimeError("断网")

    monkeypatch.setattr(arxiv_sync, "_download", stop_after_seeing)
    pytest.importorskip("pyarrow")
    with pytest.raises(RuntimeError):
        arxiv_sync._import_metadata(lib, [])
    assert seen == ["metadata/part-1.parquet"]


def test_not_enough_disk_is_said_up_front(tmp_path, monkeypatch):
    lib = ArxivLibrary(str(tmp_path / "library.sqlite3"))
    monkeypatch.setattr(arxiv_sync, "_free_bytes", lambda path: 2 * 1024**3)
    with pytest.raises(RuntimeError, match="硬盘剩 2.0 GB"):
        arxiv_sync._import_metadata(lib, [])


# ── arXiv 那边:解析与限速 ──────────────────────────────────────────────────

_ATOM = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
<entry><id>http://arxiv.org/abs/2401.00001v2</id><published>2024-01-02T00:00:00Z</published>
<title>Retrieval   augmented</title><summary> We study it. </summary>
<author><name>Ada Lovelace</name></author><arxiv:primary_category term="cs.CL"/>
<category term="cs.CL"/><category term="cs.AI"/></entry></feed>"""

_OAI = """<?xml version="1.0"?><OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/"><ListRecords>
<record><header><identifier>oai:arXiv.org:2410.00007</identifier><datestamp>2026-09-03</datestamp></header>
<metadata><arXiv xmlns="http://arxiv.org/OAI/arXiv/"><id>2410.00007</id><created>2024-10-01</created>
<authors><author><keyname>Turing</keyname><forenames>Alan</forenames></author></authors>
<title>Machines</title><categories>cs.AI cs.LO</categories><abstract>Can machines think</abstract>
</arXiv></metadata></record>
<record><header status="deleted"><identifier>oai:arXiv.org:2001.00001</identifier>
<datestamp>2026-09-04</datestamp></header></record>
</ListRecords></OAI-PMH>"""


def test_atom_results_parse_into_the_usual_paper_shape():
    (p,) = arxiv_client.parse_atom(_ATOM)
    assert p["paper_id"] == "2401.00001" and p["title"] == "Retrieval augmented"
    assert p["primary_category"] == "cs.CL" and p["tags"] == ["arXiv", "cs.CL", "cs.AI"]


def test_oai_records_parse_and_withdrawals_are_seen():
    import xml.etree.ElementTree as ET

    root = ET.fromstring(_OAI)
    recs = root.findall(".//{http://www.openarchives.org/OAI/2.0/}record")
    pid, row = arxiv_client.parse_oai_record(recs[0])
    assert pid == "2410.00007" and row["authors"] == "Alan Turing" and row["primary_category"] == "cs.AI"
    assert arxiv_client.parse_oai_record(recs[1]) == ("2001.00001", None)


def test_arxiv_is_asked_at_most_once_every_three_seconds_over_https(monkeypatch):
    clock = {"t": 1000.0}
    sent = []

    class _Resp:
        status_code = 200
        headers = {}

    monkeypatch.setattr(arxiv_client.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(arxiv_client.time, "sleep", lambda s: clock.__setitem__("t", clock["t"] + s))
    monkeypatch.setattr(arxiv_client, "_last_call", [0.0])

    def fake_get(url, **kw):
        sent.append((clock["t"], url))
        return _Resp()

    import httpx

    monkeypatch.setattr(httpx, "get", fake_get)
    for _ in range(3):
        arxiv_client._get(arxiv_client.API_URL)
    gaps = [b[0] - a[0] for a, b in zip(sent, sent[1:])]
    assert all(g >= arxiv_client.MIN_INTERVAL_S for g in gaps), gaps
    assert all(url.startswith("https://") for _t, url in sent)


def test_every_arxiv_client_in_the_repo_goes_through_the_one_gate():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    for rel in ("core/academic_retrieval.py", "nodes/Node_97_AcademicSearch/main.py"):
        src = (root / rel).read_text(encoding="utf-8")
        assert "export.arxiv.org/api" not in src, f"{rel} 又自己直连 arXiv 了(不限速、http)"
        assert "core.arxiv_client import search" in src


# ── 给智能体的工具 ──────────────────────────────────────────────────────────


def _tool(which, **args):
    from core.academic_tools import dispatch_arxiv_tool

    return asyncio.run(dispatch_arxiv_tool(which, args))


def test_search_uses_the_local_library_when_it_is_built(lib, monkeypatch):
    monkeypatch.setattr(arxiv_library, "get_library", lambda: lib)
    monkeypatch.setattr(arxiv_sync, "maybe_refresh", lambda: False)
    out = _tool("arxiv_search", query="retrieval", categories=["cs.CL"])
    assert out["origin"] == "local" and [p["paper_id"] for p in out["papers"]] == ["2401.00001"]


def test_search_falls_back_to_online_and_says_the_library_is_not_built(tmp_path, monkeypatch):
    empty = ArxivLibrary(str(tmp_path / "none.sqlite3"))
    monkeypatch.setattr(arxiv_library, "get_library", lambda: empty)
    monkeypatch.setattr(arxiv_sync, "get_library", lambda: empty)
    monkeypatch.setattr(arxiv_client, "search_or_why", lambda q, n: ([{"paper_id": "x", "abstract": "y"}], ""))
    out = _tool("arxiv_search", query="anything")
    assert out["origin"] == "online" and out["total"] == 1 and "1.6 GB" in out["note"]


def test_online_search_that_could_not_connect_says_so_instead_of_finding_nothing(tmp_path, monkeypatch):
    """第 6 轮真跑：代理不放行 export.arxiv.org，工具原先照样回 ``success: True, papers: []`` —— 模型据此告诉人
    「没有相关论文」，而事实是一篇都没查成。没连上和没搜到是两件事。"""
    import httpx

    empty = ArxivLibrary(str(tmp_path / "none.sqlite3"))
    monkeypatch.setattr(arxiv_library, "get_library", lambda: empty)
    monkeypatch.setattr(arxiv_sync, "get_library", lambda: empty)

    def refused(*a, **kw):
        raise httpx.ConnectError("CONNECT tunnel failed, response 403")

    monkeypatch.setattr(arxiv_client, "_get", refused)
    out = _tool("arxiv_search", query="transformer")
    assert out["success"] is False and out["papers"] == []
    assert "没连上 arXiv" in out["error"] and "不是没有相关论文" in out["error"]
    assert arxiv_client.search("transformer") == [], "旧的 search() 照旧只回空列表（多源汇总的调用方靠它）"


def test_reading_returns_a_window_and_where_to_continue(lib, monkeypatch):
    monkeypatch.setattr(arxiv_library, "get_library", lambda: lib)
    lib.store_text("2401.00001", "x" * 1200, "arxiv_html")
    out = _tool("arxiv_read", paper_id="2401.00001", max_chars=500)
    assert len(out["text"]) == 500 and out["total_chars"] == 1200 and out["next_offset"] == 500


def test_downloads_only_happen_in_a_turn_the_user_started(monkeypatch):
    import core.academic_tools as tools

    started = []
    monkeypatch.setattr(arxiv_sync, "start", lambda part, categories=(): started.append(part) or {"success": True})
    monkeypatch.setattr(tools, "_human_turn", lambda: False)
    assert _tool("arxiv_library", action="build")["success"] is False and started == []
    monkeypatch.setattr(tools, "_human_turn", lambda: True)
    assert _tool("arxiv_library", action="download_fulltext")["success"] is False, "70 GB 不问就下了"
    assert started == []
    _tool("arxiv_library", action="download_fulltext", confirm=True)
    _tool("arxiv_library", action="build", categories=["cs"])
    assert started == ["paper_text", "metadata"]


def test_the_agent_sees_the_three_new_tools_and_they_are_dispatched():
    import inspect

    from core.openclawd import _ACADEMIC_BUILTIN_TOOLS, OpenClawd

    names = [t["function"]["name"] for t in _ACADEMIC_BUILTIN_TOOLS]
    for n in ("academic__arxiv_search", "academic__arxiv_read", "academic__arxiv_library"):
        assert n in names
    assert "dispatch_arxiv_tool" in inspect.getsource(OpenClawd._dispatch_academic_tool)


def test_academic_search_puts_local_hits_first_and_dedupes(lib, monkeypatch):
    from core.academic_retrieval import AcademicRetriever

    monkeypatch.setattr(arxiv_library, "get_library", lambda: lib)
    r = AcademicRetriever()

    async def node97(*_a):
        return [{"paper_id": "2401.00001", "title": "dup"}, {"paper_id": "pubmed-1", "title": "other"}]

    monkeypatch.setattr(r, "_search_via_node97", node97)
    out = asyncio.run(r.search("retrieval", ingest=False))
    ids = [p["paper_id"] for p in out["papers"]]
    assert ids[:2] == ["2401.00001", "2401.00002"] and ids.count("2401.00001") == 1 and "pubmed-1" in ids
