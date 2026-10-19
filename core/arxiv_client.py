"""arXiv 的**唯一**出口:https、全进程每 3 秒最多一次请求、同一时刻只有一条连接。

arXiv 的接口使用条款(https://info.arxiv.org/help/api/tou.html)写得很清楚:多次调用之间至少
隔 3 秒,同一时刻只用一条连接。仓库里原先有两处各自直连 ``http://export.arxiv.org/api/query``
(``core/academic_retrieval.py`` 的兜底、``nodes/Node_97_AcademicSearch``),都没有限速 ——
智能体一口气问几次就会被封,而被封的症状是「arXiv 一直搜不到东西」,没有任何地方会说为什么。

这里收口三件事:

* ``search(query)``           —— 在线检索(API,Atom),本地文献库没建好时的兜底;
* ``list_records(since)``     —— OAI-PMH 增量元数据(每天的新论文),本地文献库的更新路;
* ``fetch_text(paper_id)``    —— **单篇**全文:先要 arXiv 的 HTML 版(2023-12 之后的论文大多有),
  没有再要 PDF 抽文字。只在本地缓存里没有时才走这里。

全部是**同步**函数(调用方在工作线程里调 —— 限速本来就要睡,不能睡在事件循环上)。
"""

from __future__ import annotations

import html
import io
import logging
import re
import threading
import time
import xml.etree.ElementTree as ET
from typing import Any, Dict, Iterator, List, Optional, Tuple

logger = logging.getLogger("Galaxy.ArxivClient")

API_URL = "https://export.arxiv.org/api/query"
#: OAI-PMH 新址在前,旧址兜底(arXiv 迁过一次)。
OAI_URLS = ("https://oaipmh.arxiv.org/oai", "https://export.arxiv.org/oai2")
HTML_URL = "https://arxiv.org/html/{id}"
PDF_URL = "https://export.arxiv.org/pdf/{id}"

#: 使用条款:两次请求之间至少 3 秒。
MIN_INTERVAL_S = 3.0
#: 被 503 / Retry-After 要求等的最长时间 —— 再久就放弃这一次,别把调用方挂住。
MAX_RETRY_AFTER_S = 60.0

_ATOM = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
_OAI = {"oai": "http://www.openarchives.org/OAI/2.0/", "ax": "http://arxiv.org/OAI/arXiv/"}

_gate = threading.Lock()
_last_call = [0.0]


def _user_agent() -> str:
    try:
        from core.version import GALAXY_VERSION

        return f"Galaxy-Academic/{GALAXY_VERSION} (local research assistant; polite: 1 req/3s)"
    except Exception:  # noqa: BLE001
        return "Galaxy-Academic (local research assistant; polite: 1 req/3s)"


def _get(url: str, params: Optional[Dict[str, Any]] = None, *, timeout: float = 60.0):
    """一次 GET:排队等到离上一次满 3 秒;同一时刻只有一个请求在飞。返回 httpx.Response。"""
    import httpx

    with _gate:
        for attempt in range(3):
            wait = MIN_INTERVAL_S - (time.monotonic() - _last_call[0])
            if wait > 0:
                time.sleep(wait)
            try:
                resp = httpx.get(
                    url,
                    params=params,
                    timeout=timeout,
                    headers={"User-Agent": _user_agent()},
                    follow_redirects=True,
                )
            finally:
                _last_call[0] = time.monotonic()
            if resp.status_code == 503 and attempt < 2:
                # 「太快了 / 正忙」:照它说的等,但有上限。
                try:
                    after = float(resp.headers.get("Retry-After", "10"))
                except ValueError:
                    after = 10.0
                time.sleep(min(max(after, MIN_INTERVAL_S), MAX_RETRY_AFTER_S))
                continue
            return resp
    return resp


# ── 在线检索(API) ──────────────────────────────────────────────────────────


def _text(el: Optional[ET.Element]) -> str:
    return " ".join((el.text or "").split()) if el is not None else ""


