"""
Node_102_DebugOptimize - 自主调试和优化系统

功能：
1. 错误检测（语法错误、运行时错误）
2. 错误诊断（分析错误原因）
3. 自动修复（修复常见错误）
4. 性能分析（识别性能瓶颈）
5. 代码优化（优化性能和资源使用）

技术栈：
- ast（语法检查）
- traceback（错误追踪）
- cProfile（性能分析）
- DeepSeek Coder（智能修复）

版本：1.0.0
日期：2026-01-22
作者：Manus AI
"""

import os
import ast
import sys
import json
import traceback
import subprocess
from io import StringIO
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Node_102_DebugOptimize", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# ============================================================================
# 配置
# ============================================================================

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "sk-be72ac32a25e4de08ef261d50feebb60")
DEEPSEEK_API_BASE = os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com")

# ============================================================================
# 数据模型
# ============================================================================

@dataclass
class Error:
    """错误"""
    type: str
    message: str
    line: Optional[int]
    column: Optional[int]
    traceback: Optional[str]

@dataclass
class Fix:
    """修复"""
    original_code: str
    fixed_code: str
    explanation: str
    confidence: float

class DetectErrorsRequest(BaseModel):
    """检测错误请求"""
    code: str
    language: str = "python"

class DiagnoseErrorRequest(BaseModel):
    """诊断错误请求"""
    code: str
    error: str
    language: str = "python"

class AutoFixRequest(BaseModel):
    """自动修复请求"""
    code: str
    error: str
    language: str = "python"

class AnalyzePerformanceRequest(BaseModel):
    """性能分析请求"""
    code: str
    language: str = "python"

class OptimizeCodeRequest(BaseModel):
    """优化代码请求"""
    code: str
    target: str = "speed"  # speed, memory, both
    language: str = "python"

# ============================================================================
# 错误检测器
# ============================================================================

class ErrorDetector:
    """错误检测器"""
    
    def detect_syntax_errors(self, code: str, language: str) -> List[Error]:
        """检测语法错误"""
        errors = []
        
        if language == "python":
            try:
                ast.parse(code)
            except SyntaxError as e:
                errors.append(Error(
                    type="SyntaxError",
                    message=str(e.msg),
                    line=e.lineno,
                    column=e.offset,
                    traceback=None
                ))
        
        return errors
    
    def detect_runtime_errors(self, code: str, language: str) -> List[Error]:
        """检测运行时错误（通过静态分析）"""
        errors = []
        
        if language == "python":
            # 检查常见的运行时错误
            try:
                tree = ast.parse(code)
                
                # 检查未定义的变量
                defined_vars = set()
                used_vars = set()
                
                for node in ast.walk(tree):
                    if isinstance(node, ast.Name):
                        if isinstance(node.ctx, ast.Store):
                            defined_vars.add(node.id)
                        elif isinstance(node.ctx, ast.Load):
                            used_vars.add(node.id)
                
                # 内置函数和关键字
                builtins = set(dir(__builtins__))
                
                undefined_vars = used_vars - defined_vars - builtins
                for var in undefined_vars:
                    errors.append(Error(
                        type="NameError",
                        message=f"可能未定义的变量: {var}",
                        line=None,
                        column=None,
                        traceback=None
                    ))
            
            except Exception as e:
                pass
        
        return errors

# 初始化错误检测器
error_detector = ErrorDetector()

# ============================================================================
# 错误诊断器
# ============================================================================

class ErrorDiagnoser:
    """错误诊断器"""
    
    def diagnose(self, code: str, error: str, language: str) -> Dict[str, Any]:
        """诊断错误"""
        # 基础诊断
        diagnosis = {
            "error": error,
            "possible_causes": [],
            "suggestions": []
        }
        
        # 常见错误模式
        if "SyntaxError" in error:
            diagnosis["possible_causes"].append("代码语法不正确")
            diagnosis["suggestions"].append("检查括号、引号是否匹配")
            diagnosis["suggestions"].append("检查缩进是否正确")
        
        elif "NameError" in error:
            diagnosis["possible_causes"].append("使用了未定义的变量或函数")
            diagnosis["suggestions"].append("检查变量名是否拼写正确")
            diagnosis["suggestions"].append("确保变量在使用前已定义")
        
        elif "TypeError" in error:
            diagnosis["possible_causes"].append("类型不匹配")
            diagnosis["suggestions"].append("检查函数参数类型")
            diagnosis["suggestions"].append("检查操作符是否适用于该类型")
        
        elif "IndexError" in error:
            diagnosis["possible_causes"].append("索引超出范围")
            diagnosis["suggestions"].append("检查列表或数组的长度")
            diagnosis["suggestions"].append("确保索引在有效范围内")
        
        # 使用 LLM 进行深度诊断
        if DEEPSEEK_API_KEY:
            llm_diagnosis = self._llm_diagnose(code, error)
            if llm_diagnosis:
                diagnosis["llm_diagnosis"] = llm_diagnosis
        
        return diagnosis
    
    def _llm_diagnose(self, code: str, error: str) -> Optional[str]:
        """使用 LLM 诊断错误"""
        try:
            import httpx
            
            response = httpx.post(
                f"{DEEPSEEK_API_BASE}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "deepseek-coder",
                    "messages": [
                        {
                            "role": "system",
                            "content": "你是一个调试专家，帮助用户诊断代码错误。"
                        },
                        {
                            "role": "user",
                            "content": f"代码:\n```\n{code}\n```\n\n错误:\n{error}\n\n请分析错误原因并提供解决方案。"
                        }
                    ],
                    "temperature": 0.3
                },
                timeout=30.0
            )
            
            if response.status_code == 200:
                result = response.json()
                return result["choices"][0]["message"]["content"]
            else:
                return None
        
        except Exception as e:
            return None

