---
# Galaxy Panel — Design Tokens (design.md format)
# 机器可读 token；下方 Markdown 是理由与组件规范。引用语法:{path.to.token}
meta:
  name: Galaxy Control Panel
  version: 2.0.0
  mode: dark-only            # 桌面 AI 覆盖层之上的"镜头",恒为深色
  accent_strategy: single    # 单一暖金强调色,与覆盖层三态辉光同源
  material: liquid-glass      # 克制版液态玻璃(小米 HyperOS 3 / OPPO ColorOS 16 取向)
  layout: three-column        # 图标栏 | 对话 | 在场栏

color:
  # 画布与表面(近黑、微暖中性;层级靠明度,不靠重边框)
  canvas:        "#0C0D11"
  surface:       "#14151B"   # 实底内容(气泡/列表)用,保可读
  surface_raised:"#1C1E26"
  scrim:         "rgba(0,0,0,0.55)"
  border_subtle: "rgba(255,255,255,0.07)"
  border_strong: "rgba(255,255,255,0.14)"
  # 文字(高对比中性;WCAG AA: primary on canvas ≈ 15:1)
  text_primary:  "#ECEFF4"
  text_secondary:"#A9B1BE"
  text_muted:    "#717885"
  # 单一强调:香槟暖金(= 覆盖层"暖金边缘辉光")
  accent:        "#E6C07B"
  accent_hover:  "#F0CF95"
  accent_press:  "#C9A45E"
  accent_dim:    "#8C7A4E"
  on_accent:     "#1A1407"   # 暖金底上用的深色文字
  # 三态(与覆盖层 silent→liminal→manifest 一一对应,同一套暖金递进)
  phase_silent:  "#8C7A4E"   # 待机:暗金、呼吸
  phase_liminal: "#E6C07B"   # 思考:活跃金、脉动
  phase_manifest:"#F6DCA6"   # 表达:满亮金
  # 语义(全部偏柔和、不刺眼,保持静谧)
  success:       "#74B79A"
  warning:       "#E0B24E"
  danger:        "#D47A7A"
  info:          "#7C97D6"

# 液态玻璃材质(克制版)。只用于"漂浮的导航/外壳层",绝不铺到内容上。
material:
  # 玻璃面:半透明 + 背景模糊 + 轻微增饱和(玻璃透出底层的暖意)
  glass_bg:        "rgba(22,24,32,0.62)"          # 导航/外壳面板底
  glass_bg_strong: "rgba(18,20,27,0.78)"          # 弹层/抽屉(更实,保层级)
  glass_blur:      "20px"                          # backdrop-filter 模糊半径(克制,不过曝)
  glass_saturate:  "1.4"                           # backdrop-filter 饱和(玻璃质感来源)
  glass_border:    "rgba(255,255,255,0.10)"        # 玻璃边缘细高光
  glass_highlight: "inset 0 1px 0 rgba(255,255,255,0.08)"  # 顶缘 1px 高光(玻璃厚度感)
  glass_specular:  "rgba(230,192,123,0.06)"        # 极淡暖金高光叠加(同源,不抢戏)

typography:
  font_sans: "'Inter','SF Pro Display','Segoe UI Variable Text','Segoe UI',system-ui,-apple-system,'PingFang SC','Microsoft YaHei','Noto Sans SC',sans-serif"
  font_mono: "'SF Mono','JetBrains Mono','Cascadia Code',ui-monospace,Consolas,monospace"
  display:   { size: "26px", weight: 300, line: "1.2",  track: "0.01em" }   # Galaxy 标题
  title:     { size: "17px", weight: 500, line: "1.3" }
  section:   { size: "11px", weight: 600, line: "1.4",  track: "0.12em", transform: "uppercase" }  # 分区小标题
  body:      { size: "15px", weight: 400, line: "1.6" }   # 对话正文
  label:     { size: "12px", weight: 500, line: "1.4" }
  caption:   { size: "11px", weight: 400, line: "1.4" }
  mono:      { size: "12px", weight: 400, line: "1.5" }   # 模型名/token/代码

space:   { xs: "4px", sm: "8px", md: "12px", lg: "16px", xl: "24px", xxl: "32px", xxxl: "48px" }
radius:  { sm: "8px", md: "12px", lg: "16px", xl: "20px", pill: "999px" }

elevation:
  e0: "none"
  e1: "0 1px 2px rgba(0,0,0,0.40)"                         # 卡片/气泡 + border_subtle
  e2: "0 16px 48px rgba(0,0,0,0.55)"                       # 弹层/抽屉 + border_strong
  glass_e: "0 8px 32px rgba(0,0,0,0.45)"                   # 玻璃面的浮起投影
  glow_accent: "0 0 24px rgba(230,192,123,0.35)"           # 强调辉光(用于在场指示,克制)

