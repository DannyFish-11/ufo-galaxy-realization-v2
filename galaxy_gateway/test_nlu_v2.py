"""
UFO³ Galaxy - NLU v2.0 测试脚本

功能：
1. 测试各种用户输入场景
2. 评估 NLU 准确率
3. 对比规则引擎和 LLM 的性能
4. 生成测试报告

作者：Manus AI
日期：2026-01-22
版本：1.0
"""

import asyncio
import json
import time
from datetime import datetime
from typing import List, Dict, Any

from enhanced_nlu_v2 import (
    DeviceRegistry, EnhancedNLUEngineV2, LLMClient
)

# ============================================================================
# 测试用例
# ============================================================================

TEST_CASES = [
    # 基础测试 - 单设备单应用
    {
        "category": "基础操作",
        "input": "在手机A上打开微信",
        "expected": {
            "devices": ["phone_a"],
            "actions": ["open"],
            "targets": ["wechat"]
        }
    },
    {
        "category": "基础操作",
        "input": "在平板上播放音乐",
        "expected": {
            "devices": ["tablet"],
            "actions": ["play"],
            "targets": ["music"]
        }
    },
    {
        "category": "基础操作",
        "input": "在电脑上打开Chrome",
        "expected": {
            "devices": ["pc"],
            "actions": ["open"],
            "targets": ["chrome"]
        }
    },
    
    # 多设备并行操作
    {
        "category": "多设备并行",
        "input": "在手机B上打开微信，在平板上播放音乐",
        "expected": {
            "devices": ["phone_b", "tablet"],
            "actions": ["open", "play"],
            "targets": ["wechat", "music"]
        }
    },
    {
        "category": "多设备并行",
        "input": "在手机A上打开微信，在手机B上打开QQ，在平板上播放YouTube",
        "expected": {
            "devices": ["phone_a", "phone_b", "tablet"],
            "actions": ["open", "open", "play"],
            "targets": ["wechat", "qq", "youtube"]
        }
    },
    
    # 复杂任务 - 多步骤
    {
        "category": "复杂任务",
        "input": "把手机A上的照片发到电脑",
        "expected": {
            "devices": ["phone_a", "pc"],
            "task_count": 2,  # 读取 + 写入
            "has_dependencies": True
        }
    },
    {
        "category": "复杂任务",
        "input": "把手机上的照片发到电脑，然后用PS打开",
        "expected": {
            "devices": ["phone_a", "pc"],
            "task_count": 3,  # 读取 + 写入 + 打开
            "has_dependencies": True
        }
    },
    {
        "category": "复杂任务",
        "input": "在电脑上打开Chrome并搜索Python教程",
        "expected": {
            "devices": ["pc"],
            "task_count": 2,  # 打开 + 搜索
            "has_dependencies": True
        }
    },
    
    # 设备别名测试
    {
        "category": "设备别名",
        "input": "在我的手机上打开微信",
        "expected": {
            "devices": ["phone_a"],  # "我的手机" 是 phone_a 的别名
            "actions": ["open"],
            "targets": ["wechat"]
        }
    },
    {
        "category": "设备别名",
        "input": "在工作手机上打开QQ",
        "expected": {
            "devices": ["phone_b"],  # "工作手机" 是 phone_b 的别名
            "actions": ["open"],
            "targets": ["qq"]
        }
    },
    
    # 模糊指令（需要澄清）
    {
        "category": "模糊指令",
        "input": "打开微信",
        "expected": {
            "need_clarification": True  # 没有指定设备
        }
    },
    {
        "category": "模糊指令",
        "input": "在手机上打开那个聊天软件",
        "expected": {
            "need_clarification": True  # "那个聊天软件" 不明确
        }
    },
    
    # 自然语言多样性
    {
        "category": "自然语言多样性",
        "input": "帮我在手机B上启动微信",
        "expected": {
            "devices": ["phone_b"],
            "actions": ["open"],
            "targets": ["wechat"]
        }
    },
    {
        "category": "自然语言多样性",
        "input": "用平板播放一首歌",
        "expected": {
            "devices": ["tablet"],
            "actions": ["play"],
            "targets": ["music"]
        }
    },
    {
        "category": "自然语言多样性",
        "input": "电脑上的浏览器打开一下",
        "expected": {
            "devices": ["pc"],
            "actions": ["open"],
            "targets": ["browser"]
        }
    },
]

# ============================================================================
# 测试执行器
# ============================================================================

