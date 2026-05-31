"""
Node 63: FuzzyLogicEngine - Fuzzy Logic Inference Engine
Supports Mamdani and Sugeno inference with triangular/trapezoidal membership functions.
"""
import os
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from nodes.common.cors_config import get_cors_origins

try:
    from core.port_config import get_node_port
    PORT = get_node_port("Node_63_FuzzyLogicEngine")
except Exception as exc:
    logger.debug("Fallback triggered: %s", exc)
    PORT = int(os.getenv("PORT", "8163"))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Node 63 - FuzzyLogicEngine", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_start_time = datetime.now()


# ---------------------------------------------------------------------------
# Pure-Python fuzzy logic implementation
# ---------------------------------------------------------------------------

def _trimf(x: float, a: float, b: float, c: float) -> float:
    """Triangular membership function."""
    if x <= a or x >= c:
        return 0.0
    if x <= b:
        return (x - a) / (b - a) if b != a else 1.0
    return (c - x) / (c - b) if c != b else 1.0


def _trapmf(x: float, a: float, b: float, c: float, d: float) -> float:
    """Trapezoidal membership function."""
    if x <= a or x >= d:
        return 0.0
    if b <= x <= c:
        return 1.0
    if x < b:
        return (x - a) / (b - a) if b != a else 1.0
    return (d - x) / (d - c) if d != c else 1.0


def _gaussmf(x: float, mean: float, sigma: float) -> float:
    """Gaussian membership function."""
    import math
    if sigma == 0:
        return 1.0 if x == mean else 0.0
    return math.exp(-0.5 * ((x - mean) / sigma) ** 2)


def _membership(x: float, mf: Dict[str, Any]) -> float:
    mf_type = mf.get("type", "trimf")
    params = mf.get("params", [])
    if mf_type == "trimf" and len(params) == 3:
        return _trimf(x, *params)
    elif mf_type == "trapmf" and len(params) == 4:
        return _trapmf(x, *params)
    elif mf_type == "gaussmf" and len(params) == 2:
        return _gaussmf(x, *params)
    elif mf_type == "const":
        return float(params[0]) if params else 0.0
    raise ValueError(f"Unknown membership function type: {mf_type}")


class FuzzyEngine:
    def __init__(self):
        self.fuzzy_sets: Dict[str, Dict[str, Any]] = {}
        self.rules: List[Dict[str, Any]] = []

    def define_set(self, variable: str, term: str, mf: Dict[str, Any]) -> None:
        key = f"{variable}.{term}"
        self.fuzzy_sets[key] = mf

    def get_membership(self, variable: str, term: str, value: float) -> float:
        key = f"{variable}.{term}"
        if key not in self.fuzzy_sets:
            raise ValueError(f"Fuzzy set '{key}' not defined")
        return _membership(value, self.fuzzy_sets[key])

    def add_rule(self, antecedents: List[Dict], consequent: Dict, weight: float = 1.0) -> int:
        rule = {"antecedents": antecedents, "consequent": consequent, "weight": weight}
        self.rules.append(rule)
        return len(self.rules) - 1

    def _eval_antecedent(self, ant: Dict, inputs: Dict[str, float]) -> float:
        variable = ant["variable"]
        term = ant["term"]
        value = inputs.get(variable)
        if value is None:
            raise ValueError(f"Input variable '{variable}' not provided")
        return self.get_membership(variable, term, value)

    def mamdani_infer(self, inputs: Dict[str, float], output_variable: str,
                      output_range: Tuple[float, float], resolution: int = 100) -> Dict[str, Any]:
        """Mamdani inference with centroid defuzzification."""
        lo, hi = output_range
        step = (hi - lo) / resolution
        x_vals = [lo + i * step for i in range(resolution + 1)]

        aggregated = [0.0] * len(x_vals)

        fired_rules = []
        for rule in self.rules:
            if rule["consequent"]["variable"] != output_variable:
                continue
            # AND aggregation of antecedents
            strengths = [self._eval_antecedent(a, inputs) for a in rule["antecedents"]]
            firing = min(strengths) * rule["weight"]
            if firing <= 0:
                continue

            cons_term = rule["consequent"]["term"]
            for i, xv in enumerate(x_vals):
                mf_val = self.get_membership(output_variable, cons_term, xv)
                aggregated[i] = max(aggregated[i], min(firing, mf_val))
            fired_rules.append({"term": cons_term, "firing_strength": round(firing, 4)})

        # Centroid defuzzification
        numerator = sum(x * y for x, y in zip(x_vals, aggregated))
        denominator = sum(aggregated)
        crisp = numerator / denominator if denominator != 0 else (lo + hi) / 2

        return {
            "success": True,
            "method": "mamdani",
            "output_variable": output_variable,
            "crisp_output": round(crisp, 6),
            "fired_rules": fired_rules,
        }

    def sugeno_infer(self, inputs: Dict[str, float], output_variable: str) -> Dict[str, Any]:
        """Sugeno (weighted average) inference."""
        numerator = 0.0
        denominator = 0.0
        fired_rules = []

        for rule in self.rules:
            if rule["consequent"]["variable"] != output_variable:
                continue
            strengths = [self._eval_antecedent(a, inputs) for a in rule["antecedents"]]
            firing = min(strengths) * rule["weight"]
            if firing <= 0:
                continue

            cons_term = rule["consequent"]["term"]
            cons_key = f"{output_variable}.{cons_term}"
            if cons_key not in self.fuzzy_sets:
                raise ValueError(f"Consequent set '{cons_key}' not defined")
            mf = self.fuzzy_sets[cons_key]
            # For Sugeno: const or linear output
            if mf.get("type") == "const":
                output_val = float(mf["params"][0])
            else:
                output_val = mf.get("params", [0])[0]

            numerator += firing * output_val
            denominator += firing
            fired_rules.append({"term": cons_term, "firing_strength": round(firing, 4),
                                 "output_value": output_val})

        crisp = numerator / denominator if denominator != 0 else 0.0
        return {
            "success": True,
            "method": "sugeno",
            "output_variable": output_variable,
            "crisp_output": round(crisp, 6),
            "fired_rules": fired_rules,
        }

    def defuzz_centroid(self, variable: str, output_range: Tuple[float, float],
                        resolution: int = 100) -> float:
        """Compute centroid of all membership functions for a variable."""
        lo, hi = output_range
        step = (hi - lo) / resolution
        x_vals = [lo + i * step for i in range(resolution + 1)]
        aggregated = [0.0] * len(x_vals)

        for key, mf in self.fuzzy_sets.items():
            if "." not in key:
                continue
            var, _ = key.split(".", 1)
            if var != variable:
                continue
            for i, xv in enumerate(x_vals):
                aggregated[i] = max(aggregated[i], _membership(xv, mf))

        num = sum(x * y for x, y in zip(x_vals, aggregated))
        den = sum(aggregated)
        return num / den if den != 0 else (lo + hi) / 2


