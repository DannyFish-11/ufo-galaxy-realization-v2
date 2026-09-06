"""云端厂商与型号的**唯一权威**表。

## 为什么它自己一个文件

这张表原来长在 ``core/multi_llm_router.py`` 里。2026-09-04 一轮复核之后它涨到
四百多行 —— 涨的几乎全是**核实出处**:哪个型号什么时候发布、价格从哪查到的、
哪个已经退役、哪个查不到一手来源所以故意没登记。那些字不是注释噪音,是这张表
唯一的保鲜机制:没有它们,下一个人无从判断某条是"刚核过"还是"三年前写的"。

于是复杂度门红了。抬基线是把问题记下来当没发生;拆出来才是解决 —— 路由器
那个文件本来就该是"怎么选",不该同时是"有哪些"。

导入路径没变:``multi_llm_router`` 仍然 re-export ``PROVIDER_REGISTRY``,仓库里
二十来处 ``from core.multi_llm_router import PROVIDER_REGISTRY`` 一处都不用改。
新代码建议直接从这里导。

## 改这张表之前先读这几条

* **不准凭命名惯例猜型号串。** 猜出来的串会注册成功、选路成功,一直到真发请求
  才 404 —— 而那时用户看到的只是"模型没回话"。没有一手来源就不登记,并在原地
  写明为什么不登记(现成的例子:GPT-6 Astra)。
* **退役的要删,并把出处留在注释里。** 只删不写,下一个人会好心加回来。
  ``tests/test_model_ids_have_one_authority.py`` 盯着退役名单。
* **``default_model`` 必须在自己的 ``models`` 里。** 同一道门管这条。
* **``cost_in`` / ``cost_out`` 跟着 ``default_model`` 走**,单位是每 1K token 的
  美元。它驱动 cost_budget SLO:算贵了顶多提前降级,算便宜了会让真实花费超预算
  却不触发保护 —— 两种错法不对等,遇到分档定价一律往贵了登记。
* **别在别处再存一份型号表。** 这个仓库已经因为这件事栽过三次(见那道门的说明)。
"""

from typing import Any, Dict, List

