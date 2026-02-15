"""
节点工厂模块 - Node Factory
用于动态创建、注册和管理 UFO Galaxy 节点
"""

import os
import json
import re
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class NodeTemplate:
    """节点模板数据类"""
    name: str
    description: str
    category: str
    inputs: Dict[str, Any] = field(default_factory=dict)
    outputs: Dict[str, Any] = field(default_factory=dict)
    parameters: Dict[str, Any] = field(default_factory=dict)
    code_template: str = ""
    
    
class NodeFactory:
    """
    节点工厂类
    负责动态生成节点、管理节点模板和注册节点
    """
    
    def __init__(self, templates_dir: str = "templates"):
        self.templates_dir = templates_dir
        self.registered_nodes: Dict[str, Dict] = {}
        self.templates: Dict[str, NodeTemplate] = {}
        self.node_counter = 0
        
        # 确保模板目录存在
        os.makedirs(templates_dir, exist_ok=True)
        
        # 加载内置模板
        self._load_builtin_templates()
    
    def _load_builtin_templates(self):
        """加载内置节点模板"""
        
        # 基础处理节点模板
        self.templates["base_processor"] = NodeTemplate(
            name="BaseProcessor",
            description="基础处理节点",
            category="processor",
            inputs={"input": {"type": "any", "description": "输入数据"}},
            outputs={"output": {"type": "any", "description": "输出数据"}},
            parameters={"enabled": {"type": "bool", "default": True}},
            code_template="""
class {class_name}(BaseNode):
    \"\"\"{description}\"\"\"
    
    def __init__(self):
        super().__init__()
        self.node_id = "{node_id}"
        self.node_type = "{node_type}"
        {init_code}
    
    def process(self, input_data):
        \"\"\"处理逻辑\"\"\"
        {process_code}
        return output_data
"""
        )
        
        # 输入节点模板
        self.templates["input_node"] = NodeTemplate(
            name="InputNode",
            description="数据输入节点",
            category="input",
            inputs={},
            outputs={"data": {"type": "any", "description": "输出数据"}},
            parameters={
                "source": {"type": "str", "default": "default"},
                "auto_trigger": {"type": "bool", "default": False}
            },
            code_template="""
class {class_name}(InputNode):
    \"\"\"{description}\"\"\"
    
    def __init__(self):
        super().__init__()
        self.node_id = "{node_id}"
        self.node_type = "input"
        self.source = "{source}"
        {init_code}
    
    def read(self):
        \"\"\"读取输入数据\"\"\"
        {read_code}
        return data
"""
        )
        
        # 输出节点模板
        self.templates["output_node"] = NodeTemplate(
            name="OutputNode",
            description="数据输出节点",
            category="output",
            inputs={"data": {"type": "any", "description": "输入数据"}},
            outputs={},
            parameters={
                "destination": {"type": "str", "default": "default"},
                "format": {"type": "str", "default": "json"}
            },
            code_template="""
class {class_name}(OutputNode):
    \"\"\"{description}\"\"\"
    
    def __init__(self):
        super().__init__()
        self.node_id = "{node_id}"
        self.node_type = "output"
        self.destination = "{destination}"
        {init_code}
    
    def write(self, data):
        \"\"\"写入输出数据\"\"\"
        {write_code}
        return success
"""
        )
        
        # AI 处理节点模板
        self.templates["ai_processor"] = NodeTemplate(
            name="AIProcessor",
            description="AI 处理节点",
            category="ai",
            inputs={"prompt": {"type": "str", "description": "输入提示"}},
            outputs={"response": {"type": "str", "description": "AI响应"}},
            parameters={
                "model": {"type": "str", "default": "gpt-4"},
                "temperature": {"type": "float", "default": 0.7},
                "max_tokens": {"type": "int", "default": 1024}
            },
            code_template="""
class {class_name}(AINode):
    \"\"\"{description}\"\"\"
    
    def __init__(self):
        super().__init__()
        self.node_id = "{node_id}"
        self.node_type = "ai"
        self.model = "{model}"
        self.temperature = {temperature}
        {init_code}
    
    async def generate(self, prompt):
        \"\"\"AI生成逻辑\"\"\"
        {ai_code}
        return response
"""
        )
        
        # 条件节点模板
        self.templates["condition_node"] = NodeTemplate(
            name="ConditionNode",
            description="条件判断节点",
            category="logic",
            inputs={"value": {"type": "any", "description": "输入值"}},
            outputs={
                "true_branch": {"type": "any", "description": "条件为真"},
                "false_branch": {"type": "any", "description": "条件为假"}
            },
            parameters={
                "condition": {"type": "str", "default": "value > 0"},
                "operator": {"type": "str", "default": "greater_than"}
            },
            code_template="""
class {class_name}(ConditionNode):
    \"\"\"{description}\"\"\"
    
    def __init__(self):
        super().__init__()
        self.node_id = "{node_id}"
        self.node_type = "condition"
        self.condition = "{condition}"
        {init_code}
    
    def evaluate(self, value):
        \"\"\"条件评估逻辑\"\"\"
        {condition_code}
        return result
"""
        )
    
    def create_node(self, template_name: str, node_config: Dict[str, Any]) -> str:
        """
        根据模板创建新节点
        
        Args:
            template_name: 模板名称
            node_config: 节点配置
            
        Returns:
            生成的节点代码
        """
        if template_name not in self.templates:
            raise ValueError(f"模板 '{template_name}' 不存在")
        
        template = self.templates[template_name]
        self.node_counter += 1
        
        # 生成节点ID
        node_id = f"{template.category}_{self.node_counter:04d}"
        
        # 构建模板变量
        template_vars = {
            "class_name": node_config.get("class_name", f"{template.name}_{self.node_counter}"),
            "description": node_config.get("description", template.description),
            "node_id": node_id,
            "node_type": template.category,
            "init_code": self._generate_init_code(template, node_config),
            "process_code": node_config.get("process_code", "# TODO: 实现处理逻辑\n        output_data = input_data"),
            "read_code": node_config.get("read_code", "# TODO: 实现读取逻辑\n        data = None"),
            "write_code": node_config.get("write_code", "# TODO: 实现写入逻辑\n        success = True"),
            "ai_code": node_config.get("ai_code", "# TODO: 实现AI调用\n        response = await self.call_model(prompt)"),
            "condition_code": node_config.get("condition_code", "# TODO: 实现条件判断\n        result = eval(self.condition)"),
        }
        
        # 添加参数值
        for param_name, param_config in template.parameters.items():
            template_vars[param_name] = node_config.get(param_name, param_config.get("default", ""))
        
        # 渲染模板
        node_code = template.code_template.format(**template_vars)
        
        # 注册节点
        self.register_node(node_id, {
            "template": template_name,
            "class_name": template_vars["class_name"],
            "config": node_config,
            "code": node_code,
            "created_at": datetime.now().isoformat()
        })
        
        return node_code
    
    def _generate_init_code(self, template: NodeTemplate, node_config: Dict) -> str:
        """生成初始化代码"""
        init_lines = []
        
        # 添加参数初始化
        for param_name, param_config in template.parameters.items():
            value = node_config.get(param_name, param_config.get("default", ""))
            if isinstance(value, str):
                init_lines.append(f"        self.{param_name} = \"{value}\"")
            else:
                init_lines.append(f"        self.{param_name} = {value}")
        
        return "\n".join(init_lines) if init_lines else "        pass"
    
    def register_node(self, node_id: str, node_info: Dict):
        """
        注册节点
        
        Args:
            node_id: 节点唯一标识
            node_info: 节点信息
        """
        self.registered_nodes[node_id] = node_info
        print(f"[NodeFactory] 节点已注册: {node_id}")
    
    def unregister_node(self, node_id: str) -> bool:
        """
        注销节点
        
        Args:
            node_id: 节点唯一标识
            
        Returns:
            是否成功注销
        """
        if node_id in self.registered_nodes:
            del self.registered_nodes[node_id]
            print(f"[NodeFactory] 节点已注销: {node_id}")
            return True
        return False
    
    def get_node(self, node_id: str) -> Optional[Dict]:
        """
        获取节点信息
        
        Args:
            node_id: 节点唯一标识
            
        Returns:
            节点信息
        """
        return self.registered_nodes.get(node_id)
    
    def list_nodes(self, category: Optional[str] = None) -> List[Dict]:
        """
        列出所有已注册节点
        
        Args:
            category: 按类别过滤
            
        Returns:
            节点列表
        """
        nodes = []
        for node_id, node_info in self.registered_nodes.items():
            if category is None or node_info.get("template") == category:
                nodes.append({
                    "node_id": node_id,
                    **node_info
                })
        return nodes
    
    def create_custom_template(self, template_name: str, template_config: Dict) -> NodeTemplate:
        """
        创建自定义模板
        
        Args:
            template_name: 模板名称
            template_config: 模板配置
            
        Returns:
            创建的模板
        """
        template = NodeTemplate(
            name=template_config.get("name", template_name),
            description=template_config.get("description", ""),
            category=template_config.get("category", "custom"),
            inputs=template_config.get("inputs", {}),
            outputs=template_config.get("outputs", {}),
            parameters=template_config.get("parameters", {}),
            code_template=template_config.get("code_template", "")
        )
        
        self.templates[template_name] = template
        
        # 保存到文件
        self._save_template(template_name, template)
        
        return template
    
    def _save_template(self, template_name: str, template: NodeTemplate):
        """保存模板到文件"""
        template_path = os.path.join(self.templates_dir, f"{template_name}.json")
        with open(template_path, 'w', encoding='utf-8') as f:
            json.dump({
                "name": template.name,
                "description": template.description,
                "category": template.category,
                "inputs": template.inputs,
                "outputs": template.outputs,
                "parameters": template.parameters,
                "code_template": template.code_template
            }, f, indent=2, ensure_ascii=False)
    
    def load_template(self, template_name: str) -> Optional[NodeTemplate]:
        """
        从文件加载模板
        
        Args:
            template_name: 模板名称
            
        Returns:
            加载的模板
        """
        template_path = os.path.join(self.templates_dir, f"{template_name}.json")
        if not os.path.exists(template_path):
            return None
        
        with open(template_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        template = NodeTemplate(**data)
        self.templates[template_name] = template
        return template
    
    def list_templates(self) -> List[Dict]:
        """
        列出所有可用模板
        
        Returns:
            模板列表
        """
        return [
            {
                "name": name,
                "description": template.description,
                "category": template.category,
                "inputs": list(template.inputs.keys()),
                "outputs": list(template.outputs.keys()),
                "parameters": list(template.parameters.keys())
            }
            for name, template in self.templates.items()
        ]
    
    def generate_node_file(self, node_id: str, output_dir: str = "generated_nodes") -> str:
        """
        生成节点文件
        
        Args:
            node_id: 节点ID
            output_dir: 输出目录
            
        Returns:
            生成的文件路径
        """
        node_info = self.get_node(node_id)
        if not node_info:
            raise ValueError(f"节点 '{node_id}' 不存在")
        
        os.makedirs(output_dir, exist_ok=True)
        
        class_name = node_info["class_name"]
        file_path = os.path.join(output_dir, f"{class_name.lower()}.py")
        
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(node_info["code"])
        
        return file_path
    
    def clone_node(self, node_id: str, new_name: Optional[str] = None) -> str:
        """
        克隆现有节点
        
        Args:
            node_id: 原节点ID
            new_name: 新节点名称
            
        Returns:
            新节点代码
        """
        node_info = self.get_node(node_id)
        if not node_info:
            raise ValueError(f"节点 '{node_id}' 不存在")
        
        template_name = node_info["template"]
        config = node_info["config"].copy()
        
        if new_name:
            config["class_name"] = new_name
        
        return self.create_node(template_name, config)
    
    def validate_node_code(self, code: str) -> Dict[str, Any]:
        """
        验证节点代码
        
        Args:
            code: 节点代码
            
        Returns:
            验证结果
        """
        result = {
            "valid": True,
            "errors": [],
            "warnings": []
        }
        
        # 检查类定义
        if not re.search(r'class\s+\w+\s*\(', code):
            result["valid"] = False
            result["errors"].append("缺少类定义")
        
        # 检查 __init__ 方法
        if "def __init__" not in code:
            result["warnings"].append("缺少 __init__ 方法")
        
        # 检查 node_id
        if "node_id" not in code:
            result["warnings"].append("缺少 node_id 属性")
        
        # 尝试语法检查
        try:
            compile(code, '<string>', 'exec')
        except SyntaxError as e:
            result["valid"] = False
            result["errors"].append(f"语法错误: {e}")
        
        return result


# 全局节点工厂实例
_node_factory: Optional[NodeFactory] = None


def get_node_factory() -> NodeFactory:
    """获取全局节点工厂实例"""
    global _node_factory
    if _node_factory is None:
        _node_factory = NodeFactory()
    return _node_factory


def reset_node_factory():
    """重置全局节点工厂实例"""
    global _node_factory
    _node_factory = None


# 便捷函数
def create_node(template_name: str, config: Dict[str, Any]) -> str:
    """便捷函数：创建节点"""
    return get_node_factory().create_node(template_name, config)


def register_node(node_id: str, node_info: Dict):
    """便捷函数：注册节点"""
    return get_node_factory().register_node(node_id, node_info)


def unregister_node(node_id: str) -> bool:
    """便捷函数：注销节点"""
    return get_node_factory().unregister_node(node_id)


def list_nodes(category: Optional[str] = None) -> List[Dict]:
    """便捷函数：列出节点"""
    return get_node_factory().list_nodes(category)


def list_templates() -> List[Dict]:
    """便捷函数：列出模板"""
    return get_node_factory().list_templates()


if __name__ == "__main__":
    # 测试代码
    factory = NodeFactory()
    
    print("=" * 50)
    print("可用模板:")
    print("=" * 50)
    for template in factory.list_templates():
        print(f"  - {template['name']} ({template['category']})")
        print(f"    描述: {template['description']}")
    
    print("\n" + "=" * 50)
    print("创建示例节点:")
    print("=" * 50)
    
    # 创建一个处理器节点
    processor_code = factory.create_node("base_processor", {
        "class_name": "MyProcessor",
        "description": "我的自定义处理器",
        "process_code": "output_data = input_data.upper() if isinstance(input_data, str) else input_data"
    })
    print(processor_code[:500] + "...")
    
    print("\n" + "=" * 50)
    print("已注册节点:")
    print("=" * 50)
    for node in factory.list_nodes():
        print(f"  - {node['node_id']}: {node['class_name']}")