def parse_atom(xml_text: str) -> List[Dict[str, Any]]:
    """API 的 Atom 结果 → 论文 dict(与 Node_97 ``/search`` 同形)。"""
    root = ET.fromstring(xml_text)
    papers: List[Dict[str, Any]] = []
    for entry in root.findall("atom:entry", _ATOM):
        url = _text(entry.find("atom:id", _ATOM))
        pid = re.sub(r"v\d+$", "", url.rsplit("/abs/", 1)[-1]) if url else ""
        cats = [c.get("term") for c in entry.findall("atom:category", _ATOM) if c.get("term")]
        primary = entry.find("arxiv:primary_category", _ATOM)
        papers.append(
            {
                "paper_id": pid,
                "title": _text(entry.find("atom:title", _ATOM)),
                "authors": [_text(a.find("atom:name", _ATOM)) for a in entry.findall("atom:author", _ATOM)],
                "abstract": _text(entry.find("atom:summary", _ATOM)),
                "published_date": _text(entry.find("atom:published", _ATOM))[:10],
                "url": url,
                "source": "arXiv",
                "primary_category": primary.get("term") if primary is not None else (cats[0] if cats else ""),
                "tags": ["arXiv", *cats],
                "doi": _text(entry.find("arxiv:doi", _ATOM)),
            }
        )
    return papers


def search(query: str, max_results: int = 10) -> List[Dict[str, Any]]:
    """在线检索。失败返回空列表(不把异常抛到对话里)。要分清「没搜到」和「没连上」,用 :func:`search_or_why`。"""
    return search_or_why(query, max_results)[0]


def search_or_why(query: str, max_results: int = 10) -> Tuple[List[Dict[str, Any]], str]:
    """在线检索 → ``(论文, 没成的原因)``;成了原因是空串。

    全面排查第 6 轮真跑:连不上 arXiv(代理不放行)时这里原先只回空列表,工具照样回 ``success: True, papers: []``
    —— 模型据此告诉人「没有相关论文」,而事实是一篇都没查成。没连上和没搜到是两件事,得说出来。
    """
    params = {
        "search_query": f"all:{query}",
        "start": 0,
        "max_results": max(1, min(int(max_results), 50)),
        "sortBy": "relevance",
        "sortOrder": "descending",
    }
    try:
        resp = _get(API_URL, params, timeout=30.0)
        resp.raise_for_status()
        return parse_atom(resp.text), ""
    except Exception as exc:  # noqa: BLE001
        logger.info("arXiv 在线检索失败: %s", exc)
        code = getattr(getattr(exc, "response", None), "status_code", None)
        if code:
            return [], f"arXiv 回了 HTTP {code},这次没查成"
        return [], f"没连上 arXiv(export.arxiv.org,{type(exc).__name__}),这次没查成 —— 不是没有相关论文"


# ── 增量元数据(OAI-PMH) ────────────────────────────────────────────────────


def parse_oai_record(rec: ET.Element) -> Tuple[str, Optional[Dict[str, Any]]]:
    """一条 OAI 记录 → ``(paper_id, 行)``;被撤下的记录行为 ``None``。"""
    header = rec.find("oai:header", _OAI)
    ident = _text(header.find("oai:identifier", _OAI)) if header is not None else ""
    pid = ident.rsplit(":", 1)[-1] if ident else ""
    if header is not None and header.get("status") == "deleted":
        return pid, None
    meta = rec.find("oai:metadata/ax:arXiv", _OAI)
    if meta is None:
        return pid, None
    authors = []
    for a in meta.findall("ax:authors/ax:author", _OAI):
        name = " ".join(x for x in (_text(a.find("ax:forenames", _OAI)), _text(a.find("ax:keyname", _OAI))) if x)
        if name:
            authors.append(name)
    cats = _text(meta.find("ax:categories", _OAI)).split()
    pid = _text(meta.find("ax:id", _OAI)) or pid
    return pid, {
        "paper_id": pid,
        "title": _text(meta.find("ax:title", _OAI)),
        "abstract": _text(meta.find("ax:abstract", _OAI)),
        "authors": "; ".join(authors),
        "categories": " ".join(cats),
        "primary_category": cats[0] if cats else "",
        "first_date": _text(meta.find("ax:created", _OAI))[:10],
        "updated": _text(meta.find("ax:updated", _OAI))[:10],
        "license": _text(meta.find("ax:license", _OAI)),
        "doi": _text(meta.find("ax:doi", _OAI)),
        "journal_ref": _text(meta.find("ax:journal-ref", _OAI)),
    }


