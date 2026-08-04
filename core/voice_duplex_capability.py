"""core/voice_duplex_capability.py —— 双工语音能力判定（按真实供给，不按开关）

从 ``core/voice_duplex_session.py`` 拆出来的一件独立事情：**当前这台机器、当前这个
档位，到底具不具备双工供给**。会话/协议机器与"能不能"是两个关注点，面板与诊断要问的
也只是后者，所以单独成模块（顺便让那个文件回到复杂度基线内）。

判据的原料本来就散在仓库各处，这里只做汇总，不另造第二套：

* ``PROVIDER_REGISTRY`` —— 每家的 ``realtime_models`` / ``default_realtime_model``；
* ``DuplexSessionConfig.from_env()`` —— 端点推导、密钥三层解析、占位符过滤、
  本地端点免 key、B 档原生自动推导，"能不能建连"它已经回答得很完整；
* ``core.modality_capability.negotiate()`` —— 当前档位的原生听/说结论。

账单事实明写在这里而不是藏着：云端 realtime 按分钟计费，判定里带 ``metered=True``。
它**不**阻止自动启用（产品决定是「档位具备就自动开」，本机原生与云端一视同仁），
但计费这件事必须可见 —— 面板显示得出，自动开启时日志也说一次，不能悄悄开始花钱。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict

from core.voice_duplex_session import DuplexSessionConfig, is_local_endpoint

logger = logging.getLogger("Galaxy.VoiceDuplexCapability")


@dataclass(frozen=True)
class DuplexCapability:
    """当前档位到底具不具备双工供给 —— 一份**如实**的判定，而不是一个开关。

    Fields
    ------
    available
        供给存在（端点 + 凭据 / 本地原生服务都齐了）。
    source
        ``"native_local"``（本机全模态 server）/ ``"cloud_realtime"``（云端 realtime）/ ``""``。
    metered
        这条供给是**按量计费**的（云端 realtime 按分钟计）。它不再阻止自动启用
        —— 那是产品决定，已改为「档位具备就自动开」—— 但账单事实必须如实带出来：
        面板要显示得出「正在用计费链路」，自动开启时也要在日志里说一次，
        不能悄悄开始花钱。
    reason
        为什么可用 / 为什么不可用。缺了它，"开了开关却没生效"完全无从排查。
    """

    available: bool
    source: str = ""
    metered: bool = False
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "available": self.available,
            "source": self.source,
            "metered": self.metered,
            "reason": self.reason,
        }


def duplex_capability() -> DuplexCapability:
    """按**真实供给**判定双工能力：端点、凭据、以及当前档位模型的原生听/说。

    为什么要有这个函数
    ------------------
    ``duplex_enabled()`` 原先是一个纯环境开关（默认关），与「当前档位的模型到底有没有
    realtime 能力」**完全无关**。而判据的原料本来全都在：``PROVIDER_REGISTRY`` 维护着
    每家的 ``realtime_models``/``default_realtime_model``，``DuplexSessionConfig.from_env()``
    会按权威顺序解析密钥并过滤占位符，``core.modality_capability.negotiate()`` 给出
    当前档位的原生听/说结论。装了一整套判据，最外层那个「开不开」却不看它们。

    复用而非另造
    ------------
    能不能建连这件事，``from_env()`` 已经回答得很完整（端点推导、密钥三层解析、
    占位符过滤、本地端点免 key、B 档原生自动推导），所以这里**直接用它**当探针，
    不再写第二套判据 —— 两套判据必然漂移。

    本地端点额外多问一句档位
    ------------------------
    ``from_env()`` 的原生分支只看 ``GALAXY_NATIVE_AUDIO`` 这个**服务**开关。服务开着、
    但当前档位的模型压根不原生听/说时，推导出来的本地 realtime 地址是连不通的。
    所以本地这一支再问一次 ``negotiate()``：听和说都得是 native 才算数。
    """
    try:
        cfg = DuplexSessionConfig.from_env(probe=True)
    except Exception as exc:  # noqa: BLE001 — 判定失败不能让语音链路崩，按"不可用"处理
        return DuplexCapability(False, reason=f"双工配置探测异常: {exc}")
    if cfg is None:
        return DuplexCapability(
            False,
            reason="没有可用的 realtime 端点或密钥（详见 DuplexSessionConfig.from_env 的日志）",
        )

    if is_local_endpoint(cfg.url):
        try:
            from core.modality_capability import negotiate

            plan = negotiate()
            in_native = getattr(plan.audio_in, "mode", "") == "native"
            out_native = getattr(plan.audio_out, "mode", "") == "native"
        except Exception as exc:  # noqa: BLE001
            return DuplexCapability(False, reason=f"档位模态能力不可读: {exc}")
        if not (in_native and out_native):
            return DuplexCapability(
                False,
                source="native_local",
                reason=(
                    "本地 realtime 地址是由原生服务开关推导出来的，但当前档位的模型"
                    f"并不同时原生听/说（听={getattr(plan.audio_in, 'mode', '?')}、"
                    f"说={getattr(plan.audio_out, 'mode', '?')}）——连上去也是空转"
                ),
            )
        return DuplexCapability(True, source="native_local", reason="B 档原生听/说就绪，本机全模态 server 可直连")

    return DuplexCapability(
        True,
        source="cloud_realtime",
        metered=True,
        reason="云端 realtime 端点与密钥都在（按分钟计费）",
    )
