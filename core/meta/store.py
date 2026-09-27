"""core/meta/store.py — artifact 的持久存储：只追加，内容寻址，不可悄悄改写。

布局（``runtime/meta/`` 下，``runtime/`` 默认不入库）::

    artifacts/<型>/<内容哈希前 16 位>.json   一件一个文件
    index.jsonl                              追加式索引：id、型、时间、产生者、父
    commits.jsonl                            追加式生效记录：哪个可写面、哪个补丁、凭哪个裁决

「不可悄悄改写」是结构保证，不是约定：同一个 id 已经存在时，写入的内容必须与已有的
**逐字节相等**（内容寻址下这是必然的），否则拒绝。想改一条结论只能写一条新的、并在
lineage 里指向旧的 —— 历史永远都在。
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from core.atomic_json import atomic_write_json
from core.meta.artifacts import ARTIFACT_TYPES, Artifact, ArtifactError, verify_integrity

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_STORE_ROOT = REPO_ROOT / "runtime" / "meta"


class ArtifactStore:
    """元层 artifact 的只追加存储。线程安全（单进程内）。"""

    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = Path(root) if root is not None else DEFAULT_STORE_ROOT
        self._lock = threading.Lock()

    # -- 路径 ------------------------------------------------------------------

    def _path_of(self, artifact_id: str) -> Path:
        artifact_type, _, digest = artifact_id.partition(":")
        if artifact_type not in ARTIFACT_TYPES or len(digest) != 16 or not digest.isalnum():
            raise ArtifactError(f"不合法的 artifact id：{artifact_id!r}")
        return self.root / "artifacts" / artifact_type / f"{digest}.json"

    def _append_line(self, name: str, record: Dict[str, Any]) -> None:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    def _read_lines(self, name: str) -> Iterator[Dict[str, Any]]:
        path = self.root / name
        if not path.is_file():
            return
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict):
                yield record

    # -- 写 --------------------------------------------------------------------

    def put(self, artifact: Artifact) -> str:
        """存一件 artifact，返回 id。重复写同一内容是幂等的；同 id 不同内容直接拒绝。"""
        if not verify_integrity(artifact):
            raise ArtifactError(f"{artifact.artifact_id} 的内容与 id 对不上 —— 被改过的 artifact 不予受理")
        path = self._path_of(artifact.artifact_id)
        with self._lock:
            if path.is_file():
                existing = Artifact.from_dict(json.loads(path.read_text(encoding="utf-8")))
                if not verify_integrity(existing):
                    raise ArtifactError(f"存储里的 {artifact.artifact_id} 已被篡改（内容与 id 对不上）—— 历史不可改写")
                if existing.content_hash != artifact.content_hash:
                    raise ArtifactError(f"{artifact.artifact_id} 已存在且内容不同 —— 历史不可改写")
                return artifact.artifact_id
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(path, artifact.to_dict(), indent=2, ensure_ascii=False)
            self._append_line(
                "index.jsonl",
                {
                    "artifact_id": artifact.artifact_id,
                    "artifact_type": artifact.artifact_type,
                    "created_at": artifact.created_at,
                    "operator": artifact.lineage.operator,
                    "parents": list(artifact.lineage.parents),
                },
            )
        return artifact.artifact_id

    def record_commit(self, scope: str, patch_id: str, verdict_id: str, committed_at: str) -> None:
        """记一次生效：哪个可写面、哪个补丁、凭哪个裁决。只追加。"""
        with self._lock:
            self._append_line(
                "commits.jsonl",
                {"scope": scope, "patch_id": patch_id, "verdict_id": verdict_id, "committed_at": committed_at},
            )

    # -- 读 --------------------------------------------------------------------

    def get(self, artifact_id: str) -> Optional[Artifact]:
        try:
            path = self._path_of(artifact_id)
        except ArtifactError:
            return None
        if not path.is_file():
            return None
        artifact = Artifact.from_dict(json.loads(path.read_text(encoding="utf-8")))
        return artifact if verify_integrity(artifact) else None

    def list(self, artifact_type: Optional[str] = None, limit: Optional[int] = None) -> List[Artifact]:
        """按写入顺序列出（最新的在后）。"""
        ids = [
            r["artifact_id"]
            for r in self._read_lines("index.jsonl")
            if artifact_type is None or r.get("artifact_type") == artifact_type
        ]
        if limit is not None:
            ids = ids[-limit:]
        out = [self.get(i) for i in ids]
        return [a for a in out if a is not None]

    def ancestry(self, artifact_id: str, max_depth: int = 64) -> List[Artifact]:
        """沿 lineage.parents 往上走，返回祖先（不含自己），广度优先。"""
        seen = {artifact_id}
        frontier = [artifact_id]
        out: List[Artifact] = []
        for _ in range(max_depth):
            nxt: List[str] = []
            for current in frontier:
                artifact = self.get(current)
                if artifact is None:
                    continue
                for parent in artifact.lineage.parents:
                    if parent in seen:
                        continue
                    seen.add(parent)
                    found = self.get(parent)
                    if found is not None:
                        out.append(found)
                        nxt.append(parent)
            if not nxt:
                break
            frontier = nxt
        return out

    def commits(self, scope: Optional[str] = None) -> List[Dict[str, Any]]:
        return [r for r in self._read_lines("commits.jsonl") if scope is None or r.get("scope") == scope]

    def last_commit_at(self, scope: str) -> str:
        """这个可写面最近一次生效的时间；从未生效返回空串。"""
        stamps = [str(r.get("committed_at", "")) for r in self.commits(scope)]
        return max(stamps) if stamps else ""


__all__ = ["DEFAULT_STORE_ROOT", "ArtifactStore"]
