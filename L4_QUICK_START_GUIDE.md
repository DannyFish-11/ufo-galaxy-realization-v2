# UFO Galaxy L4 级自主性智能系统 - 快速启动指南

## 🚀 5 分钟快速启动

### 前置条件

```bash
# 系统要求
- Ubuntu 22.04 或更高版本
- Python 3.11+
- Git
- 至少 4GB RAM
- 至少 10GB 磁盘空间

# 可选硬件（用于物理设备控制）
- 无人机（支持 MAVLink 协议）
- 3D 打印机（支持 OctoPrint API）
```

---

## 📥 步骤 1: 克隆仓库

```bash
# 克隆服务端代码
git clone https://github.com/DannyFish-11/ufo-galaxy-realization.git
cd ufo-galaxy-realization

# 克隆 Android 客户端（可选）
git clone https://github.com/DannyFish-11/ufo-galaxy-android.git
```

---

## 🔧 步骤 2: 安装依赖

```bash
# 安装 Python 依赖
pip3 install -r requirements.txt

# 或使用虚拟环境（推荐）
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

## ⚙️ 步骤 3: 配置系统

### 3.1 编辑 L4 配置文件

```bash
# 编辑配置
nano config/l4_config.json
```

**关键配置项**:

```json
{
  "system": {
    "name": "UFO Galaxy L4",
    "version": "1.0.0",
    "log_level": "INFO"
  },
  "environment_scanner": {
    "scan_interval": 300,
    "tools_to_scan": ["python", "node", "java", "git", "docker"]
  },
  "autonomous_planner": {
    "max_actions_per_plan": 50,
    "resource_matching_threshold": 0.8
  },
  "devices": {
    "drone": {
      "enabled": false,
      "connection": "mavlink",
      "host": "127.0.0.1",
      "port": 14550
    },
    "3d_printer": {
      "enabled": false,
      "connection": "octoprint",
      "api_url": "http://localhost:5000",
      "api_key": "YOUR_OCTOPRINT_API_KEY"
    }
  }
}
```

### 3.2 配置物理设备（可选）

**无人机配置**:

```json
{
  "devices": {
    "drone": {
      "enabled": true,
      "connection": "mavlink",
      "host": "192.168.1.100",  // 无人机 IP
      "port": 14550,
      "protocol": "v2.0"
    }
  }
}
```

**3D 打印机配置**:

```json
{
  "devices": {
    "3d_printer": {
      "enabled": true,
      "connection": "octoprint",
      "api_url": "http://192.168.1.200:5000",  // OctoPrint 地址
      "api_key": "YOUR_API_KEY_HERE"
    }
  }
}
```

---

## ✅ 步骤 4: 运行测试

### 4.1 端到端测试

```bash
# 测试所有 L4 核心模块
python3 tests/test_l4_e2e.py
```

**预期输出**:

```
============================================================
UFO Galaxy L4 级自主性智能系统 - 端到端测试
============================================================
✓ 测试 1: 环境扫描器 - 通过
✓ 测试 2: 目标分解 - 通过
✓ 测试 3: 自主规划 - 通过
✓ 测试 4: 世界模型 - 通过
✓ 测试 5: 元认知服务 - 通过
✓ 测试 6: 自主编程 - 通过
✓ 测试 7: 完整 L4 周期 - 通过
============================================================
✓ L4 级自主性智能系统已就绪！
```

### 4.2 物理设备控制测试

```bash
# 测试物理设备控制（计划生成）
python3 tests/test_l4_physical_devices.py
```

**预期输出**:

```
============================================================
UFO Galaxy L4 级物理设备控制测试
============================================================
✓ 测试 1: 无人机控制 - 通过
✓ 测试 2: 3D 打印机控制 - 通过
✓ 测试 3: 多设备协同控制 - 通过
✓ 测试 4: 世界模型集成 - 通过
============================================================
✓ L4 级物理设备控制系统已就绪！
```

---

## 🎯 步骤 5: 启动 L4 系统

### 5.1 手动启动

```bash
# 启动 L4 主循环
python3 start_l4.py
```

**预期输出**:

```
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║   █    █ ███████  ███████     ███████  █████  ██      █████ ║
║   █    █ █        █     █    █        █    █ █      █    █ ║
║   █    █ █        █     █    █        █    █ █      █    █ ║
║   █    █ █████    █     █    █  ████  █████  █      █████  ║
║   █    █ █        █     █    █     █  █   █  █      █   █  ║
║   █    █ █        █     █    █     █  █    █ █      █    █ ║
║   ██████ █        ███████     ███████  █    █ ██████ █    █ ║
║                                                              ║
║                  L4 Autonomous Intelligence System          ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝

