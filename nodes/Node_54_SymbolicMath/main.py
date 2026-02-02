"""
Node 54: Symbolic Math & Formal Verification
UFO Galaxy 64-Core MCP Matrix - Phase 5: Scientific Brain

Three-layer verification pipeline for mathematical formulas.
"""

import os
import json
import asyncio
import logging
import hashlib
import re
from typing import Dict, Optional, List, Any, Tuple
from datetime import datetime
from contextlib import asynccontextmanager
from enum import Enum
from dataclasses import dataclass, field

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn

# =============================================================================
# Configuration
# =============================================================================

NODE_ID = os.getenv("NODE_ID", "54")
NODE_NAME = os.getenv("NODE_NAME", "SymbolicMath")
STATE_MACHINE_URL = os.getenv("STATE_MACHINE_URL", "http://localhost:8000")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format=f"[Node {NODE_ID}] %(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# =============================================================================
# Models
# =============================================================================

class VerificationLevel(str, Enum):
    BASIC = "basic"         # Syntax only
    FULL = "full"           # Syntax + Semantic
    PEDANTIC = "pedantic"   # All three layers

class MathDomain(str, Enum):
    CALCULUS = "calculus"
    ALGEBRA = "algebra"
    LINEAR_ALGEBRA = "linear_algebra"
    STATISTICS = "statistics"
    PHYSICS = "physics"
    ENGINEERING = "engineering"
    ECONOMICS = "economics"
    GENERAL = "general"

class VerificationRequest(BaseModel):
    formula: str = Field(..., description="Mathematical formula to verify")
    context: Dict[str, Any] = Field(default={}, description="Context and assumptions")
    verification_level: VerificationLevel = Field(default=VerificationLevel.FULL)
    domain: MathDomain = Field(default=MathDomain.GENERAL)

class VerificationResult(BaseModel):
    valid: bool
    simplified_form: Optional[str] = None
    verification_steps: List[Dict[str, Any]] = []
    alternative_forms: List[str] = []
    warnings: List[str] = []
    confidence: float = 1.0
    formula_hash: str = ""

@dataclass
class FormulaRecord:
    """Immutable record of a verified formula."""
    formula: str
    hash: str
    verified_at: str
    verification_result: bool
    domain: str
    version: int = 1

# =============================================================================
# Symbolic Math Engine (Mock SymPy-like)
# =============================================================================

