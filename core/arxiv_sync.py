"""把 arXiv 元数据导进本机文献库,之后每天补上新论文。全部在后台线程里做,随时可以问进度。

三件事(``core/arxiv_library.py`` 讲了为什么是这个形状):

* ``start("metadata")``   —— 从 Hugging Face 下 ``metadata/*.parquet``(共 1.6 GB,固定版本),逐个文件
  流式读进 SQLite,读完一个删一个(不在硬盘上同时留两份);全部导完建一次全文索引。中断了再开会从
  没导完的那个文件接着来。
* ``start("update")``     —— arXiv 官方 OAI-PMH 增量:快照(或上次更新)之后的新论文 / 改动 / 撤稿。
  文献库建好后,检索时若离上次更新超过一天,会顺带在后台补一次(``maybe_refresh``)。
* ``start("paper_text")`` —— **70 GB** 的全文分片整份下到本机(之后读全文不用联网)。默认不做;
  工具层要人明确点头才会走到这里。

只用两个库:``huggingface_hub``(已在依赖里)与 ``pyarrow``(读 Parquet;没装的话第一次同步时补装)。
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence

from core.arxiv_library import DATASET, REVISION, SNAPSHOT_DATE, ArxivLibrary, get_library, library_dir

logger = logging.getLogger("Galaxy.ArxivSync")

#: 元数据整份导入要预留的硬盘(下载中的单个分片 + SQLite 正文 + 全文索引)。
NEED_BYTES_METADATA = 8 * 1024**3
#: 只导部分分类时的下限。
NEED_BYTES_SUBSET = 3 * 1024**3
#: 全文分片整份。
NEED_BYTES_PAPER_TEXT = 75 * 1024**3
#: 离上次增量更新超过这么久,检索时顺带在后台补一次。
REFRESH_AFTER_S = 24 * 3600

_BATCH = 20000

#: 列名不写死:数据集卡片上确认过的是 paper_id / title / abstract / primary_category / license /
#: first_version_date,其余几列按常见写法挨个认。认不出的列就空着,不猜。
_ALIASES = {
    "paper_id": ("paper_id", "id", "arxiv_id"),
    "title": ("title",),
    "abstract": ("abstract", "summary"),
    "authors": ("authors", "author", "authors_parsed"),
    "categories": ("categories", "category_list", "all_categories"),
    "primary_category": ("primary_category",),
    "first_date": ("first_version_date", "published", "created", "first_date", "date"),
    "updated": ("latest_version_date", "last_version_date", "updated", "update_date"),
    "license": ("license",),
    "doi": ("doi",),
    "journal_ref": ("journal_ref", "journal-ref"),
}
_TEXT_ID = ("paper_id", "id", "arxiv_id")
_TEXT_BODY = ("text", "paper_text", "content", "body")

_job_lock = threading.Lock()
_job: Dict[str, Any] = {"running": False}


# ── 小工具 ────────────────────────────────────────────────────────────────


def _as_text(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, (list, tuple)):
        parts = [" ".join(str(x) for x in p if x) if isinstance(p, (list, tuple)) else str(p) for p in v]
        return "; ".join(p.strip() for p in parts if p and p.strip())
    if isinstance(v, (datetime, date)):
        return v.isoformat()[:10]
    return " ".join(str(v).split())


def map_columns(names: Sequence[str]) -> Dict[str, str]:
    """Parquet 的列名 → 文献库的字段名。"""
    have = set(names)
    return {field: next(a for a in aliases if a in have) for field, aliases in _ALIASES.items() if have & set(aliases)}


def to_rows(batch: Dict[str, List[Any]], cols: Dict[str, str], categories: Sequence[str] = ()) -> List[Dict[str, str]]:
    """一批列式数据 → 行;只留 ``categories`` 里的(空 = 全要)。"""
    n = len(next(iter(batch.values()))) if batch else 0
    rows = []
    for i in range(n):
        row = {field: _as_text(batch[col][i]) for field, col in cols.items()}
        raw = batch[cols["categories"]][i] if "categories" in cols else ""
        cats = (
            [str(c) for c in raw if c]
            if isinstance(raw, (list, tuple))
            else str(raw or "").replace(",", " ").replace(";", " ").split()
        )
        if not cats and row.get("primary_category"):
            cats = [row["primary_category"]]
        row["categories"] = " ".join(cats)
        if categories and not any(c == want or c.startswith(want + ".") for c in cats for want in categories):
            continue
        row["primary_category"] = row.get("primary_category") or (cats[0] if cats else "")
        row["first_date"] = row.get("first_date", "")[:10]
        row["updated"] = row.get("updated", "")[:10]
        rows.append(row)
    return rows


def _free_bytes(path: str) -> int:
    os.makedirs(path, exist_ok=True)
    return shutil.disk_usage(path).free


def _ensure_pyarrow() -> None:
    try:
        import pyarrow.parquet  # noqa: F401

        return
    except ImportError:
        pass
    _say("正在补装 pyarrow(读 Parquet 用,只这一次)")
    try:
        from launcher.deps import pip_install

        ok = pip_install(["pyarrow"], stream=False).ok
    except Exception:  # noqa: BLE001 — 启动器不在(容器里)就直接 pip
        ok = subprocess.run([sys.executable, "-m", "pip", "install", "pyarrow"], timeout=1800).returncode == 0
    if not ok:
        raise RuntimeError("pyarrow 装不上(读 Parquet 要它):手动运行 pip install pyarrow 后再同步")
    import importlib

    importlib.invalidate_caches()


def _hf():
    """确定 Hugging Face 下载源(镜像 / 官方择优)并返回 ``HfApi``。"""
    from core.hf_endpoint import pick_endpoint

    endpoint = pick_endpoint()
    if not endpoint:
        raise RuntimeError("Hugging Face 的下载源(hf-mirror.com / huggingface.co)都连不上,稍后再试或设 HF_ENDPOINT")
    from huggingface_hub import HfApi

    return HfApi(endpoint=endpoint)


def _files(api: Any, prefix: str) -> List[str]:
    files = api.list_repo_files(DATASET, repo_type="dataset", revision=REVISION)
    return sorted(f for f in files if f.startswith(prefix + "/") and f.endswith(".parquet"))


def _download(api: Any, name: str) -> str:
    from huggingface_hub import hf_hub_download

    return hf_hub_download(
        DATASET,
        name,
        repo_type="dataset",
        revision=REVISION,
        local_dir=os.path.join(library_dir(), "hf"),
        endpoint=api.endpoint,
    )


# ── 进度 ──────────────────────────────────────────────────────────────────


def _say(step: str, **extra: Any) -> None:
    with _job_lock:
        _job.update(step=step, at=time.time(), **extra)
    logger.info("arXiv 文献库: %s", step)


def status() -> Dict[str, Any]:
    """后台任务进行到哪 + 文献库现状。"""
    with _job_lock:
        job = dict(_job)
    return {"job": job, "library": get_library().status()}


def start(part: str = "metadata", *, categories: Sequence[str] = ()) -> Dict[str, Any]:
    """开一个后台任务(同一时刻只有一个)。立刻返回,进度用 :func:`status` 看。"""
    runners = {"metadata": _import_metadata, "update": _incremental, "paper_text": _download_paper_text}
    if part not in runners:
        return {"success": False, "error": f"不认识的同步内容:{part}(可选 metadata / update / paper_text)"}
    with _job_lock:
        if _job.get("running"):
            return {"success": False, "error": "已经有一个同步在跑了", "job": dict(_job)}
        _job.clear()
        _job.update(running=True, part=part, started_at=time.time(), step="准备中", error="")
    cats = [c.strip() for c in categories if c and c.strip()]

    def run() -> None:
        try:
            runners[part](get_library(), cats)
            _say("完成")
        except Exception as exc:  # noqa: BLE001 — 失败要说得出原因,不能悄悄停
            logger.warning("arXiv 文献库同步失败(%s): %s", part, exc)
            with _job_lock:
                _job.update(error=str(exc))
        finally:
            with _job_lock:
                _job.update(running=False, finished_at=time.time())

    threading.Thread(target=run, name=f"arxiv-sync-{part}", daemon=True).start()
    return {"success": True, "started": part, "job": status()["job"]}


def maybe_refresh() -> bool:
    """检索时调:文献库建好了、离上次增量更新超过一天、手上没有任务 → 后台补一次。返回是否开了。"""
    lib = get_library()
    if not lib.ready():
        return False
    try:
        last = float(lib.meta("oai_checked_at", "0") or 0)
    except ValueError:
        last = 0.0
    if time.time() - last < REFRESH_AFTER_S:
        return False
    with _job_lock:
        if _job.get("running"):
            return False
    lib.set_meta("oai_checked_at", time.time())
    return bool(start("update").get("success"))


# ── 三件事 ────────────────────────────────────────────────────────────────


def _import_metadata(lib: ArxivLibrary, categories: Sequence[str]) -> None:
    need = NEED_BYTES_SUBSET if categories else NEED_BYTES_METADATA
    free = _free_bytes(library_dir())
    if free < need:
        raise RuntimeError(
            f"硬盘剩 {free / 1024**3:.1f} GB,建文献库要留 {need / 1024**3:.0f} GB"
            + ("" if categories else "(只要几个分类的话,指定分类能小很多)")
        )
    _ensure_pyarrow()
    import pyarrow.parquet as pq

    api = _hf()
    files = _files(api, "metadata")
    if not files:
        raise RuntimeError(f"{DATASET}@{REVISION[:8]} 里没找到 metadata/*.parquet")
    done = set(filter(None, lib.meta("metadata_done").split(",")))
    if lib.meta("categories", "") != ",".join(categories):
        done = set()  # 分类换了:从头导
    lib.set_meta("categories", ",".join(categories))
    lib.bulk_mode(True)
    total = 0
    for i, name in enumerate(files, 1):
        if name in done:
            continue
        _say(f"下载元数据 {i}/{len(files)}", files_total=len(files), files_done=i - 1)
        local = _download(api, name)
        _say(f"导入元数据 {i}/{len(files)}", files_total=len(files), files_done=i - 1)
        pf = pq.ParquetFile(local)
        cols = map_columns(pf.schema_arrow.names)
        if "paper_id" not in cols:
            raise RuntimeError(f"{name} 里没有论文编号这一列:{pf.schema_arrow.names}")
        for batch in pf.iter_batches(batch_size=_BATCH, columns=sorted(set(cols.values()))):
            total += lib.upsert(to_rows(batch.to_pydict(), cols, categories))
            _say(f"导入元数据 {i}/{len(files)}", files_total=len(files), files_done=i - 1, rows=total)
        done.add(name)
        lib.set_meta("metadata_done", ",".join(sorted(done)))
        try:
            os.remove(local)  # 导完就删:硬盘上不同时留两份
        except OSError:
            pass
    _say("建全文索引(几分钟)", rows=total)
    lib.bulk_mode(False)
    lib.set_meta("snapshot_date", SNAPSHOT_DATE)
    lib.set_meta("oai_through", lib.meta("oai_through") or SNAPSHOT_DATE)
    _incremental(lib, categories)


def _incremental(lib: ArxivLibrary, categories: Sequence[str] = ()) -> None:
    """快照(或上次)之后的改动。按天推进 —— 断了下次从断的那天接着来。"""
    if not lib.ready():
        raise RuntimeError("文献库还没建好,先同步 metadata")
    from core.arxiv_client import list_records

    cats = [c for c in (categories or lib.meta("categories").split(",")) if c]
    since = lib.meta("oai_through") or SNAPSHOT_DATE
    _say(f"增量更新:{since} 之后的新论文")
    pending: List[Dict[str, Any]] = []
    gone: List[str] = []
    newest, n = since, 0
    for pid, row, stamp in list_records(since):
        if row is None:
            gone.append(pid)
        elif not cats or any(c == w or c.startswith(w + ".") for c in row["categories"].split() for w in cats):
            pending.append(row)
        newest = max(newest, stamp[:10] or newest)
        if len(pending) >= 1000:
            n += lib.upsert(pending)
            pending = []
            _say(f"增量更新:已写入 {n} 篇(到 {newest})", rows=n)
    n += lib.upsert(pending)
    if gone:
        lib.delete(gone)
    # 记到「上一天」:同一天里晚些时候新出的论文,下次还会被问到(重复的按编号覆盖,不会多出来)。
    through = (datetime.strptime(newest, "%Y-%m-%d") - timedelta(days=1)).date().isoformat() if newest else since
    lib.set_meta("oai_through", max(through, since))
    lib.set_meta("oai_checked_at", time.time())
    _say(f"增量更新完成:{n} 篇新增或改动,{len(gone)} 篇撤下", rows=n)


def _download_paper_text(lib: ArxivLibrary, _categories: Sequence[str] = ()) -> None:
    """70 GB 全文分片整份下到本机,并建「编号 → 分片 / 行组」的索引(只读编号那一列)。"""
    free = _free_bytes(library_dir())
    if free < NEED_BYTES_PAPER_TEXT:
        raise RuntimeError(f"硬盘剩 {free / 1024**3:.1f} GB,全文分片要 {NEED_BYTES_PAPER_TEXT / 1024**3:.0f} GB")
    _ensure_pyarrow()
    import pyarrow.parquet as pq

    api = _hf()
    files = _files(api, "paper_text")
    for i, name in enumerate(files, 1):
        _say(f"下载全文分片 {i}/{len(files)}", files_total=len(files), files_done=i - 1)
        local = _download(api, name)
        pf = pq.ParquetFile(local)
        id_col = next((c for c in _TEXT_ID if c in pf.schema_arrow.names), None)
        if id_col is None:
            raise RuntimeError(f"{name} 里没有论文编号这一列:{pf.schema_arrow.names}")
        rows = []
        for rg in range(pf.num_row_groups):
            ids = pf.read_row_group(rg, columns=[id_col]).column(0).to_pylist()
            rows.extend((str(p), local, rg) for p in ids if p)
        with lib._write, lib.connect() as conn:
            conn.executemany("INSERT OR REPLACE INTO text_index(paper_id, shard, row_group) VALUES (?, ?, ?)", rows)


def local_shard_text(lib: ArxivLibrary, paper_id: str) -> str:
    """本机下过全文分片的话,从分片里读这一篇;没下过 / 不在里面返回空串。"""
    with lib.connect() as conn:
        hit = conn.execute("SELECT shard, row_group FROM text_index WHERE paper_id=?", (paper_id,)).fetchone()
    if not hit or not os.path.exists(hit["shard"]):
        return ""
    import pyarrow.parquet as pq

    pf = pq.ParquetFile(hit["shard"])
    names = pf.schema_arrow.names
    id_col = next(c for c in _TEXT_ID if c in names)
    body = next((c for c in _TEXT_BODY if c in names), None)
    if body is None:
        return ""
    table = pf.read_row_group(int(hit["row_group"]), columns=[id_col, body]).to_pydict()
    for pid, text in zip(table[id_col], table[body]):
        if str(pid) == paper_id:
            return str(text or "")
    return ""


def _utc_today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def describe(st: Optional[Dict[str, Any]] = None) -> str:
    """给人看的一句话(工具结果里带上,模型照着说)。"""
    st = st or status()
    lib, job = st["library"], st["job"]
    if job.get("running"):
        return f"文献库同步进行中:{job.get('step', '')}"
    if job.get("error"):
        return f"上一次同步没做完:{job['error']}"
    if lib.get("ready"):
        return (
            f"本机 arXiv 文献库:{lib['papers']:,} 篇(快照 {lib.get('snapshot') or SNAPSHOT_DATE},"
            f"已更新到 {lib.get('updated_through') or '—'},今天 {_utc_today()})"
        )
    return "本机还没有 arXiv 文献库(建一次要下 1.6 GB 元数据,建好后检索离线、全库可搜)"
