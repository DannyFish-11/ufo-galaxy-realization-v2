#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_two_local_openai_lanes.py

钉住：**本地可以同时有两台 OpenAI 兼容服务，而且它们伺候的不是同一只手。**

修的是什么
==========
``_register_local_openai`` 原来只认一台（``GALAXY_LOCAL_OPENAI_URL``），那是按
"核显上跑感知位"这一个场景写的。可 C/D 档本来就是双模型：**感知位在核显、推理位
在独显，两块加速器、两台服务**。只留一个槽位的后果是二选一 —— 接了核显那台，
独显那台就没有地方填地址。

推理位那条泳道的直接用途是 FreeToken（``ft serve`` 起 OpenAI ``/v1/*``，MoE
专用引擎），但泳道本身与引擎无关：vLLM、llama.cpp server 的 CUDA 后端讲的是
同一套协议。

两条泳道的差别不只是地址
========================
* **模态**：推理位是纯文本 —— 目录里两个推理位候选的 ``caps`` 里 vision/audio
  都是 False。给它标上"能看"，能力聚合会把"看"算到它头上，协商层于是不挂视觉
  通道 —— 现场表现是"它说自己能看，可什么都看不见"；
* **硬件档**：核显 ``gpu_quantized`` vs 独显 ``gpu_full``；
* **量化档**：核显侧惯例 q4；FreeToken 发的是 FP8/NVFP4/BF16 或它自己的 FTW，
  **没有一个是 q4**，所以如实填 ``none``（"没声明"），不编一个。

本文件用**真的 HTTP 服务端**（如实实现 ``/v1/models`` 与 ``/v1/chat/completions``）
而不是打桩：那两个端点就是 FreeToken 的对外契约，走真服务才和真引擎同一条路。
"""

from __future__ import annotations

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import core.multi_llm_router as R

PERC_ID = "MiniCPM-o-4_5-int4-ov"  # OpenVINO 那套命名
REAS_ID = "Qwen3.6-35B-A3B"  # FreeToken 取 --model 路径的 basename


def _spawn(model_id: str, reply: str = "好"):
    hits = {"chat": 0, "auth": []}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):  # 别把测试输出刷满
            pass

        def _json(self, obj):
            b = json.dumps(obj).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            if self.path.rstrip("/").endswith("/models"):
                hits["auth"].append(self.headers.get("Authorization"))
                return self._json({"data": [{"id": model_id}]})
            self.send_response(404)
            self.end_headers()

        def do_POST(self):
            if "chat/completions" in self.path:
                hits["chat"] += 1
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                return self._json(
                    {
                        "choices": [{"message": {"role": "assistant", "content": reply}}],
                        "usage": {"prompt_tokens": 5, "completion_tokens": 1},
                    }
                )
            self.send_response(404)
            self.end_headers()

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"127.0.0.1:{srv.server_port}", hits


@pytest.fixture
def perception():
    srv, addr, hits = _spawn(PERC_ID)
    yield addr, hits
    srv.shutdown()


@pytest.fixture
def reasoning():
    srv, addr, hits = _spawn(REAS_ID)
    yield addr, hits
    srv.shutdown()


@pytest.fixture(autouse=True)
def _no_lane_env(monkeypatch):
    """每条用例自己决定配哪条泳道 —— 不许继承外面的环境。"""
    for lane in R._LOCAL_OPENAI_LANES:
        for suffix in ("URL", "MODEL", "SERVES", "KEY"):
            monkeypatch.delenv(f"{lane['env_prefix']}_{suffix}", raising=False)
    yield


class TestTheOldLaneDidNotMove:
    """加一条泳道是加法不是改法：只填老那个变量时，行为必须与加泳道之前一致。"""

    def test_only_the_perception_lane_registers(self, perception, monkeypatch):
        addr, _ = perception
        monkeypatch.setenv("GALAXY_LOCAL_OPENAI_URL", addr)
        r = R.MultiLLMRouter()
        assert "local_openai" in r.providers
        assert "reasoning_openai" not in r.providers, "没配地址的泳道不该冒出来"

    def test_its_facts_are_unchanged(self, perception, monkeypatch):
        addr, _ = perception
        monkeypatch.setenv("GALAXY_LOCAL_OPENAI_URL", addr)
        cfg = R.MultiLLMRouter().providers["local_openai"]
        assert cfg.supports_vision and cfg.supports_audio and cfg.multimodal
        assert cfg.hardware_tier == "gpu_quantized"
        assert cfg.quantization == "q4"
        assert cfg.env_key == "GALAXY_LOCAL_OPENAI_URL"
        assert cfg.source_type == "local", "本地服务被当成远端，质量优先路径会绕开它"
        assert cfg.default_model == PERC_ID, "模型 id 该用服务自报的，不是猜的"


class TestTheReasoningLaneTellsTheTruthAboutItself:
    """这条泳道的每一栏都是**它自己的事实**，不是抄感知位那条。"""

    def test_it_registers_on_its_own_variable(self, reasoning, monkeypatch):
        addr, _ = reasoning
        monkeypatch.setenv("GALAXY_REASONING_OPENAI_URL", addr)
        r = R.MultiLLMRouter()
        assert "reasoning_openai" in r.providers
        assert "local_openai" not in r.providers

    def test_it_does_not_claim_to_see_or_hear(self, reasoning, monkeypatch):
        """两个推理位候选的 caps 里 vision/audio 都是 False —— 这里必须一致。"""
        addr, _ = reasoning
        monkeypatch.setenv("GALAXY_REASONING_OPENAI_URL", addr)
        cfg = R.MultiLLMRouter().providers["reasoning_openai"]
        assert not cfg.supports_vision and not cfg.supports_audio and not cfg.multimodal

        import core.model_catalog as mc

        for tag in ("qwen3.6:35b-a3b", "agents-a1:35b-a3b"):
            spec = mc.exact_model(tag)
            assert (
                spec.caps.vision is False and spec.caps.audio_in is False
            ), f"{tag} 的目录声明变了 —— 这条断言的前提没了"

    def test_it_is_a_discrete_gpu_not_the_igpu_tier(self, reasoning, monkeypatch):
        addr, _ = reasoning
        monkeypatch.setenv("GALAXY_REASONING_OPENAI_URL", addr)
        cfg = R.MultiLLMRouter().providers["reasoning_openai"]
        assert cfg.hardware_tier == "gpu_full"
        assert cfg.source_type == "local"
        assert cfg.supports_tools is True, "推理位不会调工具就没有意义"

    def test_it_does_not_invent_a_quantization(self, reasoning, monkeypatch):
        """FreeToken 发 FP8/NVFP4/BF16/FTW，**没有一个是 q4**。没声明就说没声明。"""
        addr, _ = reasoning
        monkeypatch.setenv("GALAXY_REASONING_OPENAI_URL", addr)
        assert R.MultiLLMRouter().providers["reasoning_openai"].quantization == "none"


class TestBothAtOnceIsTheRealShape:
    """C/D 档本来就是两块加速器、两台服务。"""

    def test_neither_lane_steals_the_others_address_or_model(self, perception, reasoning, monkeypatch):
        pa, _ = perception
        ra, _ = reasoning
        monkeypatch.setenv("GALAXY_LOCAL_OPENAI_URL", pa)
        monkeypatch.setenv("GALAXY_REASONING_OPENAI_URL", ra)
        r = R.MultiLLMRouter()
        assert {"local_openai", "reasoning_openai"} <= set(r.providers)
        assert r.providers["local_openai"].base_url != r.providers["reasoning_openai"].base_url
        assert r.providers["local_openai"].default_model == PERC_ID
        assert r.providers["reasoning_openai"].default_model == REAS_ID
        assert r.adapters["local_openai"] is not r.adapters["reasoning_openai"]

    def test_a_request_goes_to_the_lane_it_was_addressed_to(self, perception, reasoning, monkeypatch):
        """走真适配器发一次 —— 配置对不代表请求发对了地方。"""
        pa, phits = perception
        ra, rhits = reasoning
        monkeypatch.setenv("GALAXY_LOCAL_OPENAI_URL", pa)
        monkeypatch.setenv("GALAXY_REASONING_OPENAI_URL", ra)
        r = R.MultiLLMRouter()
        res = asyncio.run(r.adapters["reasoning_openai"].chat([{"role": "user", "content": "你好"}], model=REAS_ID))
        assert rhits["chat"] == 1, "推理位那台没收到请求"
        assert phits["chat"] == 0, "请求发到感知位那台去了"
        assert "好" in json.dumps(res, ensure_ascii=False, default=str)


class TestTheServesDeclarationIsPerLane:
    """两台服务伺候的是不同的位，共用一个声明就等于说"这两台装的是同一个型号"。"""

    def test_each_declaration_lands_on_its_own_lane(self, perception, reasoning, monkeypatch):
        pa, _ = perception
        ra, _ = reasoning
        monkeypatch.setenv("GALAXY_LOCAL_OPENAI_URL", pa)
        monkeypatch.setenv("GALAXY_REASONING_OPENAI_URL", ra)
        monkeypatch.setenv("GALAXY_LOCAL_OPENAI_SERVES", "openbmb/minicpm-o4.5")
        monkeypatch.setenv("GALAXY_REASONING_OPENAI_SERVES", "agents-a1:35b-a3b")
        r = R.MultiLLMRouter()
        assert r._provider_serving("openbmb/minicpm-o4.5") == ("local_openai", PERC_ID)
        assert r._provider_serving("agents-a1:35b-a3b") == ("reasoning_openai", REAS_ID)

    def test_declaring_one_lane_does_not_speak_for_the_other(self, perception, reasoning, monkeypatch):
        """此前写死 ``name == "local_openai"``，两条泳道会共用同一个声明。"""
        pa, _ = perception
        ra, _ = reasoning
        monkeypatch.setenv("GALAXY_LOCAL_OPENAI_URL", pa)
        monkeypatch.setenv("GALAXY_REASONING_OPENAI_URL", ra)
        monkeypatch.setenv("GALAXY_REASONING_OPENAI_SERVES", "agents-a1:35b-a3b")
        r = R.MultiLLMRouter()
        assert r._provider_serving("agents-a1:35b-a3b") == ("reasoning_openai", REAS_ID)

    def test_an_undeclared_tag_is_still_not_matched(self, perception, reasoning, monkeypatch):
        """乱认一个更糟：那一位会静默落到别的模型上，失去两位分工的意义。"""
        pa, _ = perception
        ra, _ = reasoning
        monkeypatch.setenv("GALAXY_LOCAL_OPENAI_URL", pa)
        monkeypatch.setenv("GALAXY_REASONING_OPENAI_URL", ra)
        assert R.MultiLLMRouter()._provider_serving("qwythos-9b-v2") is None


class TestALaneThatIsNotThereStaysQuiet:
    def test_no_address_means_no_provider(self):
        r = R.MultiLLMRouter()
        assert "local_openai" not in r.providers and "reasoning_openai" not in r.providers

    def test_an_address_nobody_listens_on_is_not_registered(self, monkeypatch):
        """注册一个没人监听的端点，偏好列表命中它时拿到的是连接失败。"""
        monkeypatch.setenv("GALAXY_REASONING_OPENAI_URL", "127.0.0.1:1")
        assert "reasoning_openai" not in R.MultiLLMRouter().providers


class TestTheLaneTableItself:
    def test_lanes_do_not_collide(self):
        names = [lane["provider"] for lane in R._LOCAL_OPENAI_LANES]
        prefixes = [lane["env_prefix"] for lane in R._LOCAL_OPENAI_LANES]
        assert len(set(names)) == len(names), f"两条泳道抢同一个 provider 名：{names}"
        assert len(set(prefixes)) == len(prefixes), f"两条泳道读同一组环境变量：{prefixes}"

    def test_every_lane_key_is_registered_in_the_config_schema(self):
        """没登记的配置键=面板上看不见、文档里查不到 —— 等于没有这个开关。"""
        from core.routes.config_schema_registry import CONFIG_SCHEMA

        for lane in R._LOCAL_OPENAI_LANES:
            for suffix in ("URL", "MODEL", "SERVES", "KEY"):
                key = f"{lane['env_prefix']}_{suffix}"
                assert key in CONFIG_SCHEMA, f"{key} 没在配置登记表里"
