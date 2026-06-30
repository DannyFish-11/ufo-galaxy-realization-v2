---
# Galaxy Panel — Design Tokens (design.md format)
# 机器可读 token；下方 Markdown 是理由与组件规范。引用语法:{path.to.token}
meta:
  name: Galaxy Control Panel
  version: 1.0.0
  mode: dark-only            # 桌面 AI 覆盖层之上的"镜头",恒为深色
  accent_strategy: single    # 单一暖金强调色,与覆盖层三态辉光同源

color:
  # 画布与表面(近黑、微暖中性;层级靠明度,不靠重边框)
  canvas:        "#0C0D11"
  surface:       "#14151B"
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

typography:
  font_sans: "'Inter','SF Pro Display','Segoe UI Variable Text','Segoe UI',system-ui,-apple-system,'PingFang SC','Microsoft YaHei','Noto Sans SC',sans-serif"
  font_mono: "'SF Mono','JetBrains Mono','Cascadia Code',ui-monospace,Consolas,monospace"
  display:   { size: "28px", weight: 300, line: "1.2",  track: "0.01em" }   # Galaxy 标题
  title:     { size: "18px", weight: 500, line: "1.3" }
  section:   { size: "12px", weight: 600, line: "1.4",  track: "0.10em", transform: "uppercase" }  # 分区小标题
  body:      { size: "15px", weight: 400, line: "1.6" }   # 对话正文
  label:     { size: "12px", weight: 500, line: "1.4" }
  caption:   { size: "11px", weight: 400, line: "1.4" }
  mono:      { size: "13px", weight: 400, line: "1.5" }   # 模型名/token/代码

space:   { xs: "4px", sm: "8px", md: "12px", lg: "16px", xl: "24px", xxl: "32px", xxxl: "48px" }
radius:  { sm: "8px", md: "12px", lg: "16px", pill: "999px" }

elevation:
  e0: "none"
  e1: "0 1px 2px rgba(0,0,0,0.40)"                         # 卡片/气泡 + border_subtle
  e2: "0 12px 40px rgba(0,0,0,0.50)"                       # 抽屉/弹层 + border_strong
  glow_accent: "0 0 24px rgba(230,192,123,0.35)"           # 强调辉光(用于在场指示,克制)

motion:
  fast: "150ms"
  base: "250ms"
  slow: "400ms"
  easing: "cubic-bezier(0.2, 0, 0, 1)"                     # easeOut;进场用
  principle: "motion = 表达状态(三态/流式/到达),不做装饰;除 liminal 思考脉动外无常驻循环"

layout:
  rail_width: "200px"          # 左侧 tabs 栏
  chat_max_width: "760px"      # 右栏对话列最大宽,过宽不利阅读
  gap: "{space.lg}"
  drawer_width: "min(440px, 80vw)"   # 诊断抽屉(遥测降级进此)
---

# Galaxy Control Panel — DESIGN.md

## Overview

控制面板是桌面 AI(三态覆盖层)的**镜头**:看进同一个"在场"。它不是遥测仪表盘——
**首屏只做两件事:左侧 tabs 导航 + 右侧上下文对话(聊天范式)**,对话进行时旁边用三态/在场
强度做**实时对照**。其余系统遥测(NATS/拓扑/Provider/Mesh…)一律降级进**诊断抽屉**,默认隐藏。

设计基调三个词:**静谧、聚焦、同源**。
- **静谧**:深色近黑画布、柔和语义色、克制动效——不吵、不怪。
- **聚焦**:同一时刻只有一个焦点(对话);信息靠层级与留白分层,不靠堆部件。
- **同源**:面板的暖金强调色 = 覆盖层的"暖金边缘辉光",三态色一一对应,让桌面 AI 是"一个东西"。

参考:`design.md`(本格式)为骨;克制的对话界面取向参考 Codex / Claude 那类(深色、单强调、
大留白、动效只表状态)。

## Colors

- **单强调色策略**:整套只有一个强调色——香槟暖金 `{color.accent}`。交互、聚焦、在场都用它;
  绝不引入第二个霓虹色抢戏。这是"不乱"的第一保证。
- **层级靠明度不靠边框**:`canvas → surface → surface_raised` 三级近黑递进;边框只用极淡
  `{color.border_subtle}`,弹层才用 `{color.border_strong}`。
- **三态 = 暖金递进**:`{color.phase_silent}`(暗金/待机)→ `{color.phase_liminal}`(活跃/思考)
  → `{color.phase_manifest}`(满亮/表达)。与覆盖层语义严格一致。