[INFO] UFO Galaxy L4 系统启动中...
[INFO] 加载配置: config/l4_config.json
[INFO] 初始化环境扫描器...
[INFO] 初始化目标分解器...
[INFO] 初始化自主规划器...
[INFO] 初始化世界模型...
[INFO] 初始化元认知服务...
[INFO] 初始化自主编程器...
[INFO] L4 主循环已启动
[INFO] 系统就绪，等待目标输入...
```

### 5.2 自动启动（systemd 服务）

```bash
# 复制服务文件
sudo cp deployment/ufo-galaxy-l4.service /etc/systemd/system/

# 重新加载 systemd
sudo systemctl daemon-reload

# 启用自动启动
sudo systemctl enable ufo-galaxy-l4

# 启动服务
sudo systemctl start ufo-galaxy-l4

# 查看状态
sudo systemctl status ufo-galaxy-l4

# 查看日志
sudo journalctl -u ufo-galaxy-l4 -f
```

---

## 🧪 步骤 6: 测试自然语言控制

### 6.1 通过命令行测试

```bash
# 启动交互式测试
python3 -c "
import asyncio
from enhancements.reasoning.goal_decomposer import GoalDecomposer, Goal, GoalType

async def test():
    decomposer = GoalDecomposer()
    goal = Goal(
        description='用 3D 打印机打印一个无人机支架，然后让无人机飞到阳台拍照',
        type=GoalType.TASK_EXECUTION,
        constraints=[],
        success_criteria=['支架打印完成', '照片已保存'],
        deadline=None
    )
    result = decomposer.decompose(goal)
    print(f'分解为 {len(result.subtasks)} 个子任务:')
    for i, st in enumerate(result.subtasks, 1):
        print(f'  {i}. {st.description}')

asyncio.run(test())
"
```

### 6.2 通过 Android 客户端测试（可选）

1. 在 Android Studio 中打开 `ufo-galaxy-android` 项目
2. 配置服务器地址（`app/src/main/res/values/strings.xml`）
3. 编译并安装到 Android 设备
4. 启用无障碍服务（设置 → 无障碍 → UFO Galaxy）
5. 打开应用，输入自然语言指令

**示例指令**:
- "让无人机起飞到 10 米高度拍照"
- "用 3D 打印机打印一个测试立方体"
- "打印支架然后让无人机飞到阳台"

---

## 📊 步骤 7: 监控系统状态

### 7.1 查看日志

```bash
# 实时查看日志
tail -f logs/ufo_galaxy_l4.log

# 查看特定模块日志
grep "AutonomousPlanner" logs/ufo_galaxy_l4.log
```

### 7.2 查看性能指标

```bash
# 查看元认知评估
python3 -c "
from enhancements.reasoning.metacognition_service import MetaCognitionService

metacog = MetaCognitionService()
# 加载历史数据
# ...
print('性能评估:', metacog.assessments)
"
```

---

## 🐛 故障排查

### 问题 1: 导入错误

**错误**: `ModuleNotFoundError: No module named 'enhancements'`

**解决**:

```bash
# 确保在正确的目录
cd ufo-galaxy-realization

# 添加到 Python 路径
export PYTHONPATH="${PYTHONPATH}:$(pwd)"

# 或在脚本开头添加
import sys
sys.path.insert(0, '/path/to/ufo-galaxy-realization')
```

### 问题 2: 资源匹配失败

**错误**: `未找到匹配的资源: xxx`

**解决**:

1. 检查 `config/l4_config.json` 中的设备配置
2. 确保设备的 `capabilities` 与子任务的 `required_capabilities` 匹配
3. 查看日志了解详细错误信息

### 问题 3: 物理设备连接失败

**错误**: `Connection refused` 或 `Timeout`

**解决**:

1. 检查设备是否开机并连接到网络
2. 验证 IP 地址和端口是否正确
3. 测试网络连接: `ping <device_ip>`
4. 检查防火墙设置

---

## 📚 进阶使用

### 自定义目标类型

```python
from enhancements.reasoning.goal_decomposer import GoalDecomposer, Goal, GoalType

# 创建自定义目标
goal = Goal(
    description="你的自定义目标",
    type=GoalType.CREATION,  # 或其他类型
    constraints=["约束条件 1", "约束条件 2"],
    success_criteria=["成功标准 1", "成功标准 2"],
    deadline=None  # 或 Unix 时间戳
)

decomposer = GoalDecomposer()
result = decomposer.decompose(goal)
```

### 添加自定义资源

```python
from enhancements.reasoning.autonomous_planner import AutonomousPlanner, Resource, ResourceType

