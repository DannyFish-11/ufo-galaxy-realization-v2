"""launcher/compose_failures.py — compose 起不来时,到底是什么起不来

为什么单开一处
--------------
基础设施那一行以前只会说一句 ``Docker 启动异常 (rc=1)，详情见 logs/docker.log``。
真跑下来,同一句话底下至少有三种完全不同的事:

1. **``.env`` 缺必填变量** —— compose 在插值阶段就拒了,一个容器都没起。
   注意 compose 是**整份文件**一起插值的:``minio`` 的 ``${VAR:?}`` 会让只起
   ``nats`` 的命令也失败(docker-compose.yml 顶部就写着这一条)。
   这种情况跟 Docker 本身一点关系都没有,而那句话把人指向了 Docker。
2. **拉不到镜像** —— 守护进程好好的,compose 也跑起来了,是网络/代理/镜像源的事。
3. **端口被占** —— 本机已经有东西占着 4222 / 6379 这些口。

三种的下一步动作完全不同。混成一句"启动异常"等于什么都没说,而且指错了方向 ——
第 1 种尤其:人会去查 Docker,而真正该改的是 ``.env``。

判据只认**明确的证据**
----------------------
每一条都对着 compose 自己吐的原话匹配。认不出就是 ``UNKNOWN`` ——
不猜一个"最像"的,猜错了比不说更费时间。
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

from core.log_locations import log_hint

#: compose 在插值阶段就拒了(``${VAR:?message}`` 没给值)。
FAIL_MISSING_ENV = "missing_env"
#: 镜像拉不下来(网络 / 代理 / registry 拒绝)。
FAIL_IMAGE_PULL = "image_pull"
#: 端口被别的进程占了。
FAIL_PORT_IN_USE = "port_in_use"
#: 镜像仓库限流(Docker Hub 匿名拉取的每日额度)。
#:
#: 单独一类是因为**下一步完全不同**:这不是网断了、也不是源不对,
#: 等一会儿或者登录一下就好。归进"拉不到镜像"会让人去折腾代理和镜像源,
#: 而那两样都没问题。真跑里遇到的原话是 "429 Too Many Requests"。
FAIL_RATE_LIMITED = "rate_limited"
#: 引擎在,但 compose **连不上它的 API socket**。
#:
#: 这一类是真跑里挖出来的,而且最容易被误判:Podman 装好之后 ``podman info``
#: 是通的 —— 引擎确实在 —— 但 ``podman compose`` 转发给 docker-compose 之后,
#: 后者要连 ``unix:///run/podman/podman.sock``,那个 socket 是另一件事。
#: 没有这一类时它落进"原因未能判定",于是人去查引擎,而引擎根本没问题。
FAIL_API_SOCKET = "api_socket"
#: 认不出。**不猜**。
FAIL_UNKNOWN = "unknown"

#: 每一类给一句"下一步该干什么"。没有下一步的类别不许出现在这里。
FAIL_ADVICE = {
    FAIL_MISSING_ENV: "补上 .env 里这几个键(值见 .env.example)后重跑 —— 这不是 Docker 的问题",
    # 这一条刻意**不提运行时的名字** —— 措辞里写死 "Docker",跑 Podman 的人
    # 就会看到"Podman 拉不到镜像 …… Docker 本身是好的"。名字由 describe 那边带。
    FAIL_IMAGE_PULL: "拉镜像被拒/超时 —— 查网络或换镜像源后重跑;引擎本身是好的",
    FAIL_PORT_IN_USE: "端口已被占用 —— 停掉占用的进程,或改 docker-compose.yml 的端口映射",
    FAIL_RATE_LIMITED: (
        "镜像仓库限流了(匿名拉取有每日额度)—— 网络和镜像源都没问题。"
        "等额度回来,或 `docker login` 后重跑,或换一个镜像源"
    ),
    FAIL_API_SOCKET: (
        "compose 是通过这个 socket 跟引擎说话的。"
        "Podman:socket 和引擎是两回事,`podman info` 通不代表它起来了;"
        "Docker:多半是守护进程没跑"
    ),
    FAIL_UNKNOWN: log_hint("docker"),
}

_MISSING_ENV_RE = re.compile(r"required variable ([A-Z_][A-Z0-9_]*) is missing a value")
_PORT_RE = re.compile(r"(?:bind|port) .*?(\d{2,5}).*?(?:already in use|address already in use)", re.I)

#: API socket 连不上的原话。**必须排在拉镜像那一类之前**判 ——
#: 上游那句错误是 "unable to get image ...: failed to connect to the docker API",
#: 里面既有"取镜像"又有"连不上",按拉镜像判会把人指向网络,而网络毫无问题。
#: 限流的原话。**必须排在拉镜像那一类之前** —— 上游那句里同时有
#: "failed to resolve reference" 和 "429",按拉镜像判就会把人指向网络。
_RATE_LIMIT_MARKERS = (
    "429 too many requests",
    "toomanyrequests",
    "too many requests",
    "rate limit",
    "pull rate limit",
)

_API_SOCKET_MARKERS = (
    "failed to connect to the docker api",
    "podman.sock",
    "docker.sock: connect",
    "cannot connect to the docker daemon",
    "is the docker daemon running",
)

#: 拉镜像失败的**结构性**信号:compose 在拉取阶段会逐个镜像打
#: ``Image <名字> Error ...``。比关键词可靠 —— 上游的错误正文换了一茬又一茬
#: (真跑里见过 ``{"message":"Forbidden"}`` 这种连一个英文单词都不给的),
#: 但"哪个镜像出错了"这个结构是稳的。
_IMAGE_ERROR_RE = re.compile(r"^\s*Image\s+(\S+)\s+Error\b", re.M)

_PULL_MARKERS = (
    "failed to do request",
    "failed to copy",
    "error pulling image",
    "manifest unknown",
    "pull access denied",
    "toomanyrequests",
    "no such host",
    "connection refused while pulling",
    "tls handshake timeout",
)


def classify_compose_failure(log_text: str) -> Tuple[str, List[str]]:
    """compose 的输出 → ``(类别, 相关细节)``。

    *细节* 随类别而变:缺变量时是**变量名清单**,端口冲突时是端口号。
    认不出返回 ``(FAIL_UNKNOWN, [])`` —— 空清单和"没查过"由类别本身区分。

    顺序是有讲究的:缺变量排最前。插值失败时 compose 根本没开始拉镜像,
    但它的输出里可能同时含有别的噪声,先匹配到镜像那一类就会把人指错方向。
    """
    text = log_text or ""
    if not text.strip():
        return FAIL_UNKNOWN, []

    names = _MISSING_ENV_RE.findall(text)
    if names:
        seen: List[str] = []
        for n in names:
            if n not in seen:
                seen.append(n)
        return FAIL_MISSING_ENV, seen

    low = text.lower()
    port = _PORT_RE.search(text)
    if port or "address already in use" in low:
        return FAIL_PORT_IN_USE, [port.group(1)] if port else []

    if any(marker in low for marker in _RATE_LIMIT_MARKERS):
        return FAIL_RATE_LIMITED, []

    if any(marker in low for marker in _API_SOCKET_MARKERS):
        sock = re.search(r"(unix://\S*?\.sock|/\S*?\.sock)", text)
        return FAIL_API_SOCKET, [sock.group(1)] if sock else []

    if any(marker in low for marker in _PULL_MARKERS):
        return FAIL_IMAGE_PULL, []

    # 关键词都没命中,再看结构:有没有哪个镜像被标成 Error。
    # 放在最后是因为它最宽 —— 前面几类(限流 / socket / 缺变量)都比它具体。
    images = _IMAGE_ERROR_RE.findall(text)
    if images:
        seen: List[str] = []
        for name in images:
            if name not in seen:
                seen.append(name)
        return FAIL_IMAGE_PULL, seen

    return FAIL_UNKNOWN, []


def describe_compose_failure(log_text: str, *, runtime_name: str = "Docker") -> str:
    """一行人话,直接给基础设施那一行用。

    不带 ``rc=`` —— 返回码对着屏幕的人没有任何意义,它只是"失败了"的另一种写法。
    """
    kind, detail = classify_compose_failure(log_text)
    if kind == FAIL_MISSING_ENV:
        keys = ", ".join(detail[:4]) + ("…" if len(detail) > 4 else "")
        return f".env 缺必填变量 ({keys}) — {FAIL_ADVICE[kind]}"
    if kind == FAIL_PORT_IN_USE:
        where = f" ({detail[0]})" if detail else ""
        return f"端口被占用{where} — {FAIL_ADVICE[kind]}"
    if kind == FAIL_RATE_LIMITED:
        return f"{runtime_name} 被镜像仓库限流 — {FAIL_ADVICE[kind]}"
    if kind == FAIL_API_SOCKET:
        # 这里**不断言引擎在不在** —— 分类器只看到了 compose 的报错,没查过引擎。
        # Podman 上确实是"引擎在、socket 没起来",Docker 上多半是守护进程没跑,
        # 两种都可能。说死一种就有一半时候是假话。
        where = f" {detail[0]}" if detail else ""
        return f"{runtime_name} 的 API socket 连不上{where} — {FAIL_ADVICE[kind]}"
    if kind == FAIL_IMAGE_PULL:
        which = f"({detail[0]}{'…' if len(detail) > 1 else ''}) " if detail else ""
        return f"{runtime_name} 拉不到镜像 {which}— {FAIL_ADVICE[kind]}"
    return f"{runtime_name} 启动失败(原因未能判定) — {FAIL_ADVICE[kind]}"


def read_compose_log_tail(path: Optional[str], *, max_bytes: int = 20000) -> str:
    """读 ``logs/docker.log`` 的尾部。读不到返回空串 —— 读不到不是一种失败原因。"""
    if not path:
        return ""
    try:
        with open(path, "rb") as fh:
            try:
                fh.seek(-max_bytes, 2)
            except OSError:
                fh.seek(0)
            return fh.read().decode("utf-8", "replace")
    except OSError:
        return ""


__all__ = [
    "FAIL_MISSING_ENV",
    "FAIL_IMAGE_PULL",
    "FAIL_PORT_IN_USE",
    "FAIL_API_SOCKET",
    "FAIL_RATE_LIMITED",
    "FAIL_UNKNOWN",
    "FAIL_ADVICE",
    "classify_compose_failure",
    "describe_compose_failure",
    "read_compose_log_tail",
]
