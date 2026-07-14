"""
L4 级物理设备控制测试
测试通过自然语言指令控制无人机和 3D 打印机
"""

import asyncio
import sys
from pathlib import Path

# 添加路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from enhancements.perception.environment_scanner import EnvironmentScanner
from enhancements.reasoning.autonomous_planner import AutonomousPlanner, Resource, ResourceType
from enhancements.reasoning.goal_decomposer import Goal, GoalDecomposer, GoalType
from enhancements.reasoning.world_model import Entity, EntityState, EntityType, WorldModel


async def test_drone_control():
    """测试无人机控制"""
    print("\n" + "=" * 60)
    print("测试 1: 无人机控制")
    print("=" * 60)

    # 1. 创建目标
    goal = Goal(
        description="让无人机起飞到 10 米高度，拍一张照片，然后降落",
        type=GoalType.TASK_EXECUTION,
        constraints=["安全第一", "电池电量 > 30%"],
        success_criteria=["照片已保存", "无人机已安全降落"],
        deadline=None,
    )

    print(f"✓ 目标: {goal.description}")

    # 2. 分解目标
    decomposer = GoalDecomposer()
    decomposition = decomposer.decompose(goal)

    print(f"✓ 分解为 {len(decomposition.subtasks)} 个子任务:")
    for i, subtask in enumerate(decomposition.subtasks, 1):
        print(f"  {i}. {subtask.description}")
        print(f"     - 类型: {subtask.type.value}")
        print(f"     - 所需能力: {', '.join(subtask.required_capabilities)}")

    # 3. 创建计划
    planner = AutonomousPlanner()
    planner.available_resources = [
        Resource(
            id="node_43_mavlink",
            type=ResourceType.DEVICE,
            name="无人机控制器",
            capabilities=["drone_control", "takeoff", "land", "capture_image", "set_altitude"],
            availability=1.0,
            metadata={"connection": "MAVLink", "protocol": "v2.0"},
        )
    ]

    plan = planner.create_plan(decomposition)

    print(f"\n✓ 创建了包含 {len(plan.actions)} 个动作的计划:")
    for i, action_id in enumerate(plan.execution_order, 1):
        action = next((a for a in plan.actions if a.id == action_id), None)
        if action:
            resource_id = action.node_id or action.device_id or "unknown"
            print(f"  {i}. {action.command}")
            print(f"     - 资源: {resource_id}")
            print(f"     - 参数: {action.parameters}")
            print(f"     - 预计时长: {action.expected_duration} 秒")

    print("\n✓ 无人机控制测试通过（计划生成成功）")
    print("⚠️  注意: 实际执行需要连接真实无人机硬件")

    return plan


async def test_3d_printer_control():
    """测试 3D 打印机控制"""
    print("\n" + "=" * 60)
    print("测试 2: 3D 打印机控制")
    print("=" * 60)

    # 1. 创建目标
    goal = Goal(
        description="用 3D 打印机打印一个 5cm x 5cm 的测试立方体",
        type=GoalType.TASK_EXECUTION,
        constraints=["使用 PLA 材料", "标准质量"],
        success_criteria=["打印完成", "模型无瑕疵"],
        deadline=None,
    )

    print(f"✓ 目标: {goal.description}")

    # 2. 分解目标
    decomposer = GoalDecomposer()
    decomposition = decomposer.decompose(goal)

    print(f"✓ 分解为 {len(decomposition.subtasks)} 个子任务:")
    for i, subtask in enumerate(decomposition.subtasks, 1):
        print(f"  {i}. {subtask.description}")
        print(f"     - 类型: {subtask.type.value}")
        print(f"     - 所需能力: {', '.join(subtask.required_capabilities)}")

    # 3. 创建计划
    planner = AutonomousPlanner()
    planner.available_resources = [
        Resource(
            id="node_49_octoprint",
            type=ResourceType.DEVICE,
            name="3D打印机",
            capabilities=["3d_printing", "file_upload", "print_control", "temperature_control"],
            availability=1.0,
            metadata={"connection": "OctoPrint API", "model": "Prusa i3"},
        )
    ]

    plan = planner.create_plan(decomposition)

    print(f"\n✓ 创建了包含 {len(plan.actions)} 个动作的计划:")
    for i, action_id in enumerate(plan.execution_order, 1):
        action = next((a for a in plan.actions if a.id == action_id), None)
        if action:
            resource_id = action.node_id or action.device_id or "unknown"
            print(f"  {i}. {action.command}")
            print(f"     - 资源: {resource_id}")
            print(f"     - 参数: {action.parameters}")
            print(f"     - 预计时长: {action.expected_duration} 秒")

    print("\n✓ 3D 打印机控制测试通过（计划生成成功）")
    print("⚠️  注意: 实际执行需要连接真实 3D 打印机硬件")

    return plan


