# Node 130: AutonomousCoding — 自主编程引擎

**分类**: CodeEngine | **端口**: 8130 | **状态**: Active

## 功能

自主编程引擎，提供：
- **代码生成** — 根据自然语言描述生成代码
- **Bug修复** — 分析并修复代码中的错误
- **测试编写** — 自动生成单元测试和集成测试
- **代码优化** — 性能分析和优化建议
- **代码重构** — 改善代码结构而不改变行为
- **质量分析** — 代码质量评估和报告

支持语言：Python, JavaScript/TypeScript, Java, Rust, Go 等。

## Golden Path

1. 通过 AIP v3 协议接收编码任务
2. 委托给 `enhancements/coding/autonomous_coding_engine_v2.py`
3. 返回结构化代码+解释+测试用例

## 依赖

- FastAPI + Pydantic
- 底层引擎: `autonomous_coding_engine_v2.py`

## API

- `POST /generate` — 代码生成
- `POST /fix` — Bug修复
- `POST /test` — 测试编写
- `POST /optimize` — 代码优化
- `POST /refactor` — 代码重构
- `POST /analyze` — 质量分析
- `GET /health` — 健康检查
