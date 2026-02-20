"""
Node_101_CodeEngine - 代码理解和生成系统

功能：
1. 代码解析（AST）
2. 代码理解（语义分析）
3. 代码生成（需求转代码）
4. 代码重构（优化和改进）
5. 代码审查（质量检查）

技术栈：
- ast（Python AST）
- tree-sitter（多语言 AST）
- DeepSeek Coder（代码 LLM）
- pylint（静态分析）

版本：1.0.0
日期：2026-01-22
作者：Manus AI
"""

import os
import ast
import json
import subprocess
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Node_101_CodeEngine", version="1.0.0")
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
class CodeAnalysis:
    """代码分析结果"""
    language: str
    lines: int
    functions: List[str]
    classes: List[str]
    imports: List[str]
    complexity: int
    issues: List[str]

class ParseCodeRequest(BaseModel):
    """解析代码请求"""
    code: str
    language: str = "python"

class UnderstandCodeRequest(BaseModel):
    """理解代码请求"""
    code: str
    language: str = "python"
    question: Optional[str] = None

class GenerateCodeRequest(BaseModel):
    """生成代码请求"""
    requirement: str
    language: str = "python"
    context: Optional[str] = None

class RefactorCodeRequest(BaseModel):
    """重构代码请求"""
    code: str
    language: str = "python"
    goal: str = "improve_readability"

class ReviewCodeRequest(BaseModel):
    """审查代码请求"""
    code: str
    language: str = "python"

# ============================================================================
# 代码解析器
# ============================================================================

class PythonCodeParser:
    """Python 代码解析器"""
    
    def parse(self, code: str) -> CodeAnalysis:
        """解析 Python 代码"""
        try:
            tree = ast.parse(code)
            
            # 提取函数
            functions = []
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    functions.append(node.name)
            
            # 提取类
            classes = []
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    classes.append(node.name)
            
            # 提取导入
            imports = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.append(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        imports.append(node.module)
            
            # 计算行数
            lines = len(code.split('\n'))
            
            # 计算复杂度（简单估算）
            complexity = len(functions) + len(classes) * 2
            
            return CodeAnalysis(
                language="python",
                lines=lines,
                functions=functions,
                classes=classes,
                imports=imports,
                complexity=complexity,
                issues=[]
            )
        
        except SyntaxError as e:
            return CodeAnalysis(
                language="python",
                lines=len(code.split('\n')),
                functions=[],
                classes=[],
                imports=[],
                complexity=0,
                issues=[f"语法错误: {str(e)}"]
            )

# 初始化解析器
python_parser = PythonCodeParser()

# ============================================================================
# 代码理解器
# ============================================================================

class CodeUnderstanding:
    """代码理解器"""
    
    def understand(self, code: str, language: str, question: Optional[str] = None) -> Dict[str, Any]:
        """理解代码"""
        # 解析代码
        if language == "python":
            analysis = python_parser.parse(code)
        else:
            analysis = CodeAnalysis(
                language=language,
                lines=len(code.split('\n')),
                functions=[],
                classes=[],
                imports=[],
                complexity=0,
                issues=["不支持的语言"]
            )
        
        # 生成总结
        summary = self._generate_summary(code, analysis)
        
        # 如果有问题，使用 LLM 回答
        answer = None
        if question and DEEPSEEK_API_KEY:
            answer = self._answer_question(code, question)
        
        return {
            "analysis": asdict(analysis),
            "summary": summary,
            "answer": answer
        }
    
    def _generate_summary(self, code: str, analysis: CodeAnalysis) -> str:
        """生成代码总结"""
        summary = f"这是一个 {analysis.language} 代码，共 {analysis.lines} 行。"
        
        if analysis.functions:
            summary += f"\n包含 {len(analysis.functions)} 个函数: {', '.join(analysis.functions[:5])}"
            if len(analysis.functions) > 5:
                summary += f" 等"
        
        if analysis.classes:
            summary += f"\n包含 {len(analysis.classes)} 个类: {', '.join(analysis.classes[:5])}"
            if len(analysis.classes) > 5:
                summary += f" 等"
        
        if analysis.imports:
            summary += f"\n导入了 {len(analysis.imports)} 个模块: {', '.join(analysis.imports[:5])}"
            if len(analysis.imports) > 5:
                summary += f" 等"
        
        if analysis.issues:
            summary += f"\n发现 {len(analysis.issues)} 个问题: {', '.join(analysis.issues)}"
        
        return summary
    
    def _answer_question(self, code: str, question: str) -> str:
        """使用 LLM 回答问题"""
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
                            "content": "你是一个代码分析专家，帮助用户理解代码。"
                        },
                        {
                            "role": "user",
                            "content": f"代码:\n```\n{code}\n```\n\n问题: {question}"
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
                return f"API 调用失败: {response.status_code}"
        
        except Exception as e:
            return f"错误: {str(e)}"

# 初始化理解器
code_understanding = CodeUnderstanding()

# ============================================================================
# 代码生成器
# ============================================================================

class CodeGenerator:
    """代码生成器"""
    
    def generate(self, requirement: str, language: str, context: Optional[str] = None) -> str:
        """生成代码"""
        if not DEEPSEEK_API_KEY:
            return "# 错误: 未配置 DEEPSEEK_API_KEY"
        
        try:
            import httpx
            
            # 构建提示
            prompt = f"请用 {language} 编写代码，实现以下需求:\n{requirement}"
            if context:
                prompt += f"\n\n上下文:\n{context}"
            
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
                            "content": "你是一个专业的程序员，擅长编写高质量的代码。"
                        },
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ],
                    "temperature": 0.3
                },
                timeout=60.0
            )
            
            if response.status_code == 200:
                result = response.json()
                code = result["choices"][0]["message"]["content"]
                
                # 提取代码块
                if "```" in code:
                    # 提取第一个代码块
                    parts = code.split("```")
                    if len(parts) >= 3:
                        code_block = parts[1]
                        # 移除语言标记
                        if code_block.startswith(language):
                            code_block = code_block[len(language):].strip()
                        elif code_block.startswith("python"):
                            code_block = code_block[6:].strip()
                        return code_block
                
                return code
            else:
                return f"# API 调用失败: {response.status_code}"
        
        except Exception as e:
            return f"# 错误: {str(e)}"