motion:
  fast: "150ms"
  base: "250ms"
  slow: "400ms"
  easing: "cubic-bezier(0.2, 0, 0, 1)"                     # easeOut;进场用
  principle: "motion = 表达状态(三态/流式/到达),不做装饰;除 liminal 思考脉动外无常驻循环"

layout:
  rail_width: "64px"           # 左侧图标栏(窄,玻璃)
  presence_width: "300px"      # 右侧在场/对照栏(玻璃)
  chat_max_width: "760px"      # 中间对话列最大宽,过宽不利阅读
  gap: "{space.lg}"
  drawer_width: "min(440px, 80vw)"   # 诊断抽屉(深度遥测降级进此)
---

# Galaxy Control Panel — DESIGN.md

## Overview

控制面板是桌面 AI(三态覆盖层)的**镜头**:看进同一个"在场"。采用**三栏布局**——
**左 = 图标栏(切换标签),中 = 当前标签内容(第一个标签即上下文对话),右 = 在场/对照栏**。
对话进行时,右栏用三态/在场强度/它正在看什么听什么做**实时对照**——这正是"对话 ✕ 实时生成"
并置的初衷。深度系统遥测(NATS 原始流/拓扑等)降级进**诊断抽屉**,默认隐藏。

设计基调三个词:**静谧、聚焦、同源**;材质语言:**克制的液态玻璃**。
- **静谧**:深色近黑画布、柔和语义色、克制动效——不吵、不怪。
- **聚焦**:同一时刻只有一个焦点(当前标签);信息靠层级与留白分层,不靠堆部件。
- **同源**:面板暖金强调色 = 覆盖层"暖金边缘辉光",三态色一一对应,让桌面 AI 是"一个东西"。

材质参考:**小米 HyperOS 3 / OPPO ColorOS 16** 的克制液态玻璃(磨砂 + 轻反光,优先可读),
**不学**苹果早期 Liquid Glass 那种过曝强折射(其因可读性翻车后已回调)。

## Materials — 液态玻璃(克制版)

**唯一铁律(踩坑教训):玻璃只用在"漂浮的导航/外壳层",绝不铺到内容上。**
- **用玻璃**:左图标栏、右在场栏、顶部在场带、悬浮的发送按钮、弹层/抽屉、状态药丸。
  做法 = `background:{material.glass_bg}` + `backdrop-filter: blur({material.glass_blur})
  saturate({material.glass_saturate})` + `{material.glass_border}` 细边 + `{material.glass_highlight}`
  顶缘高光 + `{material.glow_accent}`/`{material.glass_specular}` 极淡暖金高光。
- **用实底**:对话气泡、正文、列表行、代码块——一律 `{color.surface}`/`{color.surface_raised}`
  不透明,**保证逐字可读**。聊天是要读的,玻璃会糊字。
- 模糊半径克制(20px 量级),不追求强反光;`saturate` 提供"玻璃透出暖意"的质感,而非炫光。
- 性能与降级:`@supports not (backdrop-filter: blur())` 时回退到 `{material.glass_bg_strong}`
  实色,观感降级但不破版(无独显/软件渲染场景安全)。

## Colors

- **单强调色策略**:整套只有一个强调色——香槟暖金 `{color.accent}`。交互、聚焦、在场都用它;
  绝不引入第二个霓虹色抢戏。这是"不乱"的第一保证。
- **层级靠明度不靠边框**:`canvas → surface → surface_raised` 三级近黑递进;玻璃层另靠
  半透明 + 模糊与实底内容拉开层次。边框只用极淡 `{color.border_subtle}`/`{material.glass_border}`。
- **三态 = 暖金递进**:`{color.phase_silent}` →`{color.phase_liminal}` →`{color.phase_manifest}`,
  与覆盖层语义严格一致。
- **语义色偏柔和**:success/warning/danger/info 一律去饱和;不用纯红纯绿。
- **对比度**:正文 `{color.text_primary}` on 实底 ≈ 15:1,远超 WCAG AA 4.5:1;次要文字
  `{color.text_secondary}` ≥ 4.5:1;`{color.text_muted}` 仅用于非关键标注。

## Typography

- 一套系统字栈(中英混排),不引 web font,启动零等待。
- 层级:`display`(仅 Galaxy 标题)/ `title` / `section`(全大写+字距,分区)/ `body`(对话正文,
  行高 1.6)/ `label` / `caption` / `mono`(模型名/token/代码)。
- 中文不用超细字重(<400 会发虚);正文 400、强调 500/600。

## Layout