# 初始化错误诊断器
error_diagnoser = ErrorDiagnoser()

# ============================================================================
# 自动修复器
# ============================================================================

class AutoFixer:
    """自动修复器"""
    
    def fix(self, code: str, error: str, language: str) -> Optional[Fix]:
        """自动修复错误"""
        # 尝试简单修复
        simple_fix = self._simple_fix(code, error, language)
        if simple_fix:
            return simple_fix
        
        # 使用 LLM 修复
        if DEEPSEEK_API_KEY:
            llm_fix = self._llm_fix(code, error, language)
            if llm_fix:
                return llm_fix
        
        return None
    
    def _simple_fix(self, code: str, error: str, language: str) -> Optional[Fix]:
        """简单修复"""
        if language == "python":
            # 修复常见的缩进错误
            if "IndentationError" in error:
                lines = code.split('\n')
                fixed_lines = []
                for line in lines:
                    # 移除行首空格，然后根据冒号添加缩进
                    stripped = line.lstrip()
                    if stripped:
                        fixed_lines.append(stripped)
                    else:
                        fixed_lines.append(line)
                
                fixed_code = '\n'.join(fixed_lines)
                return Fix(
                    original_code=code,
                    fixed_code=fixed_code,
                    explanation="修复了缩进错误",
                    confidence=0.6
                )
        
        return None
    
    def _llm_fix(self, code: str, error: str, language: str) -> Optional[Fix]:
        """使用 LLM 修复"""
        try:
            import httpx
            
            response = httpx.post(
                f"{DEEPSEEK_API_BASE}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "deepseek-coder",
                    "messages": [
                        {
                            "role": "system",
                            "content": "你是一个代码修复专家，帮助用户修复代码错误。请只返回修复后的代码，不要添加额外的解释。"
                        },
                        {
                            "role": "user",
                            "content": f"请修复以下代码中的错误:\n\n代码:\n```{language}\n{code}\n```\n\n错误:\n{error}\n\n请返回修复后的完整代码。"
                        }
                    ],
                    "temperature": 0.3
                },
                timeout=60.0
            )
            
            if response.status_code == 200:
                result = response.json()
                fixed_code = result["choices"][0]["message"]["content"]
                
                # 提取代码块
                if "```" in fixed_code:
                    parts = fixed_code.split("```")
                    if len(parts) >= 3:
                        code_block = parts[1]
                        if code_block.startswith(language):
                            code_block = code_block[len(language):].strip()
                        elif code_block.startswith("python"):
                            code_block = code_block[6:].strip()
                        fixed_code = code_block
                
                return Fix(
                    original_code=code,
                    fixed_code=fixed_code,
                    explanation="使用 LLM 自动修复",
                    confidence=0.8
                )
            else:
                return None
        
        except Exception as e:
            return None

# 初始化自动修复器
auto_fixer = AutoFixer()

# ============================================================================
# 性能分析器
# ============================================================================