- **语义色偏柔和**:success/warning/danger/info 一律去饱和,保持静谧;不用纯红纯绿。
- **对比度**:正文 `{color.text_primary}` on `{color.canvas}` ≈ 15:1,远超 WCAG AA 4.5:1;
  次要文字 `{color.text_secondary}` ≥ 4.5:1;`{color.text_muted}` 仅用于非关键标注。

## Typography

- 一套系统字栈(中英混排),不引 web font,启动零等待。
- 层级清晰、克制:`display`(仅 Galaxy 标题)/ `title` / `section`(全大写+字距,做分区)/
  `body`(对话正文,行高 1.6 利阅读)/ `label` / `caption` / `mono`(模型名/token/代码)。
- 中文不用超细字重(<400 会发虚);正文 400、强调 500/600。

## Layout

- **左右并置**:左 `rail`(`{layout.rail_width}`,tabs 导航,内容你后续布)| 右 主区(对话 + 在场对照)。
- **对话列**限宽 `{layout.chat_max_width}`,居中,避免过宽难读;输入框(composer)吸底。
- **在场对照**:对话区顶部/侧边一条窄"在场带"——三态指示 + presence 强度,随对话实时变。
- **诊断抽屉**:从右侧滑出,`{layout.drawer_width}`,承载所有遥测;默认关。
- 间距用 `{space.*}` 阶梯;同类元素间距一致,区块之间用更大留白(`xl`/`xxl`)分隔。

## Elevation

- `e0` 画布;`e1` 卡片/气泡(配 `border_subtle`);`e2` 抽屉/弹层(配 `border_strong` + scrim)。
- `glow_accent` 仅用于"在场指示"等极少数需要呼吸感的元素;不滥用辉光。

## Shapes

- 圆角:气泡/输入/卡片 `{radius.md}`–`{radius.lg}`;状态药丸 `{radius.pill}`;小元素 `{radius.sm}`。
- 统一圆角语言,不混用直角与大圆角。

## Components

- **tab**(左栏项):默认 `text_secondary`;`active` → `text_primary` + 左缘 2px `{color.accent}` 条;
  hover 提亮。不靠整块高亮背景(太重),靠"缘条 + 文字明度"。
- **bubble.user**:右对齐,`surface_raised` 底,`radius.lg`(右下角收小)。
- **bubble.ai**:左对齐,`surface` 底 + `border_subtle`,`radius.lg`(左下角收小);正文 `body`。
- **streaming_caret**:AI 流式回复时,末尾一个 `{color.accent}` 细竖条 1Hz 闪——配合 A 方案
  (SSE `POST /api/v1/chat/stream` 逐字)做"实时生成"观感。
- **composer**(输入):`surface_raised` + `border_subtle`,聚焦时边框转 `{color.accent}`;
  回车发送、Shift+回车换行;发送按钮 `button.primary`。
- **presence_indicator**(在场带):三点对应三态,`active` 点用对应 `phase_*` 色;
  `liminal` 时缓慢脉动(唯一允许的常驻动画),旁附 presence 强度细条。
- **section_header**:`section` 字样(全大写+字距)+ 下方 `border_subtle` 细线。
- **status_pill**:小药丸,`success/warning/danger` 柔和底 + 同色文字。
- **button.primary**:`{color.accent}` 底 + `{color.on_accent}` 字;hover `accent_hover`;press `accent_press`。
- **button.ghost**:透明底 + `text_secondary`;hover 提亮 + `surface` 底。
- **drawer**(诊断):右滑,`e2` + `scrim`;承载遥测组件,默认关。

## Do's and Don'ts

**Do**
- 首屏只留"对话 + 在场对照";一个焦点。
- 只用一个强调色(暖金),其余靠明度与留白。
- 动效只表达状态(三态切换、流式、消息到达),时长 `{motion.fast}`–`{motion.slow}`、`{motion.easing}`。
- 面板暖金与覆盖层辉光保持同源,让桌面 AI 像"一个东西"。
- 中文正文 ≥400 字重,行高 1.6。

**Don't**
- 不把 NATS 流/拓扑/Provider/橡树/Mesh 摆首屏——降级进诊断抽屉。
- 不堆第二个强调色、不用霓虹饱和色。
- 不做装饰性常驻动画(除 liminal 思考脉动);不给每个元素都加 fade/slide。
- 不用整块高亮背景做选中态(太重),用缘条+文字明度。
- 不让对话列无限拉宽(超过 `{layout.chat_max_width}`)。