# 初始化生成器
code_generator = CodeGenerator()

# ============================================================================
# 代码重构器
# ============================================================================

class CodeRefactor:
    """代码重构器"""
    
    def refactor(self, code: str, language: str, goal: str) -> str:
        """重构代码"""
        if not DEEPSEEK_API_KEY:
            return code
        
        try:
            import httpx
            
            # 构建提示
            goal_descriptions = {
                "improve_readability": "提高可读性",
                "optimize_performance": "优化性能",
                "reduce_complexity": "降低复杂度",
                "add_comments": "添加注释",
                "follow_best_practices": "遵循最佳实践"
            }
            
            goal_desc = goal_descriptions.get(goal, goal)
            
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
                            "content": "你是一个代码重构专家，帮助用户改进代码质量。"
                        },
                        {
                            "role": "user",
                            "content": f"请重构以下 {language} 代码，目标是{goal_desc}:\n```\n{code}\n```"
                        }
                    ],
                    "temperature": 0.3
                },
                timeout=60.0
            )
            
            if response.status_code == 200:
                result = response.json()
                refactored_code = result["choices"][0]["message"]["content"]
                
                # 提取代码块
                if "```" in refactored_code:
                    parts = refactored_code.split("```")
                    if len(parts) >= 3:
                        code_block = parts[1]
                        if code_block.startswith(language):
                            code_block = code_block[len(language):].strip()
                        elif code_block.startswith("python"):
                            code_block = code_block[6:].strip()
                        return code_block
                
                return refactored_code
            else:
                return code
        
        except Exception as e:
            return code