engine = FuzzyEngine()


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class DefineSetRequest(BaseModel):
    variable: str
    term: str
    mf_type: str  # trimf, trapmf, gaussmf, const
    params: List[float]


class DefineRuleRequest(BaseModel):
    antecedents: List[Dict[str, str]]
    consequent: Dict[str, str]
    weight: float = 1.0


class InferRequest(BaseModel):
    inputs: Dict[str, float]
    output_variable: str


class MamdaniRequest(BaseModel):
    inputs: Dict[str, float]
    output_variable: str
    output_range: List[float] = [0.0, 100.0]
    resolution: int = 100


class SugenoRequest(BaseModel):
    inputs: Dict[str, float]
    output_variable: str


class DefuzzRequest(BaseModel):
    variable: str
    output_range: List[float] = [0.0, 100.0]
    resolution: int = 100


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "node_id": "63",
        "name": "FuzzyLogicEngine",
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/status")
async def status():
    uptime = (datetime.now() - _start_time).total_seconds()
    return {
        "status": "running",
        "node_id": "63",
        "name": "FuzzyLogicEngine",
        "uptime_seconds": round(uptime, 2),
        "configuration": {},
        "metrics": {
            "fuzzy_sets_defined": len(engine.fuzzy_sets),
            "rules_defined": len(engine.rules),
        },
        "timestamp": datetime.now().isoformat(),
    }


@app.post("/define_set")
async def define_set(request: DefineSetRequest):
    """Define a fuzzy membership function for a variable term."""
    mf = {"type": request.mf_type, "params": request.params}
    engine.define_set(request.variable, request.term, mf)
    return {
        "success": True,
        "key": f"{request.variable}.{request.term}",
        "mf": mf,
        "total_sets": len(engine.fuzzy_sets),
    }


@app.post("/define_rule")
async def define_rule(request: DefineRuleRequest):
    """Define an IF-THEN fuzzy rule."""
    idx = engine.add_rule(request.antecedents, request.consequent, request.weight)
    return {"success": True, "rule_index": idx, "total_rules": len(engine.rules)}


@app.post("/infer")
async def infer(request: InferRequest):
    """Generic inference: returns membership degrees for each defined term."""
    try:
        results: Dict[str, float] = {}
        for key in engine.fuzzy_sets:
            if "." not in key:
                continue
            var, term = key.split(".", 1)
            if var in request.inputs:
                results[key] = round(
                    _membership(request.inputs[var], engine.fuzzy_sets[key]), 6
                )
        return {"success": True, "memberships": results}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/mamdani")
async def mamdani(request: MamdaniRequest):
    """Mamdani fuzzy inference with centroid defuzzification."""
    try:
        result = engine.mamdani_infer(
            inputs=request.inputs,
            output_variable=request.output_variable,
            output_range=tuple(request.output_range[:2]),
            resolution=request.resolution,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/sugeno")
async def sugeno(request: SugenoRequest):
    """Sugeno fuzzy inference (weighted average)."""
    try:
        result = engine.sugeno_infer(
            inputs=request.inputs,
            output_variable=request.output_variable,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/defuzz")
async def defuzz(request: DefuzzRequest):
    """Defuzzify a variable using centroid method."""
    try:
        crisp = engine.defuzz_centroid(
            variable=request.variable,
            output_range=tuple(request.output_range[:2]),
            resolution=request.resolution,
        )
        return {"success": True, "variable": request.variable, "crisp_output": round(crisp, 6)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/sets")
async def list_sets():
    """List all defined fuzzy sets."""
    return {"success": True, "fuzzy_sets": engine.fuzzy_sets}


@app.get("/rules")
async def list_rules():
    """List all defined rules."""
    return {"success": True, "rules": engine.rules}


@app.post("/mcp/call")
async def mcp_call(request: dict):
    tool = request.get("tool", "")
    params = request.get("params", {})
    if tool == "define_set":
        return await define_set(DefineSetRequest(**params))
    elif tool == "define_rule":
        return await define_rule(DefineRuleRequest(**params))
    elif tool == "infer":
        return await infer(InferRequest(**params))
    elif tool == "mamdani":
        return await mamdani(MamdaniRequest(**params))
    elif tool == "sugeno":
        return await sugeno(SugenoRequest(**params))
    elif tool == "defuzz":
        return await defuzz(DefuzzRequest(**params))
    elif tool == "list_sets":
        return await list_sets()
    elif tool == "list_rules":
        return await list_rules()
    raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