- **三栏并置**:左 `rail`(`{layout.rail_width}`,图标栏,玻璃)| 中 主区(当前标签内容)|
  右 `presence`(`{layout.presence_width}`,在场/对照栏,玻璃)。中间内容区是实底滚动区。
- **图标栏(左)**:竖排图标 = 各标签;第一个是"对话"。选中靠**左缘 2px 暖金条 + 图标提亮**,
  不靠整块高亮。底部放全局状态点(连接/三态)。
- **对话(中,第一个标签)**:对话列限宽 `{layout.chat_max_width}` 居中;composer 吸底(玻璃)。
- **在场栏(右)**:三态指示 + presence 强度条 + coherence + 当前主脑模型 + 它正在看/听什么
  (感知状态),随对话实时变。这是"对话 ✕ 实时"对照面。
- **诊断抽屉**:从右侧滑出,`{layout.drawer_width}`,承载深度遥测;默认关。
- 间距用 `{space.*}` 阶梯;区块之间用更大留白(`xl`/`xxl`)分隔。

## Elevation

- `e0` 画布;`e1` 实底卡片/气泡(配 `border_subtle`);玻璃面用 `glass_e` 浮起投影 + 顶缘高光;
  `e2` 弹层/抽屉(配 `border_strong` + scrim)。
- `glow_accent` 仅用于"在场指示"等极少数需要呼吸感的元素;不滥用辉光。

## Shapes

- 圆角:气泡/输入/卡片 `{radius.md}`–`{radius.lg}`;玻璃外壳面 `{radius.xl}`;状态药丸
  `{radius.pill}`;小元素 `{radius.sm}`。统一圆角语言,不混用直角与大圆角。

## Components

- **icon_tab**(左栏项):图标按钮;默认 `text_secondary`;`active` → 图标 `text_primary` +
  左缘 2px `{color.accent}` 条 + 极淡暖金底辉;hover 提亮。不用整块高亮背景。
- **bubble.user**:右对齐,`surface_raised` **实底**,`radius.lg`(右下角收小)。
- **bubble.ai**:左对齐,`surface` **实底** + `border_subtle`,`radius.lg`(左下角收小);正文 `body`。
- **streaming_caret**:AI 流式回复时,末尾一个 `{color.accent}` 细竖条 1Hz 闪——配合 A 方案
  (SSE `POST /api/v1/chat/stream` 逐字 `delta`)做"实时生成"观感。
- **composer**(输入):玻璃底 + `border_subtle`,聚焦时边框转 `{color.accent}`;
  回车发送、Shift+回车换行;发送按钮 `button.primary`(玻璃 + 暖金)。
- **presence_indicator**(在场带):三点对应三态,`active` 点用对应 `phase_*` 色;
  `liminal` 时缓慢脉动(唯一允许的常驻动画),旁附 presence 强度细条。
- **metric_row**(右栏/状态):`label`(次要)+ 值(`mono`/`title`);需要时配柔和语义色药丸。
- **section_header**:`section` 字样(全大写+字距)+ 下方 `border_subtle` 细线。
- **status_pill**:小药丸,`success/warning/danger` 柔和底 + 同色文字(玻璃)。
- **button.primary**:`{color.accent}` 底 + `{color.on_accent}` 字;hover `accent_hover`;press `accent_press`。
- **button.ghost**:透明底 + `text_secondary`;hover 提亮 + `surface` 底。
- **drawer**(诊断):右滑,玻璃 `glass_bg_strong` + `e2` + `scrim`;承载遥测,默认关。

## Do's and Don'ts

**Do**
- 三栏:左图标 / 中内容(首个=对话)/ 右在场对照;一个焦点。
- 玻璃只用于导航/外壳层;对话与正文一律**实底**,保可读。
- 只用一个强调色(暖金),其余靠明度与留白。
- 动效只表达状态(三态切换、流式、消息到达),时长 `{motion.fast}`–`{motion.slow}`、`{motion.easing}`。
- 面板暖金与覆盖层辉光保持同源,让桌面 AI 像"一个东西"。
- 玻璃备好 `@supports` 实色降级,无独显/软件渲染不破版。
- 中文正文 ≥400 字重,行高 1.6。

**Don't**
- 不把玻璃铺到对话气泡/正文/列表上(会糊字)——这是首要红线。
- 不学苹果早期那种过曝强折射;模糊与反光都克制(小米/OPPO 取向)。
- 不把 NATS 原始流/深度遥测摆首屏——降级进诊断抽屉。
- 不堆第二个强调色、不用霓虹饱和色。
- 不做装饰性常驻动画(除 liminal 思考脉动);不给每个元素都加 fade/slide。
- 不用整块高亮背景做选中态(太重),用缘条+图标/文字明度。
- 不让对话列无限拉宽(超过 `{layout.chat_max_width}`)。