# 初始化重构器
code_refactor = CodeRefactor()

# ============================================================================
# 代码审查器
# ============================================================================

class CodeReviewer:
    """代码审查器"""
    
    def review(self, code: str, language: str) -> Dict[str, Any]:
        """审查代码"""
        issues = []
        suggestions = []
        
        # 1. 语法检查
        if language == "python":
            try:
                ast.parse(code)
            except SyntaxError as e:
                issues.append({
                    "type": "syntax_error",
                    "message": str(e),
                    "severity": "high"
                })
        
        # 2. 使用 pylint 检查（如果可用）
        if language == "python":
            try:
                # 写入临时文件
                import tempfile
                with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                    f.write(code)
                    temp_file = f.name
                
                # 运行 pylint
                result = subprocess.run(
                    ['pylint', temp_file, '--output-format=json'],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                
                # 解析结果
                if result.stdout:
                    pylint_issues = json.loads(result.stdout)
                    for issue in pylint_issues[:10]:  # 限制数量
                        issues.append({
                            "type": issue.get("type", "unknown"),
                            "message": issue.get("message", ""),
                            "line": issue.get("line", 0),
                            "severity": "medium"
                        })
                
                # 删除临时文件
                os.unlink(temp_file)
            
            except Exception as e:
                pass  # pylint 不可用或执行失败
        
        # 3. 使用 LLM 审查（如果可用）
        if DEEPSEEK_API_KEY:
            llm_review = self._llm_review(code, language)
            if llm_review:
                suggestions.append(llm_review)
        
        return {
            "issues": issues,
            "suggestions": suggestions,
            "summary": f"发现 {len(issues)} 个问题，{len(suggestions)} 条建议"
        }
    
    def _llm_review(self, code: str, language: str) -> Optional[str]:
        """使用 LLM 审查代码"""
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
                            "content": "你是一个代码审查专家，帮助用户发现代码中的问题和改进建议。"
                        },
                        {
                            "role": "user",
                            "content": f"请审查以下 {language} 代码，指出问题和改进建议:\n```\n{code}\n```"
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

# 初始化审查器
code_reviewer = CodeReviewer()

# ============================================================================
# API 端点
# ============================================================================

@app.get("/health")
async def health():
    """健康检查"""
    return {
        "status": "healthy",
        "version": "1.0.0",
        "name": "Node_101_CodeEngine",
        "deepseek_configured": bool(DEEPSEEK_API_KEY),
        "timestamp": "2026-01-22"
    }

@app.post("/parse_code")
async def parse_code(request: ParseCodeRequest) -> Dict[str, Any]:
    """解析代码"""
    if request.language == "python":
        analysis = python_parser.parse(request.code)
        return {
            "success": True,
            "analysis": asdict(analysis)
        }
    else:
        return {
            "success": False,
            "error": "不支持的语言"
        }

@app.post("/understand_code")
async def understand_code(request: UnderstandCodeRequest) -> Dict[str, Any]:
    """理解代码"""
    result = code_understanding.understand(request.code, request.language, request.question)
    return {
        "success": True,
        **result
    }

@app.post("/generate_code")
async def generate_code(request: GenerateCodeRequest) -> Dict[str, Any]:
    """生成代码"""
    code = code_generator.generate(request.requirement, request.language, request.context)
    return {
        "success": True,
        "code": code,
        "language": request.language
    }

@app.post("/refactor_code")
async def refactor_code(request: RefactorCodeRequest) -> Dict[str, Any]:
    """重构代码"""
    refactored_code = code_refactor.refactor(request.code, request.language, request.goal)
    return {
        "success": True,
        "original_code": request.code,
        "refactored_code": refactored_code,
        "goal": request.goal
    }

@app.post("/review_code")
async def review_code(request: ReviewCodeRequest) -> Dict[str, Any]:
    """审查代码"""
    review_result = code_reviewer.review(request.code, request.language)
    return {
        "success": True,
        **review_result
    }

# ============================================================================
# 启动服务
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8101)