def list_records(since: str) -> Iterator[Tuple[str, Optional[Dict[str, Any]], str]]:
    """``since``(YYYY-MM-DD)之后有改动的全部记录:``(paper_id, 行或 None, 这条的 datestamp)``。

    按 resumptionToken 一页一页翻;每页之间同样守 3 秒。新址不通就换旧址。
    """
    for base in OAI_URLS:
        params: Dict[str, Any] = {"verb": "ListRecords", "metadataPrefix": "arXiv", "from": since}
        try:
            while True:
                resp = _get(base, params, timeout=120.0)
                resp.raise_for_status()
                root = ET.fromstring(resp.content)
                err = root.find("oai:error", _OAI)
                if err is not None:
                    if err.get("code") == "noRecordsMatch":
                        return
                    raise RuntimeError(f"OAI-PMH: {err.get('code')}: {_text(err)}")
                for rec in root.findall("oai:ListRecords/oai:record", _OAI):
                    header = rec.find("oai:header", _OAI)
                    stamp = _text(header.find("oai:datestamp", _OAI)) if header is not None else ""
                    pid, row = parse_oai_record(rec)
                    if pid:
                        yield pid, row, stamp
                token = root.find("oai:ListRecords/oai:resumptionToken", _OAI)
                if token is None or not (token.text or "").strip():
                    return
                params = {"verb": "ListRecords", "resumptionToken": token.text.strip()}
        except GeneratorExit:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.info("OAI-PMH %s 不可用: %s", base, exc)
            continue
    raise RuntimeError("arXiv 的 OAI-PMH 两个地址都不通")


# ── 单篇全文 ─────────────────────────────────────────────────────────────────

_TAG = re.compile(r"<[^>]+>")
_DROP = re.compile(r"<(script|style|nav|header|footer)[^>]*>.*?</\1>", re.S | re.I)


def html_to_text(page: str) -> str:
    """arXiv HTML 版 → 纯文字(段落保留换行)。只为喂模型读,不追求排版。"""
    body = page.split("<article", 1)[-1] if "<article" in page else page
    body = _DROP.sub(" ", body)
    body = re.sub(r"</(p|div|h[1-6]|li|section|tr)>", "\n", body, flags=re.I)
    text = html.unescape(_TAG.sub(" ", body))
    lines = (" ".join(ln.split()) for ln in text.splitlines())
    return "\n".join(ln for ln in lines if ln)


def pdf_to_text(data: bytes) -> str:
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError:
        from PyPDF2 import PdfReader  # type: ignore
    reader = PdfReader(io.BytesIO(data))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def fetch_text(paper_id: str) -> Tuple[str, str]:
    """单篇全文 ``(文字, 来源)``;拿不到返回 ``("", 原因)``。先 HTML,再 PDF。"""
    try:
        resp = _get(HTML_URL.format(id=paper_id), timeout=60.0)
        if resp.status_code == 200 and "text/html" in resp.headers.get("content-type", ""):
            text = html_to_text(resp.text)
            if len(text) > 2000:  # 太短的多半是「这篇没有 HTML 版」的说明页
                return text, "arxiv_html"
    except Exception as exc:  # noqa: BLE001
        logger.info("arXiv HTML 版取不到 %s: %s", paper_id, exc)
    try:
        resp = _get(PDF_URL.format(id=paper_id), timeout=120.0)
        resp.raise_for_status()
        text = pdf_to_text(resp.content)
        if text.strip():
            return text, "arxiv_pdf"
        return "", "PDF 里抽不出文字(多半是扫描件)"
    except Exception as exc:  # noqa: BLE001
        return "", f"arXiv 取全文失败:{exc}"
