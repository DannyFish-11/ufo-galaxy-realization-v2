"""
UFO Galaxy - 安全表达式求值模块
================================

提供安全的表达式求值功能，替代危险的 eval()
"""
import ast
import operator
from typing import Any, Dict, Optional, Union

# 支持的安全操作符
SAFE_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.LShift: operator.lshift,
    ast.RShift: operator.rshift,
    ast.BitOr: operator.or_,
    ast.BitXor: operator.xor,
    ast.BitAnd: operator.and_,
    ast.Invert: operator.invert,
    ast.Not: operator.not_,
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.Is: operator.is_,
    ast.IsNot: operator.is_not,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
    ast.And: lambda a, b: a and b,
    ast.Or: lambda a, b: a or b,
}

# 支持的安全函数
SAFE_FUNCTIONS = {
    'abs': abs,
    'all': all,
    'any': any,
    'bool': bool,
    'dict': dict,
    'float': float,
    'int': int,
    'len': len,
    'list': list,
    'max': max,
    'min': min,
    'round': round,
    'set': set,
    'sorted': sorted,
    'str': str,
    'sum': sum,
    'tuple': tuple,
    'type': type,
    'isinstance': isinstance,
    'hasattr': hasattr,
    'getattr': getattr,
    'range': range,
    'enumerate': enumerate,
    'zip': zip,
    'map': map,
    'filter': filter,
}


class SafeEvalError(Exception):
    """安全表达式求值错误"""
    pass


