# memory-agent — 多模态记忆 Agent 系统

按 BUILD_SPEC 集成四个开源组件为一个可运行、可验收的系统:

| 层 | 组件 | 形态 |
|---|---|---|
| L0 推理 | Gemma 4 via vLLM | OpenAI 兼容端点 `:8000` |
| L1 表示 | jina-embeddings-v5-omni | FastAPI 嵌入服务 `:8001`(另带 OpenAI 兼容网关) |
| L2 记忆 | Omni-SimpleMem / Qdrant 兜底 | `adapters/memory.py` 双后端 |
| L3 组合 | 本项目 Memory-Agent | FastAPI `:8002` + MCP server |
| L4 治理 | Omnigent 0.4.0 | `omnigent/memory-agent` bundle |

## 快速开始(目标机器)

```bash
# 0. 硬件定档(停点:档位须人类确认后写入)
python scripts/detect_hardware.py            # 打印检测报告与建议档位
python scripts/detect_hardware.py --write B  # 人类确认后写入 config.yaml

# 1. 依赖与模型
make install                                  # uv sync(Python 3.12)
uv sync --extra local-embed                   # L1 本地推理依赖(torch 等,较重)
uv run python scripts/download_models.py      # 按档位预下载 L0/L1 模型

# 2. 起服务
make up                                       # qdrant
VLLM_MODEL=$(档位对应模型) make up-gpu          # + vLLM(GPU 机器)
make run-embed &                              # L1 :8001
make run-api &                                # L3 :8002

# 3. 验收
make verify                                   # M1-M4 全部验收 + 多模态端到端场景
```

无 GPU 的开发机上 `make test` 仍可运行全部离线逻辑用例;规格验收
(integration)用例在对应服务不可达时显式 SKIP 并注明原因,不会静默通过。

## 架构与接口契约

核心逻辑(`core/`、`services/`)只依赖三个协议(BUILD_SPEC §3):
`LLMClient`(adapters/llm.py)、`Embedder`(adapters/embedder.py)、
`MemoryStore`(adapters/memory.py)。对上游的一切知识收敛在 `adapters/`。
**评审红线:替换任何上游只允许改动 `adapters/`。**

### SimpleMem 集成方式(读源码所得)

上游 OmniSimpleMem 的 LLM 与文本嵌入共用一个 OpenAI 兼容 `api_base_url`
(`omni_memory/utils/embedding.py:_get_openai_client`)。本项目在 L1 服务上提供
网关路由——`/v1/chat/completions` 反代 L0 vLLM、`/v1/embeddings` 由 L1 jina
本地响应——SimpleMem 把 base_url 指到 `:8001/v1` 即同时命中两层,零上游改动。

## 上游版本锁定

| 上游 | 版本/commit | 说明 |
|---|---|---|
| aiming-lab/SimpleMem | `60a48e83a7fef10d386e1f438589047d3a4257bc` (2026-06-23) | OmniSimpleMem 子包 |
| omnigent (PyPI) | `0.4.0` | bundle schema 以此版本源码为准 |
| qdrant | `v1.12.4`(docker image) | |
| Python 依赖 | 见 `uv.lock` | 精确锁定 |

克隆上游到 `.upstream/SimpleMem` 并 `git checkout 60a48e83` 后
`pip install -e .upstream/SimpleMem/OmniSimpleMem` 即可启用 simplemem 后端。

## ⚠️ 上游 patch 记录(BUILD_SPEC 停点,待人类确认)

**OmniSimpleMem 在上述 pinned commit 缺失 `omni_memory/core/config.py`**:
全包 30+ 处 `from omni_memory.core.config import ...`(含 `omni_memory/__init__.py:13`),
该文件却未随仓库提交 —— 包在上游原样状态下无法 import。

处置:`adapters/simplemem_compat/config_shim.py` 依据上游自带的规范测试
`OmniSimpleMem/tests/test_config.py` 与全包字段引用逐字段重建该模块,并在
import 上游前注册到 `sys.modules["omni_memory.core.config"]`。**未修改上游任何
文件**;默认 `memory.backend=qdrant`(规格允许的兜底)不受影响。是否采纳
simplemem 后端、是否向上游提修复 PR,由人类决策。

## 与 BUILD_SPEC 的偏差(显式列出)

1. **Omnigent agent 定义为 bundle 目录而非单文件** —— 规格 §1 写
   `omnigent/memory-agent.yaml`,但 omnigent 0.4.0 实际 schema 是
   `<bundle>/config.yaml` + `<bundle>/tools/mcp/*.yaml`(spec_version: 1 判别,
   见其 cli.py bundle 解析)。按规格"以实际源码为准"原则采用 bundle 布局:
   `omnigent/memory-agent/`。
2. **本构建环境无 GPU**(容器:无 NVIDIA 驱动,15GB RAM,4 核)——
   低于规格 §0.3 任何档位。M1/M2 及依赖真实模型的规格验收用例已完整编写,
   但只能在目标硬件上执行;本环境实际跑通的是全部离线逻辑用例
   (fake 嵌入后端为 config 显式选择,非静默降级)。`hardware.tier` 保持
   `unset`,等待人类在目标机器上定档。
3. **成本策略的确切回调签名待目标机器验证** —— omnigent 0.4.0 的 guardrails
   为 function policy 机制(无内置 max_cost_usd 字段),本项目自带
   `omnigent/omnigent_policies/cost_limit.py`;Omnigent 属 alpha,若签名不符按
   规格三选一流程上报。
4. **音频跨模态验收未列入 make verify** —— 规格 M2/M3 验收原文仅要求文本+图像;
   fixtures 已含测试音频(`tone_440hz.wav`),`/embed` 接口与入库链路支持 audio,
   语义级音频检索验收留待目标机器。

## 里程碑状态

- **M1 L0 推理端点**:代码/编排/验收用例完成;`make verify-m1` 需目标 GPU 机器。
- **M2 L1 嵌入服务**:服务完成(`/embed`、OpenAI 兼容层、fail-fast 探针);
  `make verify-m2` 语义断言需真实模型。
- **M3 记忆核心**:双后端 MemoryStore、MemoryAgent、FastAPI+MCP 完成;
  验收 ①②③④⑤ 的离线链路版本全绿,live 版本待目标机器。
- **M4 Omnigent**:bundle 完成(以 0.4.0 实际 schema);结构用例全绿;
  会话级验收(记忆经 MCP 生效、成本确认)需目标机器人工执行。

## MCP server

```bash
make run-mcp   # stdio;工具:memory_store / memory_search / memory_consolidate
```

FastAPI 与 MCP 同进程时经 `core.factory.get_shared_memory_store` 复用同一
MemoryStore 实例;跨进程时经同一 Qdrant collection 共享持久状态。