class NLUTester:
    """NLU 测试器"""
    
    def __init__(self):
        self.device_registry = DeviceRegistry()
        self.llm_client = LLMClient(provider="ollama")
        
        # 创建两个 NLU 引擎：规则引擎和 LLM 引擎
        self.rule_engine = EnhancedNLUEngineV2(
            device_registry=self.device_registry,
            llm_client=self.llm_client,
            use_llm=False  # 只用规则
        )
        
        self.llm_engine = EnhancedNLUEngineV2(
            device_registry=self.device_registry,
            llm_client=self.llm_client,
            use_llm=True  # 使用 LLM
        )
    
    async def run_tests(self) -> Dict[str, Any]:
        """运行所有测试"""
        print("="*80)
        print("UFO³ Galaxy - NLU v2.0 测试")
        print("="*80)
        print(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"测试用例数: {len(TEST_CASES)}")
        print("="*80)
        
        results = {
            "rule_engine": [],
            "llm_engine": [],
            "summary": {
                "rule_engine": {"total": 0, "passed": 0, "failed": 0},
                "llm_engine": {"total": 0, "passed": 0, "failed": 0}
            }
        }
        
        for i, test_case in enumerate(TEST_CASES, 1):
            print(f"\n{'='*80}")
            print(f"测试 {i}/{len(TEST_CASES)}: {test_case['category']}")
            print(f"{'='*80}")
            print(f"输入: {test_case['input']}")
            
            # 测试规则引擎
            print(f"\n[规则引擎]")
            rule_result = await self._test_single(
                self.rule_engine,
                test_case,
                "rule"
            )
            results["rule_engine"].append(rule_result)
            results["summary"]["rule_engine"]["total"] += 1
            if rule_result["passed"]:
                results["summary"]["rule_engine"]["passed"] += 1
            else:
                results["summary"]["rule_engine"]["failed"] += 1
            
            # 测试 LLM 引擎
            print(f"\n[LLM 引擎]")
            llm_result = await self._test_single(
                self.llm_engine,
                test_case,
                "llm"
            )
            results["llm_engine"].append(llm_result)
            results["summary"]["llm_engine"]["total"] += 1
            if llm_result["passed"]:
                results["summary"]["llm_engine"]["passed"] += 1
            else:
                results["summary"]["llm_engine"]["failed"] += 1
        
        return results
    
    async def _test_single(
        self,
        engine: EnhancedNLUEngineV2,
        test_case: Dict[str, Any],
        engine_type: str
    ) -> Dict[str, Any]:
        """测试单个用例"""
        start_time = time.time()
        
        try:
            # 执行 NLU
            nlu_result = await engine.understand(test_case["input"])
            
            processing_time = time.time() - start_time
            
            # 验证结果
            passed, errors = self._verify_result(nlu_result, test_case["expected"])
            
            # 打印结果
            print(f"  置信度: {nlu_result.confidence:.2f}")
            print(f"  处理时间: {processing_time:.3f}秒")
            print(f"  任务数: {len(nlu_result.tasks)}")
            
            if nlu_result.tasks:
                for task in nlu_result.tasks:
                    print(f"    - {task.task_id}: {task.action} {task.target} on {task.device_id}")
            
            if nlu_result.clarifications:
                print(f"  需要澄清: {nlu_result.clarifications}")
            
            print(f"  结果: {'✅ 通过' if passed else '❌ 失败'}")
            if not passed:
                for error in errors:
                    print(f"    - {error}")
            
            return {
                "test_case": test_case,
                "engine_type": engine_type,
                "passed": passed,
                "errors": errors,
                "confidence": nlu_result.confidence,
                "processing_time": processing_time,
                "task_count": len(nlu_result.tasks),
                "clarifications": nlu_result.clarifications
            }
        
        except Exception as e:
            processing_time = time.time() - start_time
            print(f"  ❌ 异常: {e}")
            
            return {
                "test_case": test_case,
                "engine_type": engine_type,
                "passed": False,
                "errors": [str(e)],
                "confidence": 0.0,
                "processing_time": processing_time,
                "task_count": 0,
                "clarifications": []
            }
    
    def _verify_result(self, nlu_result, expected: Dict[str, Any]) -> tuple[bool, List[str]]:
        """验证 NLU 结果"""
        errors = []
        
        # 检查是否需要澄清
        if expected.get("need_clarification"):
            if not nlu_result.clarifications:
                errors.append("期望需要澄清，但没有提出澄清问题")
            return len(errors) == 0, errors
        
        # 检查设备
        if "devices" in expected:
            actual_devices = [task.device_id for task in nlu_result.tasks]
            expected_devices = expected["devices"]
            
            if set(actual_devices) != set(expected_devices):
                errors.append(f"设备不匹配: 期望 {expected_devices}, 实际 {actual_devices}")
        
        # 检查动作
        if "actions" in expected:
            actual_actions = [task.action for task in nlu_result.tasks]
            expected_actions = expected["actions"]
            
            # 允许部分匹配（因为可能有多种表达方式）
            for expected_action in expected_actions:
                if expected_action not in actual_actions:
                    errors.append(f"缺少动作: {expected_action}")
        
        # 检查目标
        if "targets" in expected:
            actual_targets = [task.target for task in nlu_result.tasks if task.target]
            expected_targets = expected["targets"]
            
            for expected_target in expected_targets:
                if expected_target not in actual_targets:
                    errors.append(f"缺少目标: {expected_target}")
        
        # 检查任务数量
        if "task_count" in expected:
            if len(nlu_result.tasks) != expected["task_count"]:
                errors.append(f"任务数量不匹配: 期望 {expected['task_count']}, 实际 {len(nlu_result.tasks)}")
        
        # 检查依赖关系
        if expected.get("has_dependencies"):
            has_deps = any(task.depends_on for task in nlu_result.tasks)
            if not has_deps:
                errors.append("期望有依赖关系，但没有找到")
        
        return len(errors) == 0, errors
    
    def generate_report(self, results: Dict[str, Any]) -> str:
        """生成测试报告"""
        report = []
        
        report.append("="*80)
        report.append("UFO³ Galaxy - NLU v2.0 测试报告")
        report.append("="*80)
        report.append(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append("")
        
        # 汇总
        report.append("测试汇总:")
        report.append("-"*80)
        
        for engine_type in ["rule_engine", "llm_engine"]:
            summary = results["summary"][engine_type]
            success_rate = summary["passed"] / summary["total"] * 100 if summary["total"] > 0 else 0
            
            engine_name = "规则引擎" if engine_type == "rule_engine" else "LLM 引擎"
            report.append(f"\n{engine_name}:")
            report.append(f"  总测试数: {summary['total']}")
            report.append(f"  通过: {summary['passed']}")
            report.append(f"  失败: {summary['failed']}")
            report.append(f"  成功率: {success_rate:.1f}%")
        
        # 详细结果
        report.append("\n" + "="*80)
        report.append("详细测试结果:")
        report.append("="*80)
        
        for i, (rule_result, llm_result) in enumerate(zip(results["rule_engine"], results["llm_engine"]), 1):
            test_case = rule_result["test_case"]
            
            report.append(f"\n测试 {i}: {test_case['category']}")
            report.append(f"输入: {test_case['input']}")
            report.append("-"*80)
            
            # 规则引擎结果
            report.append(f"规则引擎: {'✅ 通过' if rule_result['passed'] else '❌ 失败'}")
            report.append(f"  置信度: {rule_result['confidence']:.2f}")
            report.append(f"  处理时间: {rule_result['processing_time']:.3f}秒")
            if rule_result['errors']:
                report.append(f"  错误: {', '.join(rule_result['errors'])}")
            
            # LLM 引擎结果
            report.append(f"LLM 引擎: {'✅ 通过' if llm_result['passed'] else '❌ 失败'}")
            report.append(f"  置信度: {llm_result['confidence']:.2f}")
            report.append(f"  处理时间: {llm_result['processing_time']:.3f}秒")
            if llm_result['errors']:
                report.append(f"  错误: {', '.join(llm_result['errors'])}")
        
        return "\n".join(report)

# ============================================================================
# 主函数
# ============================================================================

async def main():
    """主函数"""
    tester = NLUTester()
    
    # 运行测试
    results = await tester.run_tests()
    
    # 生成报告
    print("\n" + "="*80)
    print("生成测试报告...")
    print("="*80)
    
    report = tester.generate_report(results)
    print("\n" + report)
    
    # 保存报告
    report_file = f"nlu_test_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(report)
    
    print(f"\n报告已保存到: {report_file}")
    
    # 保存 JSON 结果
    json_file = f"nlu_test_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    
    print(f"详细结果已保存到: {json_file}")

if __name__ == "__main__":
    asyncio.run(main())