class SafeEval:
    """
    安全的表达式求值器
    
    使用方法:
        evaluator = SafeEval()
        result = evaluator.eval("1 + 2 * 3")  # 返回 7
        result = evaluator.eval("x + y", {"x": 10, "y": 20})  # 返回 30
    """
    
    def __init__(self, allowed_names: Dict[str, Any] = None, allowed_functions: Dict[str, Any] = None):
        """
        初始化安全求值器
        
        Args:
            allowed_names: 允许的变量名和值
            allowed_functions: 允许的函数名和函数
        """
        self.allowed_names = allowed_names or {}
        self.allowed_functions = {**SAFE_FUNCTIONS, **(allowed_functions or {})}
    
    def eval(self, expression: str, context: Dict[str, Any] = None) -> Any:
        """
        安全地求值表达式
        
        Args:
            expression: 要求值的表达式字符串
            context: 额外的上下文变量
            
        Returns:
            表达式的结果
            
        Raises:
            SafeEvalError: 如果表达式包含不允许的操作
        """
        if not expression or not isinstance(expression, str):
            return None
        
        try:
            # 解析表达式
            tree = ast.parse(expression, mode='eval')
        except SyntaxError as e:
            raise SafeEvalError(f"语法错误: {e}")
        
        # 合并上下文
        full_context = {**self.allowed_names, **(context or {})}
        
        # 求值
        return self._eval_node(tree.body, full_context)
    
    def _eval_node(self, node: ast.AST, context: Dict[str, Any]) -> Any:
        """递归求值 AST 节点"""
        
        # 字面量
        if isinstance(node, ast.Constant):
            return node.value
        
        if isinstance(node, ast.Num):  # Python < 3.8 兼容
            return node.n
        
        if isinstance(node, ast.Str):  # Python < 3.8 兼容
            return node.s
        
        # 名称引用
        if isinstance(node, ast.Name):
            name = node.id
            if name in context:
                return context[name]
            if name in self.allowed_functions:
                return self.allowed_functions[name]
            if name in ('True', 'False', 'None'):
                return eval(name)  # 这些是安全的内置常量
            raise SafeEvalError(f"未定义的变量: {name}")
        
        # 二元操作
        if isinstance(node, ast.BinOp):
            left = self._eval_node(node.left, context)
            right = self._eval_node(node.right, context)
            op_type = type(node.op)
            if op_type in SAFE_OPERATORS:
                return SAFE_OPERATORS[op_type](left, right)
            raise SafeEvalError(f"不支持的操作符: {op_type.__name__}")
        
        # 一元操作
        if isinstance(node, ast.UnaryOp):
            operand = self._eval_node(node.operand, context)
            op_type = type(node.op)
            if op_type in SAFE_OPERATORS:
                return SAFE_OPERATORS[op_type](operand)
            raise SafeEvalError(f"不支持的一元操作符: {op_type.__name__}")
        
        # 比较操作
        if isinstance(node, ast.Compare):
            left = self._eval_node(node.left, context)
            for op, comparator in zip(node.ops, node.comparators):
                right = self._eval_node(comparator, context)
                op_type = type(op)
                if op_type in SAFE_OPERATORS:
                    if not SAFE_OPERATORS[op_type](left, right):
                        return False
                else:
                    raise SafeEvalError(f"不支持的比较操作符: {op_type.__name__}")
                left = right
            return True
        
        # 布尔操作
        if isinstance(node, ast.BoolOp):
            values = [self._eval_node(v, context) for v in node.values]
            if isinstance(node.op, ast.And):
                return all(values)
            if isinstance(node.op, ast.Or):
                return any(values)
            raise SafeEvalError(f"不支持的布尔操作符")
        
        # 条件表达式
        if isinstance(node, ast.IfExp):
            test = self._eval_node(node.test, context)
            if test:
                return self._eval_node(node.body, context)
            return self._eval_node(node.orelse, context)
        
        # 函数调用
        if isinstance(node, ast.Call):
            func = self._eval_node(node.func, context)
            args = [self._eval_node(arg, context) for arg in node.args]
            kwargs = {kw.arg: self._eval_node(kw.value, context) for kw in node.keywords if kw.arg}
            
            if callable(func):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    raise SafeEvalError(f"函数调用错误: {e}")
            raise SafeEvalError(f"不可调用的对象: {func}")
        
        # 属性访问
        if isinstance(node, ast.Attribute):
            obj = self._eval_node(node.value, context)
            attr = node.attr
            if hasattr(obj, attr):
                return getattr(obj, attr)
            raise SafeEvalError(f"对象没有属性: {attr}")
        
        # 下标访问
        if isinstance(node, ast.Subscript):
            value = self._eval_node(node.value, context)
            slice_val = self._eval_node(node.slice, context)
            try:
                return value[slice_val]
            except (KeyError, IndexError, TypeError) as e:
                raise SafeEvalError(f"下标访问错误: {e}")
        
        # 列表
        if isinstance(node, ast.List):
            return [self._eval_node(el, context) for el in node.elts]
        
        # 元组
        if isinstance(node, ast.Tuple):
            return tuple(self._eval_node(el, context) for el in node.elts)
        
        # 字典
        if isinstance(node, ast.Dict):
            keys = [self._eval_node(k, context) for k in node.keys]
            values = [self._eval_node(v, context) for v in node.values]
            return dict(zip(keys, values))
        
        # 集合
        if isinstance(node, ast.Set):
            return {self._eval_node(el, context) for el in node.elts}
        
        # 切片
        if isinstance(node, ast.Slice):
            lower = self._eval_node(node.lower, context) if node.lower else None
            upper = self._eval_node(node.upper, context) if node.upper else None
            step = self._eval_node(node.step, context) if node.step else None
            return slice(lower, upper, step)
        
        # 不支持的节点类型
        raise SafeEvalError(f"不支持的表达式类型: {type(node).__name__}")


def safe_eval(expression: str, context: Dict[str, Any] = None, allowed_names: Dict[str, Any] = None) -> Any:
    """
    安全表达式求值的便捷函数
    
    Args:
        expression: 要求值的表达式
        context: 上下文变量
        allowed_names: 允许的变量名
        
    Returns:
        表达式的结果
    """
    evaluator = SafeEval(allowed_names)
    return evaluator.eval(expression, context)


def safe_literal_eval(expression: str) -> Any:
    """
    安全的字面量求值（仅支持字面量，不支持表达式）
    
    这是 ast.literal_eval 的别名，用于解析字符串形式的 Python 字面量
    
    Args:
        expression: 字面量字符串，如 "[1, 2, 3]" 或 "{'key': 'value'}"
        
    Returns:
        解析后的 Python 对象
    """
    return ast.literal_eval(expression)


# 导出
__all__ = ['SafeEval', 'SafeEvalError', 'safe_eval', 'safe_literal_eval']