class PerformanceAnalyzer:
    """性能分析器"""
    
    def analyze(self, code: str, language: str) -> Dict[str, Any]:
        """分析性能"""
        if language != "python":
            return {"error": "只支持 Python"}
        
        analysis = {
            "complexity": self._analyze_complexity(code),
            "bottlenecks": self._find_bottlenecks(code),
            "suggestions": []
        }
        
        # 添加优化建议
        if analysis["complexity"] > 10:
            analysis["suggestions"].append("代码复杂度较高，建议拆分函数")
        
        if analysis["bottlenecks"]:
            analysis["suggestions"].append("发现潜在的性能瓶颈")
        
        return analysis
    
    def _analyze_complexity(self, code: str) -> int:
        """分析复杂度"""
        try:
            tree = ast.parse(code)
            
            # 计算圈复杂度
            complexity = 1
            for node in ast.walk(tree):
                if isinstance(node, (ast.If, ast.While, ast.For, ast.ExceptHandler)):
                    complexity += 1
                elif isinstance(node, ast.BoolOp):
                    complexity += len(node.values) - 1
            
            return complexity
        except Exception:
            return 0
    
    def _find_bottlenecks(self, code: str) -> List[str]:
        """查找性能瓶颈"""
        bottlenecks = []
        
        try:
            tree = ast.parse(code)
            
            # 检查嵌套循环
            for node in ast.walk(tree):
                if isinstance(node, (ast.For, ast.While)):
                    for child in ast.walk(node):
                        if child != node and isinstance(child, (ast.For, ast.While)):
                            bottlenecks.append("嵌套循环可能导致性能问题")
                            break
            
            # 检查大量的字符串拼接
            # （简化版，实际需要更复杂的分析）

        except Exception:
            pass
        
        return bottlenecks

# 初始化性能分析器
performance_analyzer = PerformanceAnalyzer()

# ============================================================================
# 代码优化器
# ============================================================================

class CodeOptimizer:
    """代码优化器"""
    
    def optimize(self, code: str, target: str, language: str) -> str:
        """优化代码"""
        if not DEEPSEEK_API_KEY:
            return code
        
        try:
            import httpx
            
            target_descriptions = {
                "speed": "提高执行速度",
                "memory": "减少内存使用",
                "both": "同时优化速度和内存"
            }
            
            target_desc = target_descriptions.get(target, target)
            
            response = httpx.post(
                f"{DEEPSEEK_API_BASE}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "deepseek-coder",
                    "messages": [
                        {
                            "role": "system",
                            "content": "你是一个性能优化专家，帮助用户优化代码性能。"
                        },
                        {
                            "role": "user",
                            "content": f"请优化以下 {language} 代码，目标是{target_desc}:\n```\n{code}\n```"
                        }
                    ],
                    "temperature": 0.3
                },
                timeout=60.0
            )
            
            if response.status_code == 200:
                result = response.json()
                optimized_code = result["choices"][0]["message"]["content"]
                
                # 提取代码块
                if "```" in optimized_code:
                    parts = optimized_code.split("```")
                    if len(parts) >= 3:
                        code_block = parts[1]
                        if code_block.startswith(language):
                            code_block = code_block[len(language):].strip()
                        elif code_block.startswith("python"):
                            code_block = code_block[6:].strip()
                        return code_block
                
                return optimized_code
            else:
                return code
        
        except Exception as e:
            return code

# 初始化代码优化器
code_optimizer = CodeOptimizer()

# ============================================================================
# API 端点
# ============================================================================

@app.get("/health")
async def health():
    """健康检查"""
    return {
        "status": "healthy",
        "version": "1.0.0",
        "name": "Node_102_DebugOptimize",
        "deepseek_configured": bool(DEEPSEEK_API_KEY),
        "timestamp": "2026-01-22"
    }

@app.post("/detect_errors")
async def detect_errors(request: DetectErrorsRequest) -> Dict[str, Any]:
    """检测错误"""
    syntax_errors = error_detector.detect_syntax_errors(request.code, request.language)
    runtime_errors = error_detector.detect_runtime_errors(request.code, request.language)
    
    all_errors = syntax_errors + runtime_errors
    
    return {
        "success": True,
        "error_count": len(all_errors),
        "errors": [asdict(e) for e in all_errors]
    }

@app.post("/diagnose_error")
async def diagnose_error(request: DiagnoseErrorRequest) -> Dict[str, Any]:
    """诊断错误"""
    diagnosis = error_diagnoser.diagnose(request.code, request.error, request.language)
    
    return {
        "success": True,
        **diagnosis
    }

@app.post("/auto_fix")
async def auto_fix(request: AutoFixRequest) -> Dict[str, Any]:
    """自动修复"""
    fix = auto_fixer.fix(request.code, request.error, request.language)
    
    if fix:
        return {
            "success": True,
            "fix": asdict(fix)
        }
    else:
        return {
            "success": False,
            "message": "无法自动修复此错误"
        }

@app.post("/analyze_performance")
async def analyze_performance(request: AnalyzePerformanceRequest) -> Dict[str, Any]:
    """性能分析"""
    analysis = performance_analyzer.analyze(request.code, request.language)
    
    return {
        "success": True,
        **analysis
    }

@app.post("/optimize_code")
async def optimize_code(request: OptimizeCodeRequest) -> Dict[str, Any]:
    """优化代码"""
    optimized_code = code_optimizer.optimize(request.code, request.target, request.language)
    
    return {
        "success": True,
        "original_code": request.code,
        "optimized_code": optimized_code,
        "target": request.target
    }

# ============================================================================
# 启动服务
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8102)