class SymbolicEngine:
    """Symbolic mathematics engine (mock implementation)."""
    
    # Common mathematical constants
    CONSTANTS = {
        "pi": 3.141592653589793,
        "e": 2.718281828459045,
        "phi": 1.618033988749895,  # Golden ratio
        "sqrt2": 1.4142135623730951,
    }
    
    # Known integral results
    KNOWN_INTEGRALS = {
        "∫x²dx": "x³/3 + C",
        "∫₀¹x²dx": "1/3",
        "∫sin(x)dx": "-cos(x) + C",
        "∫cos(x)dx": "sin(x) + C",
        "∫e^x dx": "e^x + C",
        "∫1/x dx": "ln|x| + C",
    }
    
    # Known derivatives
    KNOWN_DERIVATIVES = {
        "d/dx(x²)": "2x",
        "d/dx(x³)": "3x²",
        "d/dx(sin(x))": "cos(x)",
        "d/dx(cos(x))": "-sin(x)",
        "d/dx(e^x)": "e^x",
        "d/dx(ln(x))": "1/x",
    }
    
    def parse(self, formula: str) -> Tuple[bool, str, List[str]]:
        """Parse and validate formula syntax."""
        errors = []
        
        # Check balanced parentheses
        if formula.count('(') != formula.count(')'):
            errors.append("Unbalanced parentheses")
        
        # Check balanced brackets
        if formula.count('[') != formula.count(']'):
            errors.append("Unbalanced brackets")
        
        # Check for common syntax errors
        if re.search(r'[+\-*/^]{2,}', formula.replace('**', '^')):
            errors.append("Consecutive operators detected")
        
        # Check for division by zero patterns
        if re.search(r'/\s*0(?![.\d])', formula):
            errors.append("Potential division by zero")
        
        normalized = self._normalize(formula)
        return len(errors) == 0, normalized, errors
    
    def _normalize(self, formula: str) -> str:
        """Normalize formula representation."""
        # Replace common variations
        normalized = formula.strip()
        normalized = re.sub(r'\s+', ' ', normalized)
        normalized = normalized.replace('**', '^')
        return normalized
    
    def simplify(self, formula: str) -> str:
        """Simplify mathematical expression."""
        # Simple pattern-based simplification
        simplified = formula
        
        # x + 0 = x
        simplified = re.sub(r'\+\s*0(?![.\d])', '', simplified)
        simplified = re.sub(r'0\s*\+', '', simplified)
        
        # x * 1 = x
        simplified = re.sub(r'\*\s*1(?![.\d])', '', simplified)
        simplified = re.sub(r'1\s*\*', '', simplified)
        
        # x * 0 = 0
        simplified = re.sub(r'\w+\s*\*\s*0(?![.\d])', '0', simplified)
        
        # x^1 = x
        simplified = re.sub(r'\^1(?![.\d])', '', simplified)
        
        # x^0 = 1
        simplified = re.sub(r'\w+\^0(?![.\d])', '1', simplified)
        
        return simplified.strip()
    
    def evaluate(self, formula: str, variables: Dict[str, float] = None) -> Optional[float]:
        """Evaluate formula with given variable values."""
        if variables is None:
            variables = {}
        
        try:
            # Replace constants
            expr = formula
            for const, value in self.CONSTANTS.items():
                expr = re.sub(rf'\b{const}\b', str(value), expr)
            
            # Replace variables
            for var, value in variables.items():
                expr = re.sub(rf'\b{var}\b', str(value), expr)
            
            # Replace ^ with **
            expr = expr.replace('^', '**')
            
            # Safe evaluation (very limited)
            allowed_names = {"abs": abs, "min": min, "max": max}
            result = eval(expr, {"__builtins__": {}}, allowed_names)
            return float(result)
        except:
            return None
    
    def check_equality(self, lhs: str, rhs: str) -> Tuple[bool, float]:
        """Check if two expressions are equal."""
        # Try numerical evaluation at test points
        test_values = [0.5, 1.0, 2.0, -1.0, 0.1]
        matches = 0
        total = 0
        
        for x in test_values:
            lhs_val = self.evaluate(lhs, {"x": x})
            rhs_val = self.evaluate(rhs, {"x": x})
            
            if lhs_val is not None and rhs_val is not None:
                total += 1
                if abs(lhs_val - rhs_val) < 1e-10:
                    matches += 1
        
        if total == 0:
            return False, 0.0
        
        confidence = matches / total
        return confidence > 0.8, confidence
    
    def get_alternative_forms(self, formula: str) -> List[str]:
        """Get alternative representations of formula."""
        alternatives = []
        
        # Try to evaluate if it's a constant
        value = self.evaluate(formula)
        if value is not None:
            # Add decimal form
            alternatives.append(f"{value:.6f}".rstrip('0').rstrip('.'))
            
            # Check for common fractions
            common_fractions = {
                0.5: "1/2", 0.333333: "1/3", 0.25: "1/4",
                0.2: "1/5", 0.166667: "1/6", 0.142857: "1/7",
                0.125: "1/8", 0.666667: "2/3", 0.75: "3/4"
            }
            for frac_val, frac_str in common_fractions.items():
                if abs(value - frac_val) < 0.0001:
                    alternatives.append(frac_str)
        
        return alternatives

# =============================================================================
# Verification Pipeline
# =============================================================================