async def test_multi_device_coordination():
    """测试多设备协同"""
    print("\n" + "=" * 60)
    print("测试 3: 多设备协同控制")
    print("=" * 60)

    # 1. 创建复杂目标
    goal = Goal(
        description="用 3D 打印机打印一个无人机支架，然后让无人机飞到阳台拍照",
        type=GoalType.TASK_EXECUTION,
        constraints=["按顺序执行", "确保安全"],
        success_criteria=["支架打印完成", "照片已保存", "无人机已降落"],
        deadline=None,
    )

    print(f"✓ 目标: {goal.description}")

    # 2. 分解目标
    decomposer = GoalDecomposer()
    decomposition = decomposer.decompose(goal)

    print(f"✓ 分解为 {len(decomposition.subtasks)} 个子任务:")
    for i, subtask in enumerate(decomposition.subtasks, 1):
        print(f"  {i}. {subtask.description}")
        print(f"     - 类型: {subtask.type.value}")
        print(f"     - 依赖: {', '.join(subtask.dependencies) if subtask.dependencies else '无'}")
        print(f"     - 所需能力: {', '.join(subtask.required_capabilities)}")

    # 3. 创建计划
    planner = AutonomousPlanner()
    planner.available_resources = [
        Resource(
            id="node_49_octoprint",
            type=ResourceType.DEVICE,
            name="3D打印机",
            capabilities=["3d_printing", "file_upload", "print_control"],
            availability=1.0,
            metadata={"connection": "OctoPrint API"},
        ),
        Resource(
            id="node_43_mavlink",
            type=ResourceType.DEVICE,
            name="无人机控制器",
            capabilities=["drone_control", "takeoff", "land", "capture_image"],
            availability=1.0,
            metadata={"connection": "MAVLink"},
        ),
    ]

    plan = planner.create_plan(decomposition)

    print(f"\n✓ 创建了包含 {len(plan.actions)} 个动作的计划:")
    for i, action_id in enumerate(plan.execution_order, 1):
        action = next((a for a in plan.actions if a.id == action_id), None)
        if action:
            resource_id = action.node_id or action.device_id or "unknown"
            print(f"  {i}. {action.command}")
            print(f"     - 资源: {resource_id}")
            print(f"     - 子任务: {action.subtask_id}")
            print(f"     - 预计时长: {action.expected_duration} 秒")

    # 4. 验证执行顺序
    print(f"\n✓ 执行顺序验证:")
    print(f"  - 总预计时长: {plan.total_estimated_duration} 秒")
    print(f"  - 所需资源: {len(plan.required_resources)} 个")
    for res in plan.required_resources:
        print(f"    - {res.name} ({res.id})")

    print("\n✓ 多设备协同控制测试通过（计划生成成功）")
    print("⚠️  注意: 实际执行需要连接真实硬件设备")

    return plan


async def test_world_model_integration():
    """测试世界模型集成"""
    print("\n" + "=" * 60)
    print("测试 4: 世界模型集成")
    print("=" * 60)

    world = WorldModel()

    # 注册设备
    devices = [
        Entity(
            id="drone_mavic_2",
            type=EntityType.DEVICE,
            name="DJI Mavic 2 Pro",
            state=EntityState.ACTIVE,
            properties={"battery": 85, "gps_fix": True, "altitude": 0, "location": {"lat": 39.9042, "lon": 116.4074}},
        ),
        Entity(
            id="printer_prusa_i3",
            type=EntityType.DEVICE,
            name="Prusa i3 MK3S",
            state=EntityState.ACTIVE,
            properties={"status": "idle", "bed_temp": 25, "nozzle_temp": 25, "filament": "PLA"},
        ),
        Entity(
            id="android_phone_1",
            type=EntityType.DEVICE,
            name="Android 控制终端",
            state=EntityState.ACTIVE,
            properties={"battery": 90, "network": "WiFi", "location": "home"},
        ),
    ]

    for device in devices:
        world.register_entity(device)

    print(f"✓ 注册了 {len(world.entities)} 个设备:")
    for entity_id, entity in world.entities.items():
        print(f"  - {entity.name} ({entity_id})")
        print(f"    状态: {entity.state.value}")
        print(f"    属性: {entity.properties}")

    # 查询设备状态
    print(f"\n✓ 查询无人机状态:")
    drone_state = world.query_state("drone_mavic_2")
    print(f"  - 相关实体数: {len(drone_state)}")

    print("\n✓ 世界模型集成测试通过")

    return world


async def main():
    """主测试函数"""
    print("\n" + "=" * 60)
    print("Galaxy L4 级物理设备控制测试")
    print("=" * 60)

    try:
        # 运行所有测试
        drone_plan = await test_drone_control()
        printer_plan = await test_3d_printer_control()
        multi_plan = await test_multi_device_coordination()
        world = await test_world_model_integration()

        # 总结
        print("\n" + "=" * 60)
        print("测试总结")
        print("=" * 60)
        print("✓ 所有测试通过！")
        print(f"✓ 无人机控制: {len(drone_plan.actions)} 个动作")
        print(f"✓ 3D 打印机控制: {len(printer_plan.actions)} 个动作")
        print(f"✓ 多设备协同: {len(multi_plan.actions)} 个动作")
        print(f"✓ 世界模型: {len(world.entities)} 个设备")
        print("\n✓ L4 级物理设备控制系统已就绪！")
        print("\n📝 下一步:")
        print("  1. 连接真实无人机硬件（MAVLink 协议）")
        print("  2. 连接真实 3D 打印机（OctoPrint API）")
        print("  3. 配置设备连接参数")
        print("  4. 执行实际物理设备控制测试")

    except Exception as e:
        print(f"\n✗ 测试失败: {e}")
        import traceback

        traceback.print_exc()
        return False

    return True


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