planner = AutonomousPlanner()
planner.available_resources.append(
    Resource(
        id="custom_device_1",
        type=ResourceType.DEVICE,
        name="自定义设备",
        capabilities=["capability_1", "capability_2"],
        availability=1.0,
        metadata={"key": "value"}
    )
)
```

### 自定义节点开发

```python
# 在 nodes/ 目录下创建新节点
# nodes/Node_XXX_CustomNode/custom_node.py

class CustomNode:
    def __init__(self):
        self.name = "CustomNode"
        self.capabilities = ["custom_capability"]
    
    async def execute(self, command: str, parameters: dict):
        # 实现你的逻辑
        return {"success": True, "result": "..."}
```

---

## 🔗 相关链接

- **GitHub 仓库**: https://github.com/DannyFish-11/ufo-galaxy-realization
- **Android 客户端**: https://github.com/DannyFish-11/ufo-galaxy-android
- **完整状态报告**: `L4_SYSTEM_STATUS_REPORT.md`
- **部署文档**: `deployment/L4_DEPLOYMENT.md`

---

## 💡 示例场景

### 场景 1: 无人机航拍

```
目标: "让无人机起飞到 20 米高度，向北飞行 100 米，拍 5 张照片，然后返回并降落"

系统行为:
1. 分解为 6 个子任务（起飞、设置高度、移动、拍照、返回、降落）
2. 匹配无人机控制器资源
3. 生成 6 个动作
4. 执行计划
5. 学习和反思
```

### 场景 2: 3D 打印工作流

```
目标: "设计一个 10cm x 10cm 的手机支架，生成 STL 文件，然后用 3D 打印机打印"

系统行为:
1. 分解为 3 个子任务（设计、生成文件、打印）
2. 匹配 CAD 工具和 3D 打印机资源
3. 生成 3 个动作
4. 执行计划
5. 学习和反思
```

### 场景 3: 多设备协同

```
目标: "用 3D 打印机打印一个无人机支架，安装到无人机上，然后让无人机飞到阳台拍照"

系统行为:
1. 分解为 4 个子任务（打印、安装、飞行、拍照）
2. 匹配 3D 打印机和无人机资源
3. 生成 4 个动作，建立依赖关系
4. 按顺序执行计划
5. 学习和反思
```

---

## 🎓 学习资源

### 推荐阅读

1. **L4 系统架构**: `galaxy_main_loop_l4.py`
2. **目标分解算法**: `enhancements/reasoning/goal_decomposer.py`
3. **资源匹配逻辑**: `enhancements/reasoning/autonomous_planner.py`
4. **元认知机制**: `enhancements/reasoning/metacognition_service.py`

### 视频教程（待制作）

1. L4 系统概览
2. 自然语言控制演示
3. 物理设备集成指南
4. 自定义节点开发

---

## 🤝 贡献指南

欢迎贡献代码、报告问题或提出建议！

1. Fork 仓库
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启 Pull Request

---

## 📄 许可证

本项目采用 MIT 许可证 - 详见 `LICENSE` 文件

---

## 🙏 致谢

- OpenAI GPT 系列模型
- MAVLink 协议开发团队
- OctoPrint 开源社区
- 所有贡献者和支持者

---

**快速启动指南版本**: v1.0.0  
**最后更新**: 2025-02-05  
**系统状态**: ✅ L4 级自主性智能系统已就绪！

---

## ❓ 常见问题

### Q1: L4 系统需要 LLM 吗？

**A**: 不是必需的。系统可以在没有 LLM 的情况下运行，使用基于规则的分解和规划。但是，集成 LLM（如 OpenAI GPT）可以显著提升目标理解和代码生成能力。

### Q2: 可以在 Windows 上运行吗？

**A**: 理论上可以，但推荐使用 Ubuntu/Linux。如果必须在 Windows 上运行，建议使用 WSL2（Windows Subsystem for Linux）。

### Q3: 如何添加新的物理设备？

**A**: 
1. 在 `nodes/` 目录下创建新节点
2. 实现设备控制逻辑
3. 在 `config/l4_config.json` 中添加设备配置
4. 在 `GoalDecomposer` 中添加设备检测逻辑
5. 测试并验证

### Q4: 系统安全吗？

**A**: 系统包含基本的安全措施（沙箱执行、错误处理），但在控制物理设备时请务必小心。建议：
- 在安全环境中测试
- 添加用户确认机制
- 实施访问控制
- 定期备份数据

### Q5: 如何获得技术支持？

**A**: 
- 提交 GitHub Issue
- 查看文档和示例代码
- 加入社区讨论（待建立）

---

**祝你使用愉快！🚀**
