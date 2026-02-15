"""
Node 62: ProbabilisticProgramming - 概率编程
"""
import os, random, math
from datetime import datetime
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Node 62 - ProbabilisticProgramming", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

class BayesRequest(BaseModel):
    prior: float
    likelihood: float
    evidence: float

class SampleRequest(BaseModel):
    distribution: str
    params: Dict[str, float]
    n_samples: int = 1000

class MCMCRequest(BaseModel):
    target_mean: float
    target_std: float
    n_samples: int = 10000
    burn_in: int = 1000

@app.get("/health")
async def health():
    return {"status": "healthy", "node_id": "62", "name": "ProbabilisticProgramming", "timestamp": datetime.now().isoformat()}

@app.post("/bayes")
async def bayes_theorem(request: BayesRequest):
    """贝叶斯定理: P(A|B) = P(B|A) * P(A) / P(B)"""
    if request.evidence == 0:
        raise HTTPException(status_code=400, detail="Evidence cannot be zero")
    posterior = (request.likelihood * request.prior) / request.evidence
    return {"success": True, "prior": request.prior, "likelihood": request.likelihood, "evidence": request.evidence, "posterior": round(posterior, 6)}

@app.post("/sample")
async def sample_distribution(request: SampleRequest):
    """从分布中采样"""
    samples = []
    dist = request.distribution.lower()
    params = request.params
    
    for _ in range(request.n_samples):
        if dist == "normal" or dist == "gaussian":
            s = random.gauss(params.get("mean", 0), params.get("std", 1))
        elif dist == "uniform":
            s = random.uniform(params.get("low", 0), params.get("high", 1))
        elif dist == "exponential":
            s = random.expovariate(1 / params.get("scale", 1))
        elif dist == "poisson":
            lam = params.get("lambda", 1)
            s = sum(1 for _ in range(int(lam * 10)) if random.random() < lam / (lam * 10))
        elif dist == "bernoulli":
            s = 1 if random.random() < params.get("p", 0.5) else 0
        elif dist == "binomial":
            n = int(params.get("n", 10))
            p = params.get("p", 0.5)
            s = sum(1 for _ in range(n) if random.random() < p)
        else:
            raise HTTPException(status_code=400, detail=f"Unknown distribution: {dist}")
        samples.append(s)
    
    mean = sum(samples) / len(samples)
    variance = sum((x - mean)**2 for x in samples) / len(samples)
    
    return {"success": True, "distribution": dist, "n_samples": request.n_samples, "mean": round(mean, 4), "std": round(math.sqrt(variance), 4), "min": round(min(samples), 4), "max": round(max(samples), 4)}

@app.post("/mcmc")
async def metropolis_hastings(request: MCMCRequest):
    """Metropolis-Hastings MCMC 采样"""
    samples = []
    current = 0
    
    def target_pdf(x):
        return math.exp(-0.5 * ((x - request.target_mean) / request.target_std)**2)
    
    for i in range(request.n_samples + request.burn_in):
        proposal = current + random.gauss(0, 1)
        acceptance = min(1, target_pdf(proposal) / target_pdf(current))
        if random.random() < acceptance:
            current = proposal
        if i >= request.burn_in:
            samples.append(current)
    
    mean = sum(samples) / len(samples)
    variance = sum((x - mean)**2 for x in samples) / len(samples)
    
    return {"success": True, "target_mean": request.target_mean, "target_std": request.target_std, "estimated_mean": round(mean, 4), "estimated_std": round(math.sqrt(variance), 4), "n_samples": len(samples)}

@app.post("/likelihood")
async def compute_likelihood(data: List[float], distribution: str, params: Dict[str, float]):
    """计算数据的似然"""
    log_likelihood = 0
    
    if distribution == "normal":
        mean = params.get("mean", 0)
        std = params.get("std", 1)
        for x in data:
            log_likelihood += -0.5 * math.log(2 * math.pi * std**2) - 0.5 * ((x - mean) / std)**2
    elif distribution == "exponential":
        rate = 1 / params.get("scale", 1)
        for x in data:
            if x < 0:
                return {"success": False, "error": "Exponential requires non-negative data"}
            log_likelihood += math.log(rate) - rate * x
    else:
        raise HTTPException(status_code=400, detail=f"Unknown distribution: {distribution}")
    
    return {"success": True, "log_likelihood": round(log_likelihood, 4), "likelihood": round(math.exp(log_likelihood), 10)}

@app.post("/mcp/call")
async def mcp_call(request: dict):
    tool = request.get("tool", "")
    params = request.get("params", {})
    if tool == "bayes": return await bayes_theorem(BayesRequest(**params))
    elif tool == "sample": return await sample_distribution(SampleRequest(**params))
    elif tool == "mcmc": return await metropolis_hastings(MCMCRequest(**params))
    elif tool == "likelihood": return await compute_likelihood(params.get("data", []), params.get("distribution", "normal"), params.get("params", {}))
    raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8062)
