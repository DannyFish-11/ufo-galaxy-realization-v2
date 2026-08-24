"""core/weights_admission.py — 权重从哪来,以及允不允许执行它自带的代码
======================================================================

问题:这条路不需要任何注入就能被利用
------------------------------------
``core.local_model_backends`` 的 transformers 后端这样加载模型::

    tokenizer = AutoTokenizer.from_pretrained(load_target, trust_remote_code=True)
    model_obj = AutoModelForCausalLM.from_pretrained(..., trust_remote_code=True)

``trust_remote_code=True`` 的含义不是"加载权重时可能有风险",而是**模型仓库里的
``.py`` 文件会被直接执行**。下载下来就跑,在本进程里,以当前用户的身份。

而下载源默认指向第三方镜像(``core.memory._hf_mirror`` 把 ``HF_ENDPOINT`` 指到
``hf-mirror.com``,这是为了国内可达性,本身合理),且**下载路径上没有任何哈希或
签名校验**。两件事叠加起来:那个镜像,或任何能中间人它的人,可以在这台机器上执行
任意代码 —— 不需要提示注入、不需要模型配合、不需要用户做错任何事。

**这条路径绕过了 ``core.execution_isolation``** —— 它根本不走 ``SafeExecutor``,
所以刚建起来的容器边界对它一点用都没有。

本模块做什么
------------
把"这份权重允不允许被加载、允不允许执行它自带的代码"变成**一处可问的判据**。

三个维度互不冒充(与 ``core.speculative_draft`` 同款约束):

============  ================================================================
**来源**      从哪个主机下载的。不在白名单上 → 拒。
**格式**      ``safetensors`` / ``gguf`` 反序列化**不执行代码**;``pickle``
              (``.bin`` / ``.pt`` / ``.pth`` / ``.ckpt``)会。默认拒 pickle。
**自带代码**  仓库里的 ``.py``。默认**一律不执行**,除非该模型显式登记在白名单上;
              登记时连同指纹一起钉住,文件变了就再拒一次(挡 rug-pull)。
============  ================================================================

为什么是白名单而不是一刀切
--------------------------
``trust_remote_code=False`` 会让一部分模型加载不了(Qwen 系某些版本、不少国产模型
都依赖它)。一刀切会把用户现在能跑的东西打死,那样的闸最终会被人整个关掉 ——
**一道被关掉的闸比没有闸更糟,因为它还在报告里显示"已启用"**。

所以默认拒绝、按模型放行:你显式登记过的才允许,且登记的同时把指纹钉住。

"判不出来"不能被当成"允许"
--------------------------
远端 repo id 在真正下载之前是看不到文件的,所以格式那一维会是 ``unverified``。
这个取值**必须与 ``admitted`` 可区分** —— 把"我没看到"当成"我看过了没问题",
正是这类闸最典型的失效方式。``unverified`` 不放行自带代码。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("Galaxy.WeightsAdmission")

#: 判定取值。``unverified`` = **判不出来**,既不是允许也不是拒绝 —— 它必须
#: 与另外两个可区分,见模块头。
ADMISSION_VERDICTS: Tuple[str, ...] = ("admitted", "denied", "unverified")

#: 反序列化过程**不执行代码**的权重格式。
SAFE_WEIGHT_SUFFIXES: Tuple[str, ...] = (".safetensors", ".gguf")

#: 反序列化过程**会执行代码**的格式(Python pickle 协议)。
#: 这是 HuggingFace 上历次投毒事件的载体。
PICKLE_WEIGHT_SUFFIXES: Tuple[str, ...] = (".bin", ".pt", ".pth", ".ckpt")

#: 默认允许的权重下载主机。``hf-mirror.com`` 在列是因为它是本仓在国内的既定默认
#: (见 ``core.memory._hf_mirror``);把它排除会让国内根本下不动模型。它在列**不
#: 代表它可信** —— 正因为它是第三方镜像,自带代码那一维才必须默认拒绝。
DEFAULT_WEIGHT_HOSTS: Tuple[str, ...] = ("huggingface.co", "hf-mirror.com", "modelscope.cn")

#: 自带代码的指纹钉在这里。与 ``core.model_catalog`` 的状态文件同一处置:
#: **路径不做 env 覆盖** —— 状态文件的位置不是面板设置项。
_PIN_FILE = Path("runtime") / "weights_remote_code_pins.json"


@dataclass(frozen=True)
class WeightsAdmission:
    """这份权重的准入判定。"""

    verdict: str = "unverified"
    #: 允不允许执行仓库自带的 ``.py``。**默认假**。
    remote_code: bool = False
    #: 探到的下载主机;探不出来为空串。
    host: str = ""
    #: 探到的权重格式:``safetensors`` / ``gguf`` / ``pickle`` / ``unknown``。
    fmt: str = "unknown"
    #: 自带代码是否已按登记的指纹核对过。
    pinned: bool = False
    reason: str = ""

    @property
    def allowed(self) -> bool:
        """能不能加载。**只有 ``admitted`` 为真** —— ``unverified`` 不放行。"""
        return self.verdict == "admitted"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict,
            "remote_code": self.remote_code,
            "host": self.host,
            "fmt": self.fmt,
            "pinned": self.pinned,
            "reason": self.reason,
            "allowed": self.allowed,
        }


class WeightsRejected(RuntimeError):
    """权重没过准入 —— 显式拒绝加载,不静默放行。"""


# ══════════════════════════════════════════════════════════════════════════
# 开关
# ══════════════════════════════════════════════════════════════════════════


def _env_list(name: str) -> List[str]:
    """逗号分隔的环境变量 → 去空去空白的列表。"""
    raw = os.environ.get(name, "") or ""
    return [item.strip() for item in raw.split(",") if item.strip()]


def allowed_hosts() -> Tuple[str, ...]:
    """允许从哪些主机下权重。留空 = 用默认表(**不是**"允许所有")。"""
    override = _env_list("GALAXY_WEIGHTS_HOSTS")
    return tuple(override) if override else DEFAULT_WEIGHT_HOSTS


def remote_code_allowlist() -> Tuple[str, ...]:
    """允许执行自带代码的模型。默认空 —— **一个都不许**。"""
    return tuple(_env_list("GALAXY_TRUST_REMOTE_CODE"))


def pickle_allowed() -> bool:
    """允不允许加载 pickle 格式的权重。默认否。

    这是个真取舍:少数老模型只有 ``.bin``。但 pickle 反序列化等于执行任意代码,
    而 safetensors/gguf 现在覆盖了绝大多数模型,所以默认拒是站得住的。
    """
    return (os.environ.get("GALAXY_WEIGHTS_ALLOW_PICKLE", "0") or "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _wildcard_in(entries: Tuple[str, ...]) -> bool:
    return "*" in entries


# ══════════════════════════════════════════════════════════════════════════
# 探测:主机 / 格式 / 自带代码指纹
# ══════════════════════════════════════════════════════════════════════════


def download_host() -> str:
    """这台机器当前会从哪个主机下权重。

    判据走 ``HF_ENDPOINT``(``huggingface_hub`` / ``sentence-transformers`` 都读它,
    ``core.memory._hf_mirror`` 也是设的这一个),而不是自己另攒一套镜像配置 ——
    否则报告里说的主机和实际下载的主机会漂移。
    """
    raw = (os.environ.get("HF_ENDPOINT", "") or "").strip()
    if not raw:
        return "huggingface.co"
    without_scheme = raw.split("://", 1)[-1]
    return without_scheme.split("/", 1)[0].strip().lower()


def detect_format(local_path: Optional[str]) -> str:
    """看目录里实际有什么权重文件。

    拿不到本地路径(远端 repo id 还没下)时返回 ``unknown`` —— 那是"没看到",
    不是"没问题"。
    """
    if not local_path:
        return "unknown"
    path = Path(local_path)
    if path.is_file():
        suffix = path.suffix.lower()
        if suffix in SAFE_WEIGHT_SUFFIXES:
            return "safetensors" if suffix == ".safetensors" else "gguf"
        if suffix in PICKLE_WEIGHT_SUFFIXES:
            return "pickle"
        return "unknown"
    if not path.is_dir():
        return "unknown"

    found_safe = ""
    found_pickle = False
    try:
        for entry in path.rglob("*"):
            if not entry.is_file():
                continue
            suffix = entry.suffix.lower()
            if suffix == ".safetensors":
                found_safe = found_safe or "safetensors"
            elif suffix == ".gguf":
                found_safe = found_safe or "gguf"
            elif suffix in PICKLE_WEIGHT_SUFFIXES:
                found_pickle = True
    except OSError as exc:  # noqa: BLE001 — 目录读不动就是判不出来
        logger.debug("扫描权重目录失败,格式按 unknown 处理: %s", exc)
        return "unknown"

    # 安全格式在场就按安全格式算:transformers 优先加载 safetensors,同目录里
    # 残留的 .bin 不会被读到。反过来只有 pickle 才是真的要走 pickle。
    if found_safe:
        return found_safe
    if found_pickle:
        return "pickle"
    return "unknown"


def remote_code_files(local_path: Optional[str]) -> List[Path]:
    """仓库里那些**会被执行**的文件。"""
    if not local_path:
        return []
    path = Path(local_path)
    if not path.is_dir():
        return []
    try:
        return sorted(p for p in path.rglob("*.py") if p.is_file())
    except OSError as exc:  # noqa: BLE001
        logger.debug("扫描自带代码失败: %s", exc)
        return []


def remote_code_fingerprint(local_path: Optional[str]) -> str:
    """自带代码的指纹。**空串 = 判不出来**,与"没有自带代码"不是一回事。

    只指纹 ``.py``,不指纹整个权重目录 —— 一个 10GB 的模型全量哈希会让加载变得
    不可接受,而真正需要盯住的攻击面恰好就是这些会被执行的文件。变了就说明
    上游改了会执行的代码,那正是 rug-pull 的形状。
    """
    files = remote_code_files(local_path)
    if not files:
        # 目录里没有 .py:这是**确定的**"没有自带代码",不是判不出来。
        # 用一个固定标记而不是空串,好让它与"路径拿不到"区分开。
        return "none" if local_path and Path(local_path).is_dir() else ""

    root = Path(local_path or "")
    digest = hashlib.sha256()
    for entry in files:
        try:
            rel = entry.relative_to(root).as_posix()
            digest.update(rel.encode("utf-8"))
            digest.update(entry.read_bytes())
        except (OSError, ValueError) as exc:  # noqa: BLE001
            logger.debug("读取自带代码失败,指纹判不出来: %s", exc)
            return ""
    return digest.hexdigest()


# ══════════════════════════════════════════════════════════════════════════
# 指纹钉子
# ══════════════════════════════════════════════════════════════════════════


def _load_pins() -> Dict[str, str]:
    try:
        with open(_PIN_FILE, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:  # noqa: BLE001
        logger.warning("指纹钉子读不出来,按没有钉子处理: %s", exc)
        return {}


def pinned_fingerprint(model_ref: str) -> str:
    """这个模型登记过的指纹;没登记过为空串。"""
    return _load_pins().get(model_ref, "")


def pin_remote_code(model_ref: str, fingerprint: str) -> bool:
    """把当前自带代码的指纹钉住。返回是否写成功。

    刻意**不**在加载路径上自动调用 —— 自动钉住等于"第一次见到什么就信什么",
    那样这道闸只能挡住"上游后来改了",挡不住"上游一开始就是坏的"。钉子必须是
    人显式做的动作。
    """
    if not model_ref or not fingerprint:
        return False
    pins = _load_pins()
    pins[model_ref] = fingerprint
    try:
        _PIN_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_PIN_FILE, "w", encoding="utf-8") as handle:
            json.dump(pins, handle, ensure_ascii=False, indent=2, sort_keys=True)
        return True
    except OSError as exc:  # noqa: BLE001
        logger.warning("指纹钉子写不进去: %s", exc)
        return False


# ══════════════════════════════════════════════════════════════════════════
# 判据
# ══════════════════════════════════════════════════════════════════════════


def _host_ok(host: str) -> bool:
    allowed = allowed_hosts()
    if _wildcard_in(allowed):
        logger.warning("GALAXY_WEIGHTS_HOSTS 含 '*':权重下载主机白名单已被整个放开")
        return True
    return host in allowed


def _remote_code_verdict(model_ref: str, local_path: Optional[str]) -> Tuple[bool, bool, str]:
    """返回 ``(允许执行自带代码, 是否核对过指纹, 原因)``。"""
    allowlist = remote_code_allowlist()
    if not allowlist:
        return False, False, "自带代码默认不执行(GALAXY_TRUST_REMOTE_CODE 未登记任何模型)"
    if _wildcard_in(allowlist):
        logger.warning("GALAXY_TRUST_REMOTE_CODE 含 '*':**任何**模型仓库自带的 .py 都会被执行")
        return True, False, "自带代码已被 '*' 整个放开 —— 任何模型的 .py 都会执行"
    if model_ref not in allowlist:
        return False, False, f"{model_ref} 不在 GALAXY_TRUST_REMOTE_CODE 白名单上"

    pinned = pinned_fingerprint(model_ref)
    if not pinned:
        # 登记了但没钉指纹:放行,但**说清楚它没被核对过**。要求先钉才能用会让
        # 白名单变得难用到没人用;而如实说"没核对"至少让报告不撒谎。
        return True, False, f"{model_ref} 已登记,但没有钉指纹(上游改了不会被发现)"

    current = remote_code_fingerprint(local_path)
    if not current:
        return False, False, f"{model_ref} 钉过指纹,但这次算不出当前指纹 —— 判不出来,不放行"
    if current != pinned:
        return (
            False,
            True,
            f"{model_ref} 自带代码与登记的指纹不一致(上游可能改了会执行的代码)",
        )
    return True, True, f"{model_ref} 已登记且指纹一致"


def evaluate(model_ref: str, *, local_path: Optional[str] = None) -> WeightsAdmission:
    """这份权重的完整准入判定。**唯一判据处**。"""
    host = download_host()
    fmt = detect_format(local_path)

    if not _host_ok(host):
        return WeightsAdmission(
            verdict="denied",
            host=host,
            fmt=fmt,
            reason=f"下载主机 {host} 不在白名单上(GALAXY_WEIGHTS_HOSTS)",
        )

    if fmt == "pickle" and not pickle_allowed():
        return WeightsAdmission(
            verdict="denied",
            host=host,
            fmt=fmt,
            reason=(
                "权重是 pickle 格式(.bin/.pt/.pth/.ckpt),反序列化即执行代码;"
                "只有 safetensors/gguf 才默认允许(GALAXY_WEIGHTS_ALLOW_PICKLE 可放开)"
            ),
        )

    remote_code, pinned, why = _remote_code_verdict(model_ref, local_path)

    # 格式判不出来(远端 repo 还没下)时,**加载本身可以继续**(否则第一次下载
    # 永远进行不下去),但自带代码那一维不放行 —— 见模块头。
    if fmt == "unknown" and remote_code:
        remote_code = False
        why = f"{why};但这次看不到本地文件,自带代码不放行"

    verdict = "admitted" if fmt != "unknown" else "unverified"
    return WeightsAdmission(
        verdict=verdict,
        remote_code=remote_code,
        host=host,
        fmt=fmt,
        pinned=pinned,
        reason=why,
    )


def ensure_admitted(model_ref: str, *, local_path: Optional[str] = None) -> WeightsAdmission:
    """判定并在 ``denied`` 时抛。给"宁可不加载也不冒险"的调用点。"""
    decision = evaluate(model_ref, local_path=local_path)
    if decision.verdict == "denied":
        raise WeightsRejected(decision.reason)
    return decision


def weights_report(model_ref: str = "", *, local_path: Optional[str] = None) -> Dict[str, Any]:
    """只读诊断:这台机器现在的权重准入姿态。

    不传 ``model_ref`` 时只报全局姿态(主机、白名单规模、pickle 策略),不做
    单个模型的判定。
    """
    allowlist = remote_code_allowlist()
    report: Dict[str, Any] = {
        "host": download_host(),
        "allowed_hosts": list(allowed_hosts()),
        "host_ok": _host_ok(download_host()),
        "pickle_allowed": pickle_allowed(),
        "remote_code_allowlist_size": len(allowlist),
        "remote_code_wildcard": _wildcard_in(allowlist),
        "pinned_models": len(_load_pins()),
    }
    if model_ref:
        report["model"] = model_ref
        report["decision"] = evaluate(model_ref, local_path=local_path).to_dict()
    return report