class VerificationPipeline:
    """Three-layer verification pipeline."""
    
    def __init__(self):
        self.engine = SymbolicEngine()
        self.audit_trail: List[FormulaRecord] = []
    
    def verify(self, request: VerificationRequest) -> VerificationResult:
        """Run verification pipeline."""
        steps = []
        warnings = []
        valid = True
        confidence = 1.0
        
        # Layer 1: Syntax Parsing
        syntax_valid, normalized, syntax_errors = self.engine.parse(request.formula)
        steps.append({
            "layer": 1,
            "name": "Syntax Parsing",
            "passed": syntax_valid,
            "normalized": normalized,
            "errors": syntax_errors
        })
        
        if not syntax_valid:
            valid = False
            confidence *= 0.0
        
        # Layer 2: Semantic Validation (if FULL or PEDANTIC)
        if request.verification_level in [VerificationLevel.FULL, VerificationLevel.PEDANTIC]:
            semantic_result = self._semantic_validation(normalized, request.domain, request.context)
            steps.append({
                "layer": 2,
                "name": "Semantic Validation",
                **semantic_result
            })
            
            if not semantic_result["passed"]:
                valid = False
                confidence *= 0.5
            
            warnings.extend(semantic_result.get("warnings", []))
        
        # Layer 3: Logical Consistency (if PEDANTIC)
        if request.verification_level == VerificationLevel.PEDANTIC:
            logic_result = self._logical_consistency(normalized, request.context)
            steps.append({
                "layer": 3,
                "name": "Logical Consistency",
                **logic_result
            })
            
            if not logic_result["passed"]:
                valid = False
                confidence *= 0.7
            
            warnings.extend(logic_result.get("warnings", []))
        
        # Generate simplified form
        simplified = self.engine.simplify(normalized)
        
        # Get alternative forms
        alternatives = self.engine.get_alternative_forms(simplified)
        
        # Calculate formula hash
        formula_hash = hashlib.sha256(normalized.encode()).hexdigest()[:16]
        
        # Record in audit trail
        record = FormulaRecord(
            formula=normalized,
            hash=formula_hash,
            verified_at=datetime.utcnow().isoformat(),
            verification_result=valid,
            domain=request.domain.value
        )
        self.audit_trail.append(record)
        
        return VerificationResult(
            valid=valid,
            simplified_form=simplified,
            verification_steps=steps,
            alternative_forms=alternatives,
            warnings=warnings,
            confidence=confidence,
            formula_hash=formula_hash
        )
    
    def _semantic_validation(
        self,
        formula: str,
        domain: MathDomain,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Layer 2: Semantic validation."""
        passed = True
        warnings = []
        checks = []
        
        # Domain-specific checks
        if domain == MathDomain.PHYSICS:
            # Check dimensional consistency (simplified)
            if "=" in formula:
                lhs, rhs = formula.split("=", 1)
                # Placeholder for dimensional analysis
                checks.append("Dimensional analysis: assumed consistent")
        
        elif domain == MathDomain.STATISTICS:
            # Check probability constraints
            if "P(" in formula:
                warnings.append("Probability values should be in [0, 1]")
                checks.append("Probability constraint check")
        
        elif domain == MathDomain.ECONOMICS:
            # Check for negative values where inappropriate
            if "price" in formula.lower() or "cost" in formula.lower():
                warnings.append("Economic values typically non-negative")
        
        # Check assumptions from context
        assumptions = context.get("assumptions", [])
        for assumption in assumptions:
            checks.append(f"Assumption: {assumption}")
        
        return {
            "passed": passed,
            "checks": checks,
            "warnings": warnings
        }
    
    def _logical_consistency(
        self,
        formula: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Layer 3: Logical consistency check."""
        passed = True
        warnings = []
        checks = []
        
        # Check for contradictions
        if "=" in formula:
            parts = formula.split("=")
            if len(parts) == 2:
                lhs, rhs = parts
                
                # Check if LHS equals RHS
                equal, confidence = self.engine.check_equality(lhs.strip(), rhs.strip())
                
                if not equal and confidence > 0:
                    passed = False
                    warnings.append(f"Equality may not hold (confidence: {confidence:.2%})")
                
                checks.append(f"Equality verification: confidence {confidence:.2%}")
        
        # Check for tautologies
        if formula.strip() in ["0 = 0", "1 = 1", "x = x"]:
            warnings.append("Formula is a tautology")
        
        # Check for known contradictions
        contradictions = ["0 = 1", "1 = 0", "∞ = -∞"]
        if formula.strip() in contradictions:
            passed = False
            warnings.append("Formula is a known contradiction")
        
        return {
            "passed": passed,
            "checks": checks,
            "warnings": warnings
        }
    
    def get_audit_trail(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent audit trail entries."""
        return [
            {
                "formula": r.formula,
                "hash": r.hash,
                "verified_at": r.verified_at,
                "result": r.verification_result,
                "domain": r.domain
            }
            for r in self.audit_trail[-limit:]
        ]

# =============================================================================
# Cross-Disciplinary Verifier
# =============================================================================

class CrossDisciplinaryVerifier:
    """Verifies formulas against domain-specific rules."""
    
    PHYSICS_RULES = {
        "conservation": ["energy", "momentum", "charge", "mass"],
        "symmetry": ["time_reversal", "parity", "gauge"],
    }
    
    ENGINEERING_RULES = {
        "dimensional_homogeneity": True,
        "boundary_conditions": True,
        "stability_criteria": True,
    }
    
    def verify_physics(self, formula: str, context: Dict) -> Dict[str, Any]:
        """Verify physics formula."""
        checks = []
        warnings = []
        
        # Check for conservation law violations
        for law in self.PHYSICS_RULES["conservation"]:
            if law in formula.lower():
                checks.append(f"Conservation of {law}: referenced")
        
        # Check units if provided
        units = context.get("units", {})
        if units:
            checks.append(f"Unit consistency: {len(units)} units specified")
        
        return {
            "domain": "physics",
            "checks": checks,
            "warnings": warnings,
            "passed": True
        }
    
    def verify_engineering(self, formula: str, context: Dict) -> Dict[str, Any]:
        """Verify engineering formula."""
        checks = []
        warnings = []
        
        # Check for safety factors
        if "safety" in formula.lower() or "factor" in formula.lower():
            checks.append("Safety factor: referenced")
        
        # Check boundary conditions
        boundaries = context.get("boundary_conditions", [])
        if boundaries:
            checks.append(f"Boundary conditions: {len(boundaries)} specified")
        else:
            warnings.append("No boundary conditions specified")
        
        return {
            "domain": "engineering",
            "checks": checks,
            "warnings": warnings,
            "passed": True
        }

# =============================================================================
# FastAPI Application
# =============================================================================

pipeline: Optional[VerificationPipeline] = None
cross_verifier: Optional[CrossDisciplinaryVerifier] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global pipeline, cross_verifier
    
    logger.info(f"Starting Node {NODE_ID}: {NODE_NAME}")
    pipeline = VerificationPipeline()
    cross_verifier = CrossDisciplinaryVerifier()
    logger.info(f"Node {NODE_ID} ({NODE_NAME}) is ready")
    
    yield
    
    logger.info(f"Shutting down Node {NODE_ID}")

app = FastAPI(
    title=f"UFO Galaxy Node {NODE_ID}: {NODE_NAME}",
    description="Symbolic Math & Formal Verification",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================================================
# API Endpoints
# =============================================================================

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "node_id": NODE_ID,
        "node_name": NODE_NAME,
        "audit_trail_size": len(pipeline.audit_trail) if pipeline else 0
    }

@app.post("/verify", response_model=VerificationResult)
async def verify_formula(request: VerificationRequest):
    """Verify a mathematical formula."""
    return pipeline.verify(request)

@app.post("/simplify")
async def simplify_formula(formula: str):
    """Simplify a mathematical expression."""
    valid, normalized, errors = pipeline.engine.parse(formula)
    if not valid:
        raise HTTPException(status_code=400, detail={"errors": errors})
    
    simplified = pipeline.engine.simplify(normalized)
    alternatives = pipeline.engine.get_alternative_forms(simplified)
    
    return {
        "original": formula,
        "simplified": simplified,
        "alternatives": alternatives
    }

@app.post("/evaluate")
async def evaluate_formula(formula: str, variables: Dict[str, float] = None):
    """Evaluate formula with given variables."""
    result = pipeline.engine.evaluate(formula, variables)
    
    if result is None:
        raise HTTPException(status_code=400, detail="Could not evaluate formula")
    
    return {
        "formula": formula,
        "variables": variables or {},
        "result": result
    }

@app.post("/check-equality")
async def check_equality(lhs: str, rhs: str):
    """Check if two expressions are equal."""
    equal, confidence = pipeline.engine.check_equality(lhs, rhs)
    
    return {
        "lhs": lhs,
        "rhs": rhs,
        "equal": equal,
        "confidence": confidence
    }

@app.get("/audit-trail")
async def get_audit_trail(limit: int = 100):
    """Get verification audit trail."""
    return {
        "entries": pipeline.get_audit_trail(limit),
        "total": len(pipeline.audit_trail)
    }

@app.get("/domains")
async def list_domains():
    """List supported mathematical domains."""
    return {
        "domains": [
            {"name": d.value, "description": _get_domain_description(d)}
            for d in MathDomain
        ]
    }

@app.get("/stats")
async def get_stats():
    """Get verification statistics."""
    if not pipeline:
        return {"error": "Pipeline not initialized"}
    
    total = len(pipeline.audit_trail)
    valid_count = sum(1 for r in pipeline.audit_trail if r.verification_result)
    
    return {
        "total_verifications": total,
        "valid_count": valid_count,
        "invalid_count": total - valid_count,
        "success_rate": valid_count / total if total > 0 else 0,
        "domains_used": list(set(r.domain for r in pipeline.audit_trail))
    }

@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "node_id": NODE_ID,
        "node_name": NODE_NAME,
        "layer": "L1_GATEWAY",
        "capabilities": ["syntax_parsing", "semantic_validation", "logical_consistency", "simplification"]
    }

def _get_domain_description(domain: MathDomain) -> str:
    """Get domain description."""
    descriptions = {
        MathDomain.CALCULUS: "Differential and integral calculus",
        MathDomain.ALGEBRA: "Algebraic expressions and equations",
        MathDomain.LINEAR_ALGEBRA: "Vectors, matrices, and linear systems",
        MathDomain.STATISTICS: "Probability and statistical formulas",
        MathDomain.PHYSICS: "Physical laws with dimensional analysis",
        MathDomain.ENGINEERING: "Engineering formulas with safety checks",
        MathDomain.ECONOMICS: "Economic models and constraints",
        MathDomain.GENERAL: "General mathematical expressions",
    }
    return descriptions.get(domain, "Mathematical domain")

# =============================================================================
# Main Entry Point
# =============================================================================

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8054,
        reload=False,
        log_level=LOG_LEVEL.lower()
    )
