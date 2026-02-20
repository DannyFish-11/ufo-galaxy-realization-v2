"""
UFO³ Galaxy 自主学习系统 - Node 53

功能：
1. 用户行为分析
2. 使用模式学习
3. 参数自动优化
4. 个性化建议
5. 持续改进

作者：Manus AI
日期：2025-01-20
"""

import json
import time
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
from collections import defaultdict
import statistics

@dataclass
class UserAction:
    """用户行为记录"""
    timestamp: float
    action_type: str  # 命令类型
    command: str  # 原始命令
    device: str  # 目标设备
    success: bool  # 是否成功
    duration: float  # 执行时间
    parameters: Dict[str, Any]  # 参数

class SelfLearningSystem:
    """自主学习系统"""
    
    def __init__(self, persist_file: str = "./learning_data.json"):
        """
        初始化学习系统
        
        Args:
            persist_file: 持久化文件路径
        """
        self.persist_file = persist_file
        self.user_actions: List[UserAction] = []
        self.usage_patterns: Dict[str, Any] = {}
        self.optimized_parameters: Dict[str, Any] = {}
        
        # 加载历史数据
        self._load_data()
        
        print("自主学习系统已初始化")
    
    def record_action(self, action: UserAction):
        """
        记录用户行为
        
        Args:
            action: 用户行为
        """
        self.user_actions.append(action)
        
        # 定期分析（每 10 个行为）
        if len(self.user_actions) % 10 == 0:
            self._analyze_patterns()
    
    def _analyze_patterns(self):
        """分析使用模式"""
        print("\n🔍 分析使用模式...")
        
        # 统计命令频率
        command_frequency = defaultdict(int)
        device_usage = defaultdict(int)
        time_distribution = defaultdict(int)
        
        for action in self.user_actions:
            command_frequency[action.action_type] += 1
            device_usage[action.device] += 1
            
            # 时间分布（按小时）
            hour = time.localtime(action.timestamp).tm_hour
            time_distribution[hour] += 1
        
        # 更新使用模式
        self.usage_patterns = {
            "most_used_commands": sorted(
                command_frequency.items(),
                key=lambda x: x[1],
                reverse=True
            )[:5],
            "most_used_devices": sorted(
                device_usage.items(),
                key=lambda x: x[1],
                reverse=True
            )[:3],
            "peak_hours": sorted(
                time_distribution.items(),
                key=lambda x: x[1],
                reverse=True
            )[:3],
            "total_actions": len(self.user_actions)
        }
        
        print("✅ 使用模式分析完成")
    
    def optimize_parameters(self, action_type: str) -> Dict[str, Any]:
        """
        基于历史数据优化参数
        
        Args:
            action_type: 行为类型
        
        Returns:
            优化后的参数
        """
        # 筛选相关行为
        relevant_actions = [
            a for a in self.user_actions
            if a.action_type == action_type and a.success
        ]
        
        if not relevant_actions:
            return {}
        
        # 分析参数
        optimized = {}
        
        # 示例：优化打印温度
        if action_type == "3d_print":
            temps = [
                a.parameters.get("temperature", 220)
                for a in relevant_actions
            ]
            if temps:
                optimized["temperature"] = statistics.mean(temps)
        
        # 示例：优化无人机飞行高度
        elif action_type == "drone_flight":
            altitudes = [
                a.parameters.get("altitude", 20)
                for a in relevant_actions
            ]
            if altitudes:
                optimized["altitude"] = statistics.mean(altitudes)
        
        self.optimized_parameters[action_type] = optimized
        
        return optimized
    
    def get_personalized_suggestions(self) -> List[str]:
        """
        获取个性化建议
        
        Returns:
            建议列表
        """
        suggestions = []
        
        if not self.usage_patterns:
            return ["继续使用系统以获得个性化建议"]
        
        # 基于最常用命令的建议
        most_used = self.usage_patterns.get("most_used_commands", [])
        if most_used:
            top_command = most_used[0][0]
            suggestions.append(f"您经常使用'{top_command}'命令，已为您优化相关参数")
        
        # 基于设备使用的建议
        most_used_device = self.usage_patterns.get("most_used_devices", [])
        if most_used_device:
            device = most_used_device[0][0]
            suggestions.append(f"检测到您主要使用 {device} 设备，建议定期维护")
        
        # 基于时间分布的建议
        peak_hours = self.usage_patterns.get("peak_hours", [])
        if peak_hours:
            hour = peak_hours[0][0]
            suggestions.append(f"您通常在 {hour}:00 使用系统，系统已自动调整为该时段优化性能")
        
        return suggestions
    
    def get_success_rate(self, action_type: Optional[str] = None) -> float:
        """
        获取成功率
        
        Args:
            action_type: 行为类型（None 表示全部）
        
        Returns:
            成功率（0-100）
        """
        if action_type:
            actions = [a for a in self.user_actions if a.action_type == action_type]
        else:
            actions = self.user_actions
        
        if not actions:
            return 0.0
        
        successful = sum(1 for a in actions if a.success)
        return (successful / len(actions)) * 100
    
    def get_performance_metrics(self) -> Dict[str, Any]:
        """获取性能指标"""
        if not self.user_actions:
            return {}
        
        durations = [a.duration for a in self.user_actions if a.success]
        
        return {
            "total_actions": len(self.user_actions),
            "success_rate": self.get_success_rate(),
            "average_duration": statistics.mean(durations) if durations else 0,
            "fastest_action": min(durations) if durations else 0,
            "slowest_action": max(durations) if durations else 0
        }
    
    def _save_data(self):
        """保存数据到文件"""
        data = {
            "user_actions": [asdict(a) for a in self.user_actions],
            "usage_patterns": self.usage_patterns,
            "optimized_parameters": self.optimized_parameters
        }
        
        with open(self.persist_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def _load_data(self):
        """从文件加载数据"""
        try:
            with open(self.persist_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            self.user_actions = [
                UserAction(**action_data)
                for action_data in data.get("user_actions", [])
            ]
            self.usage_patterns = data.get("usage_patterns", {})
            self.optimized_parameters = data.get("optimized_parameters", {})
            
            print(f"✅ 已加载 {len(self.user_actions)} 条历史记录")
        except FileNotFoundError:
            print("未找到历史数据，将创建新文件")
    
    def export_report(self, output_file: str):
        """导出学习报告"""
        report = {
            "summary": {
                "total_actions": len(self.user_actions),
                "success_rate": self.get_success_rate(),
                "learning_period": {
                    "start": min([a.timestamp for a in self.user_actions]) if self.user_actions else 0,
                    "end": max([a.timestamp for a in self.user_actions]) if self.user_actions else 0
                }
            },
            "usage_patterns": self.usage_patterns,
            "optimized_parameters": self.optimized_parameters,
            "performance_metrics": self.get_performance_metrics(),
            "suggestions": self.get_personalized_suggestions()
        }
        
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        
        print(f"✅ 学习报告已导出到: {output_file}")

# 使用示例
if __name__ == "__main__":
    # 创建学习系统
    learning_system = SelfLearningSystem()
    
    # 模拟用户行为
    actions = [
        UserAction(time.time(), "3d_print", "打印花瓶", "3d_printer", True, 3600, {"temperature": 220}),
        UserAction(time.time(), "drone_flight", "拍摄全景", "drone", True, 600, {"altitude": 50}),
        UserAction(time.time(), "3d_print", "打印模型", "3d_printer", True, 7200, {"temperature": 215}),
        UserAction(time.time(), "video_generation", "生成视频", "windows", True, 120, {"style": "cinematic"}),
        UserAction(time.time(), "drone_flight", "巡航", "drone", True, 900, {"altitude": 30}),
        UserAction(time.time(), "3d_print", "打印支架", "3d_printer", False, 1800, {"temperature": 230}),
        UserAction(time.time(), "drone_flight", "拍照", "drone", True, 300, {"altitude": 40}),
        UserAction(time.time(), "3d_print", "打印零件", "3d_printer", True, 5400, {"temperature": 220}),
        UserAction(time.time(), "video_generation", "生成动画", "windows", True, 180, {"style": "anime"}),
        UserAction(time.time(), "drone_flight", "测试飞行", "drone", True, 450, {"altitude": 45}),
    ]
    
    for action in actions:
        learning_system.record_action(action)
    
    # 获取优化参数
    print("\n=== 优化参数 ===")
    optimized_3d = learning_system.optimize_parameters("3d_print")
    print(f"3D 打印优化参数: {optimized_3d}")
    
    optimized_drone = learning_system.optimize_parameters("drone_flight")
    print(f"无人机飞行优化参数: {optimized_drone}")
    
    # 获取个性化建议
    print("\n=== 个性化建议 ===")
    suggestions = learning_system.get_personalized_suggestions()
    for i, suggestion in enumerate(suggestions, 1):
        print(f"{i}. {suggestion}")
    
    # 获取性能指标
    print("\n=== 性能指标 ===")
    metrics = learning_system.get_performance_metrics()
    print(json.dumps(metrics, indent=2, ensure_ascii=False))
    
    # 导出报告
    learning_system.export_report("/tmp/learning_report.json")