PROVIDER_REGISTRY: List[Dict[str, Any]] = [
    {
        # 2026-09-04 联网复核(一手:developers.openai.com 的各型号文档页):
        #
        # · GPT-5.6 是**三个型号**,不是一个:gpt-5.6-sol(最强推理,$5/$30 每 M)、
        #   gpt-5.6-terra(均衡,$2.50/$15)、gpt-5.6-luna(高吞吐低价,$1/$6)。
        #   裸串 ``gpt-5.6`` 是官方文档写明的**别名,指向 Sol**。此前这里只写了
        #   裸串和 terra/luna,漏了 sol 本名 —— 别名能用,但路由要按型号选价时
        #   拿不到 sol 这个名字。现在三个本名都列上,default 仍用别名(见下)。
        # · cost_out 从 0.015 改成 0.030:默认落到 Sol,Sol 的输出是 $30/M 不是
        #   $15/M。这个数直接驱动 cost_budget SLO —— 算便宜了会让真实花费超预算
        #   却不触发降级保护,是两种错法里更坏的那种。
        # · gpt-5.3-codex 补进来:官方称"迄今最强的 agentic 编码模型",本仓的
        #   执行路径正是它的用武之地。
        #
        # **GPT-6 Astra 故意没有登记。** 它确实发布了(openai.com/index/gpt-6-astra),
        # 但截至复核时仍在 Trusted Access 限量放量,**公开模型目录与 API 文档里
        # 没有任何对应的请求 ID**,官方口径是"未经证实的 gpt-6 串应当视为占位符,
        # 不要写进生产配置"。凭命名惯例猜一个 ``gpt-6`` 填进来,就是这份 registry
        # 最不该犯的错:注册成功、选路成功,一直到真发请求才 404。等它进目录再加。
        #
        # default 用别名而不是 gpt-5.6-sol 本名:OpenAI 的裸串别名会跟着快照走,
        # 而本仓没有"型号退役自动迁移"的机制 —— 钉死本名的代价是某天静默 404,
        # 用别名的代价只是行为随上游微调。两害相权取后者。(Anthropic 那条相反,
        # 它家的无日期 ID 本身就是钉死的快照,见下面那条。)
        "name": "openai",
        "env_key": "OPENAI_API_KEY",
        "base_url": "https://api.openai.com/v1",
        "base_env": "OPENAI_API_BASE",
        "base_key": "openai_base",
        "models": [
            "gpt-5.6-sol",
            "gpt-5.6-terra",
            "gpt-5.6-luna",
            "gpt-5.6",
            "gpt-5.3-codex",
            "gpt-5.5",
            "gpt-4o",
        ],
        "default_model": "gpt-5.6",
        # 双工(语音实时)型号。与上面的文本型号分开列：两者走的是不同接口
        # (Realtime WebSocket vs Chat Completions),上游的下线节奏也不同 ——
        # 此前 voice_duplex_session 把型号写死在代码里、不在本 registry 中,
        # 于是 verify_provider_apis.py 的上游比对完全覆盖不到它,漂移无人发现。
        # 2026-09-04 复核:双工型号已经迭代了两代,这里原来只有初代 gpt-realtime。
        # gpt-realtime-2 加了"先想再说"(可配推理档)与更可靠的工具调用;
        # gpt-realtime-2.1 在其上改进字母数字识别、静音/噪声处理与打断行为 ——
        # 这三件正是本仓 lockstep(声字同步)最容易翻车的地方,所以默认取 2.1。
        # 2.1-mini 也在,列上供成本敏感场景选;初代保留作兜底。
        # 音频计价与文本不同轴(gpt-realtime-2:$32/M 音频输入、$64/M 音频输出),
        # 而 cost_in/cost_out 是 provider 级的**文本**单价,表示不了它 —— 不硬填,
        # 免得算出一个谁都对不上的预算。
        "realtime_models": ["gpt-realtime-2.1", "gpt-realtime-2.1-mini", "gpt-realtime-2", "gpt-realtime"],
        "default_realtime_model": "gpt-realtime-2.1",
        "cost_in": 0.005,
        "cost_out": 0.030,
        "extra": {"multimodal": True},
    },
    {
        # 2026-09-04 复核(一手:platform.claude.com 的 models/overview 对照表):
        #
        # · 补 claude-fable-5-1(2026-09-01 发布)—— 长时程 agentic 与硬推理那一档,
        #   1M 上下文 / 128K 输出 / $10 入 $50 出。此前这里没有它。
        # · cost_in/cost_out 从 0.003/0.015 改成 0.002/0.010:这两个数要跟着
        #   **default_model** 走,而默认是 claude-sonnet-5($2/M 入、$10/M 出)。
        #   旧值是更早一代 Sonnet 的价,一直没跟着改。
        #
        # 这里**钉死无日期 ID**,跟上面 openai 用别名的取舍正好相反:Anthropic 从
        # 4.6 代起,无日期 ID 本身就是一个固定快照,官方明说不会改动既有 ID 的权重
        # 与配置,要换版就发新 ID。所以钉死没有"悄悄换模型"的风险,反而拿到了可复现。
        #
        # 四档的取舍(免得下次有人按"越贵越好"改 default):
        #   fable-5-1  最强,2 倍 opus 价,给硬推理/长时程
        #   opus-5     复杂 agentic 编码
        #   sonnet-5   速度与智力的平衡 ← 默认
        #   haiku-4-5  最快,近前沿(200K 上下文,注意比上面三个小 5 倍)
        "name": "anthropic",
        "env_key": "ANTHROPIC_API_KEY",
        "protocol": "anthropic",
        "base_url": "https://api.anthropic.com/v1",
        "models": ["claude-fable-5-1", "claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5-20251001"],
        "default_model": "claude-sonnet-5",
        "cost_in": 0.002,
        "cost_out": 0.010,
        "extra": {"multimodal": True},
    },
    {
        "name": "google",
        "env_key": "GOOGLE_API_KEY",
        "alt_env": ["GEMINI_API_KEY"],
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        # 2026-09-04 复核(一手:ai.google.dev/gemini-api/docs/models 各型号页):
        # 这一条落后得最多 —— 停在 3.5,而 Gemini 3 系列已经走到 3.8。补三代:
        #   gemini-3.8-flash  2026-09-02 GA,最强 Flash,1M 上下文 / 64K 输出,
        #                     思考档可调(low/medium/high)
        #   gemini-3.7-flash  2026-08-13
        #   gemini-3.6-flash  token 效率与编码/agent 规划改进,比 3.5 更便宜
        #   gemini-3.5-flash-lite  低延迟高吞吐的子 agent 档
        #
        # **没有登记 gemini-3.x-pro。** 3 系列这几代放出来的都是 Flash 线,没查到
        # 任何一手来源确认存在 3.6/3.7/3.8 的 pro 型号 —— 按命名惯例顺手补一个
        # ``gemini-3.8-pro``,就是在造一个会 404 的串。旧的 3.5-pro / 2.5-pro 保留
        # 在尾部:它们是当时核实过的,没有证据说已退役,不因为"看着旧"就删。
        #
        # cost_in/cost_out 跟着 default(3.8-flash)改成 $0.75/M 入、$3.75/M 出。
        # 注意这是**introductory 价,2026-12-31 止**,2027-01-01 起转标准价 ——
        # 标准价官方还没公布,到期这两个数会偏低,届时要复核。
        "models": [
            "gemini-3.8-flash",
            "gemini-3.7-flash",
            "gemini-3.6-flash",
            "gemini-3.5-flash-lite",
            "gemini-3.5-flash",
            "gemini-3.5-pro",
            "gemini-2.5-pro",
        ],
        "default_model": "gemini-3.8-flash",
        # Live API(BidiGenerateContent)的原生音频型号,同样与文本型号分开维护。
        # 2026-09-04 换成 gemini-3.1-flash-live-preview:官方描述为低延迟
        # audio-to-audio、面向实时对话与语音优先应用,带声学细节侦测与数值精度 ——
        # 比原来钉的 2.5-flash-native-audio-preview-12-2025 新一代。旧串保留兜底。
        "realtime_models": ["gemini-3.1-flash-live-preview", "gemini-2.5-flash-native-audio-preview-12-2025"],
        "default_realtime_model": "gemini-3.1-flash-live-preview",
        # Live API 的 WebSocket 接口版本。官方文档现给 v1beta;v1alpha 仅用于
        # affective dialog / proactive audio 等尚未升级的特性。做成字段而非写死,
        # 是因为这个版本号历史上换过,写死在 URL 里会再次悄悄过期。
        "realtime_api_version": "v1beta",
        "cost_in": 0.00075,
        "cost_out": 0.00375,
        "extra": {"multimodal": True},
    },
    {
        # Grok 4.6 —— 联网核实,2026-08-12 发布,xAI 官方 API / OpenRouter / Cursor /
        # Vercel / Cloudflare 同步上线(2026-08-19 又上了 Amazon Bedrock,分发渠道
        # 增加,不影响这条走的是官方直连),base_url/协议与 4.5 一致(同一
        # provider,只是新模型 id),不是猜的命名惯例延伸。
        #
        # cost_in/cost_out(2026-08-20 复核补全):定价按 prompt 长度分两档,不是
        # 单一价——200K token 以下 $2/$6(每 1M,输入/输出;缓存输入更低,
        # $0.5/M),超过 200K 翻倍到 $4/$12。Grok 4.6 本身有 500K 上下文,真实
        # 请求越过 200K 那条线是会发生的情形,不是理论上的边界。跟上面 deepseek
        # 那条同样的理由:cost_budget 判的是"会不会超预算",单一静态字段没法表示
        # 分档定价,算贵了顶多提前降级、算便宜了才会让真实花费超预算却没触发
        # 保护——两种错法不对等,故意按**高档(超 200K)**登记。
        "name": "xai",
        "env_key": "XAI_API_KEY",
        "base_url": "https://api.x.ai/v1",
        "models": ["grok-4.6", "grok-4.5", "grok-4.3"],
        "default_model": "grok-4.6",
        "cost_in": 0.004,
        "cost_out": 0.012,
        "extra": {"multimodal": True},
    },
    {
        # Meta Llama API(联网核实 llama.developer.meta.com 官方文档):OpenAI 兼容 base
        # 是 api.llama.com/compat/v1,不是 api.meta.ai;"muse-spark" 并非真实模型,
        # 改用官方 Llama-4 模型名。注意:Meta 已于 2026-07-06 起【收尾 Llama API 公测】
        # (仅美区 waitlist),该 provider 实际多半不可用——保留正确配置,能用则用,
        # 不能用则由 verify_provider 如实报错、路由自动跳过。
        "name": "meta",
        "env_key": "META_API_KEY",
        "base_url": "https://api.llama.com/compat/v1",
        "models": ["Llama-4-Maverick-17B-128E-Instruct-FP8", "Llama-4-Scout-17B-16E-Instruct-FP8"],
        "default_model": "Llama-4-Maverick-17B-128E-Instruct-FP8",
        "cost_in": 0.00125,
        "cost_out": 0.00425,
        "extra": {"multimodal": True, "supports_vision": True, "max_tokens": 8192},
    },
    {
        # Agnes AI:全模态免费 API(2026),OpenAI 兼容协议。
        # agnes-2.5-flash 2026-07-13 发布(agentic/编码强化,免费不限量);
        # 2.0 仍可用作兜底(256K 上下文/64K 输出,免费档 20 RPM)。
        # 2.5 的准确串遵循官方命名规约(1.5→2.0→2.5),若有出入由 L4
        # 模型名单自动同步(/models 对账)+ 面板 verify_provider 试调纠正。
        # 图像(agnes-image-2.x)/视频(agnes-video-v2.0)模型不入聊天路由,
        # 属扩展层能力,按需另接。
        "name": "agnes",
        "env_key": "AGNES_API_KEY",
        "base_url": "https://apihub.agnes-ai.com/v1",
        "models": ["agnes-2.5-flash", "agnes-2.0-flash"],
        "default_model": "agnes-2.5-flash",
        "cost_in": 0.0,
        "cost_out": 0.0,
        "extra": {"multimodal": True, "supports_vision": True, "supports_tools": True},
    },
    {
        "name": "mistral",
        "env_key": "MISTRAL_API_KEY",
        "base_url": "https://api.mistral.ai/v1",
        "models": ["mistral-large-3", "mistral-medium-3", "mistral-large-2"],
        "default_model": "mistral-large-3",
        "cost_in": 0.002,
        "cost_out": 0.006,
        "extra": {"multimodal": True},
    },
    {
        # deepseek-v4-pro 型号 id 本身仍正确。cost_in/cost_out 这次真的更新了——
        # 2026-08-20 联网复核:上一版(2026-08-15)判"只有聚合站信号、没有一手
        # 确认,不动"是对的,这次不一样,是**真事**:DeepSeek 2026-08-16 16:00 UTC
        # 生效一轮分时段涨价,TechTimes / Yahoo Finance / Fortune / Engadget /
        # Quartz / InfoWorld / Forbes 等八家独立信源交叉确认同一组数字(不是
        # 单一聚合站估算)——
        #
        #   输出(缓存未命中):  $0.87/M flat  → 非高峰 $1.98/M · 高峰 $3.96/M
        #   输入(缓存未命中):  $0.435/M flat → 非高峰 $0.66/M · 高峰 $1.32/M
        #   缓存命中另有约 98% 折扣(未拿到缓存命中的确切数字,不编)
        #
        # cost_in/cost_out 是驱动 cost_budget SLO 判断的**单一静态值**,没法表示
        # 分时段定价;这里按**高峰价**(更贵的那档)登记——SLO 判断的是"会不会
        # 超预算触发降级",算贵了顶多提前降级,算便宜了才会让真实花费超预算却
        # 没触发保护,两种错法不对等,故意往贵了算。要拿分时段各档的精确数字,
        # 配好 DEEPSEEK_API_KEY 跑 verify_provider_apis.py --only deepseek。
        "name": "deepseek",
        "env_key": "DEEPSEEK_API_KEY",
        "base_url": "https://api.deepseek.com/v1",
        # 2026-09-04:删掉 deepseek-chat / deepseek-reasoner。这不是"清理旧条目",
        # 是**它们已经不存在了** —— 官方公告(api-docs.deepseek.com/updates)写明
        # 两者于 2026-07-24 15:59 UTC 完全退役、不再可访问。留着的后果不是多余,
        # 是路由器可能选中一个必然失败的型号,而失败发生在真发请求那一刻。
        "models": ["deepseek-v4-pro", "deepseek-v4-flash"],
        "default_model": "deepseek-v4-pro",
        "cost_in": 0.00132,
        "cost_out": 0.00396,
    },
    {
        "name": "qwen",
        "env_key": "QWEN_API_KEY",
        "alt_env": ["DASHSCOPE_API_KEY"],
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "models": ["qwen3.8-max", "qwen3.8-coder", "qwen-flash", "qwen3.7-max", "qwen3.7-coder", "qwen3-235b-a22b"],
        "default_model": "qwen3.8-max",
        "cost_in": 0.0025,
        "cost_out": 0.0075,
        "extra": {"multimodal": True},
    },
    {
        # 2026-08-27 三次联网核实 —— **上一轮(2026-08-15)的结论已经过期了**,
        # 先把它原样记下来,免得后来人以为这里一直是这么写的:
        #
        #   那次查到的是"GLM-5.3 确实能调,但服务它的是编码套餐专属端点
        #   /api/coding/paas/v4,通用端点的定价表还只到 glm-5.2",据此把 glm-5.3
        #   挡在这条之外,另开了下面的 zhipu_coding。当时那个判断是对的。
        #
        # 之后发生了两件事:
        #   · 2026-08-19  GLM-5.3 通用 API 上线,就在这条一直在用的
        #     ``open.bigmodel.cn/api/paas/v4`` 上,按 token 计价(官方口径:与
        #     GLM-5.2 同价)。
        #   · 2026-08-26  GLM-5.3-Flash 上线,并以 MIT 开源(zai-org/GLM-5.3-Flash,
        #     safetensors)。GLM-5 系列首个原生多模态:320B 总参 / 18B 激活,
        #     1M 上下文,文/图/视频,同样在通用端点上。
        #
        # 所以"把 glm-5.3 挡在这条外面"的前提没有了。继续挡,就变成按一条已经不
        # 成立的旧结论把型号关在门外 —— 那和当初要防的 404 是同一类错误(判据与
        # 事实对不上),只是方向反过来:上次是会打到错的端点,这次是明明能调却调不到。
        #
        # zhipu_coding **不废**:订阅制计费 + 专属 base_url 这两点没变,它仍然是
        # 另一件事,见下面那条自己的注释。
        #
        # 核实来源(留着是为了下次复查有起点,不是为了好看):
        #   https://docs.bigmodel.cn/cn/guide/models/vlm/glm-5.3-flash
        #   https://docs.bigmodel.cn/cn/guide/models/text/glm-5.3
        #
        # 有一处**故意没有跟着改**:cost_in/cost_out 是 provider 级的单一数字,而
        # glm-5.3 与 glm-5.3-flash 差了大约一个数量级(flash 约为 5.3 的 1/10)。
        # 这份 registry 没有"按型号计价"的字段,硬填一个折中值等于臆造一个谁都对
        # 不上的数。保持原值不动,并在这里写明:它现在只对重档那一档近似成立,
        # 选到 flash 时真实成本比这个数低得多。
        #
        # 迁移注意(现在不用改,但别踩):GLM-5.3 系列强制思考,不再接受
        # ``thinking.type=disabled``,传了请求直接失败。本仓的 OpenAI 兼容适配器
        # 从不发这个字段(只发 model/messages/temperature/max_tokens/tools/
        # response_format),走的是默认的 enabled,所以这次不需要动适配器 ——
        # 这一段是写给以后想加"关掉思考"开关的人看的。
        "name": "zhipu",
        "env_key": "ZHIPU_API_KEY",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        # 海外访问用 Z.ai 的同构端点 ``https://api.z.ai/api/paas/v4``:型号名、
        # OpenAI 兼容协议、Bearer 鉴权全都一样,**只有域名不同**。所以不另开一条
        # provider(那会多出一份要同步的型号表),而是沿用 openai 那条先例,用
        # base_env/base_key 覆盖 base_url。覆盖之后 core.endpoint_admission 会把
        # 这家判成 ``overridden`` 并写进诊断面 —— 这正是要的效果:换地址这件事
        # 必须留痕,不能悄悄发生。
        "base_env": "ZHIPU_API_BASE",
        "base_key": "zhipu_base",
        # 出站白名单要认得这个主机,否则"按上面注释把地址指到官方海外端点"这件事
        # 在 enforce 档下会被自己的闸打死。注意它**不**让 endpoint_admission 把
        # 覆盖判成 canonical —— 换地址就是换了,那件事必须照样留痕。
        "alt_base_urls": ["https://api.z.ai/api/paas/v4"],
        "models": ["glm-5.3", "glm-5.3-flash", "glm-5.2", "glm-5.1", "glm-5.1-flash", "glm-4-plus"],
        "default_model": "glm-5.3",
        "cost_in": 0.001,
        "cost_out": 0.001,
        "extra": {"multimodal": True},
    },
    {
        # GLM 编码套餐(GLM Coding Plan,2026-08-15 联网核实)——**独立条目**,
        # 不是给上面 zhipu 顺手加个型号那么简单,三处结构性差异决定了它必须分开:
        #
        # 1. base_url 不同:编码套餐专属端点 /api/coding/paas/v4,不是通用端点
        #    /api/paas/v4。同一个 API Key 打错端点一样 404——这正是把它错放进
        #    zhipu.models 会踩的坑。
        # 2. 计费方式不同:这不是这份 registry 里其它条目那种按 token 计价——它是
        #    订阅制月费(Lite $18 / Pro $80 / Max $168,年付打七折左右,按官方站点
        #    截至复查时的定价页)。cost_in/cost_out 折算不出有意义的"每千 token"
        #    数字,所以下面两个值不是真定价,是**故意设高的哨兵**(远高于本 registry
        #    任何真实按 token 计价的条目)——ProviderConfig 的字段类型是 float,
        #    传 None 会在 _cost_ordered_ladder() 的 sort/求和里直接 TypeError
        #    (写这条时先踩了一遍这个坑,再改掉的)。哨兵值确保:就算它意外进了某个
        #    按成本排序的候选池,也绝不会因为"看起来最便宜"被排到前面。
        # 3. 使用范围不同:官方文档把它限定在"编码 agent 工作流"(仓库问答/代码
        #    生成/调试/修复/自动化开发),不是通用聊天端点。
        #
        # env_key 是独立的 ZHIPU_CODING_API_KEY,不沿用 ZHIPU_API_KEY——原因不是
        # 两把 key 在官方那边不能共用(官方文档说编码套餐同样用 BigModel 控制台
        # 生成的 key),而是本仓的 provider 注册逻辑(_register_from_registry)按
        # env_key 是否有值决定要不要激活这个 provider,并把它自动放进
        # _cost_ordered_ladder() 那样按成本排序的候选池——**不看这个 provider 是否
        # 出现在 PROVIDER_MODEL_MAP 或 config/llm_routing_policy.yaml 的任务路由
        # 优先级里**(第一版以为不接那两处就够,核对注册/候选池代码才发现不够,
        # 已改)。如果沿用 ZHIPU_API_KEY,任何配了普通 zhipu 聊天 key 的人都会被
        # 静默激活这个 provider——多数人没有编码套餐订阅,会白打一堆 403/404;
        # 少数真有订阅的人,也可能在没打算用编码配额的场景里被自动选中而悄悄烧掉
        # 配额。独立 env 名把"要不要接编码套餐"变成一次显式动作:同一串 key 值
        # 大可以填两遍,但填不填 ZHIPU_CODING_API_KEY 这件事必须是用户自己决定的。
        #
        # 残留限制(如实记录,没有假装解决了):真设了 ZHIPU_CODING_API_KEY 之后,
        # _cost_ordered_ladder() 仍然会把它当成任意任务类型的候选之一——那个方法
        # 按"已注册+有 key"筛选候选池,不看 provider 是不是该任务类型"该用的那家"。
        # 999.0 的哨兵价保证它排到候选梯队最后一档、绝不会被优先选中(已用
        # deepseek 同时配置的场景验证:候选梯队按成本升序是
        # [deepseek, zhipu_coding],不是反过来)——但极端情况下(所有真实
        # provider 都不可用,只有 zhipu_coding 配了 key)它仍可能被当成兜底调用去
        # 处理一次编码套餐 ToS 没打算覆盖的任务类型。把它限定到"只接编码类任务"
        # 需要改 _cost_ordered_ladder 本身按任务类型过滤候选池,那是比这次范围大
        # 得多的改动,没有一并做。
        "name": "zhipu_coding",
        "env_key": "ZHIPU_CODING_API_KEY",
        "base_url": "https://open.bigmodel.cn/api/coding/paas/v4",
        # 套餐里能用的型号跟着官方走:glm-5.3 与 glm-5.3-flash 都在。
        # 注意这两个型号**同时**出现在上面的 zhipu 条目里 —— 那不是重复登记,
        # 是同一款模型的两条售卖路径(按 token 计价的通用端点 / 订阅制的编码端点),
        # base_url 与计费方式都不同,谁也替代不了谁。
        "models": ["glm-5.3", "glm-5.3-flash"],
        "default_model": "glm-5.3",
        "cost_in": 999.0,
        "cost_out": 999.0,
        "extra": {
            "multimodal": True
        },  # billing=订阅制/scope=编码 agent 限定,见上面注释；ProviderConfig 没有对应字段,不能塞进 extra
    },
    {
        # 官方 OpenAI 兼容端点(联网核实 platform.minimax.io 官方文档):base 是
        # api.minimax.io/v1,不是旧的 api.minimax.chat(已非官方端点)。当前主力
        # MiniMax-M3(1M 上下文·agentic),M2.7/M2.5 仍在。模型名大小写按官方。
        "name": "minimax",
        "env_key": "MINIMAX_API_KEY",
        "base_url": "https://api.minimax.io/v1",
        "models": ["MiniMax-M3", "MiniMax-M2.7", "MiniMax-M2.5"],
        "default_model": "MiniMax-M3",
        "cost_in": 0.001,
        "cost_out": 0.004,
        "extra": {"multimodal": True},
    },
    {
        "name": "step",
        "env_key": "STEP_API_KEY",
        "base_url": "https://api.stepfun.com/v1",
        "models": ["step-3.7-flash", "step-3.7-turbo", "step-3.7-mini"],
        "default_model": "step-3.7-flash",
        "cost_in": 0.001,
        "cost_out": 0.004,
        "extra": {"multimodal": True},
    },
    {
        "name": "mimo",
        "env_key": "MIMO_API_KEY",
        "base_url": "https://api.xiaomimimo.com/v1",
        "models": ["mimo-v2.5-pro", "mimo-v2.5-standard", "mimo-v2.5-lite"],
        "default_model": "mimo-v2.5-pro",
        "cost_in": 0.00002,
        "cost_out": 0.00008,
    },
    {
        "name": "moonshot",
        "env_key": "MOONSHOT_API_KEY",
        "base_url": "https://api.moonshot.cn/v1",
        "models": ["kimi-k3", "kimi-k2.6", "kimi-k2.5", "moonshot-v1-128k"],
        "default_model": "kimi-k3",
        "cost_in": 0.002,
        "cost_out": 0.002,
    },
    {
        "name": "perplexity",
        "env_key": "PERPLEXITY_API_KEY",
        # SONAR_API_KEY 是面板公开的别名,"已配置"角标本就认它;缺了这行会导致
        # 面板亮绿标而路由器不读 → 密钥静默失效(见 tests/test_panel_api_key_routing.py)
        "alt_env": ["SONAR_API_KEY"],
        "base_url": "https://api.perplexity.ai",
        "models": ["sonar-pro", "sonar-deep-research", "sonar-reasoning-pro", "sonar"],
        "default_model": "sonar-pro",
        "cost_in": 0.001,
        "cost_out": 0.001,
        "extra": {"supports_tools": False},
    },
    {
        "name": "groq",
        "env_key": "GROQ_API_KEY",
        "base_url": "https://api.groq.com/openai/v1",
        "models": ["llama-3.3-70b-versatile"],
        "default_model": "llama-3.3-70b-versatile",
        "cost_in": 0.00059,
        "cost_out": 0.00079,
        "extra": {"supports_tools": True},
    },
    {
        # OpenRouter:OpenAI 兼容的聚合器,"openrouter/auto" 让其自选底层模型。
        # cost 0 为占位——真实成本随所选底层模型浮动,由计费层回填。
        "name": "openrouter",
        "env_key": "OPENROUTER_API_KEY",
        "base_url": "https://openrouter.ai/api/v1",
        "models": ["openrouter/auto"],
        "default_model": "openrouter/auto",
        "cost_in": 0.0,
        "cost_out": 0.0,
        # extra 会被 **unpack 进 ProviderConfig,只能用其合法字段;聚合器语义用
        # source_type="api" 即可(无 aggregator 字段,误用会让整个路由器构造崩溃)。
        "extra": {"supports_tools": True},
    },
]
