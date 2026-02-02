"""
Node 57: QuantumCloud - 量子云计算接口
"""
import os, math, random
from datetime import datetime
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Node 57 - QuantumCloud", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

IBM_QUANTUM_TOKEN = os.getenv("IBM_QUANTUM_TOKEN", "")

qiskit = None
try:
    from qiskit import QuantumCircuit, transpile
    from qiskit_ibm_runtime import QiskitRuntimeService, Sampler
    qiskit = True
except ImportError:
    pass

class CircuitRequest(BaseModel):
    qubits: int = 2
    gates: List[Dict[str, Any]] = []
    shots: int = 1024

class GroverRequest(BaseModel):
    n_qubits: int = 3
    target_state: str = "101"
    shots: int = 1024

class QAOARequest(BaseModel):
    graph_edges: List[List[int]]
    p: int = 1
    shots: int = 1024

@app.get("/health")
async def health():
    return {"status": "healthy" if qiskit else "degraded", "node_id": "57", "name": "QuantumCloud", "qiskit_available": qiskit is not None, "ibm_token_set": bool(IBM_QUANTUM_TOKEN), "timestamp": datetime.now().isoformat()}

@app.post("/run_circuit")
async def run_circuit(request: CircuitRequest):
    """运行量子电路"""
    if not qiskit:
        raise HTTPException(status_code=503, detail="qiskit not installed")
    
    from qiskit import QuantumCircuit
    qc = QuantumCircuit(request.qubits, request.qubits)
    
    for gate in request.gates:
        gate_type = gate.get("type", "").lower()
        target = gate.get("target", 0)
        control = gate.get("control")
        
        if gate_type == "h":
            qc.h(target)
        elif gate_type == "x":
            qc.x(target)
        elif gate_type == "y":
            qc.y(target)
        elif gate_type == "z":
            qc.z(target)
        elif gate_type == "cx" and control is not None:
            qc.cx(control, target)
        elif gate_type == "cz" and control is not None:
            qc.cz(control, target)
        elif gate_type == "rx":
            qc.rx(gate.get("angle", math.pi/2), target)
        elif gate_type == "ry":
            qc.ry(gate.get("angle", math.pi/2), target)
        elif gate_type == "rz":
            qc.rz(gate.get("angle", math.pi/2), target)
    
    qc.measure_all()
    
    # 本地模拟
    from qiskit_aer import AerSimulator
    simulator = AerSimulator()
    compiled = transpile(qc, simulator)
    job = simulator.run(compiled, shots=request.shots)
    result = job.result()
    counts = result.get_counts()
    
    return {"success": True, "counts": counts, "shots": request.shots, "circuit": qc.draw(output="text").__str__()}

@app.post("/bell_state")
async def create_bell_state(shots: int = 1024):
    """创建 Bell 态"""
    if not qiskit:
        raise HTTPException(status_code=503, detail="qiskit not installed")
    
    from qiskit import QuantumCircuit
    from qiskit_aer import AerSimulator
    
    qc = QuantumCircuit(2, 2)
    qc.h(0)
    qc.cx(0, 1)
    qc.measure_all()
    
    simulator = AerSimulator()
    compiled = transpile(qc, simulator)
    job = simulator.run(compiled, shots=shots)
    counts = job.result().get_counts()
    
    return {"success": True, "state": "Bell State (|00> + |11>)/sqrt(2)", "counts": counts}

@app.post("/grover")
async def grover_search(request: GroverRequest):
    """Grover 搜索算法"""
    if not qiskit:
        raise HTTPException(status_code=503, detail="qiskit not installed")
    
    from qiskit import QuantumCircuit
    from qiskit_aer import AerSimulator
    
    n = request.n_qubits
    qc = QuantumCircuit(n, n)
    
    # 初始化
    for i in range(n):
        qc.h(i)
    
    # Oracle (标记目标状态)
    target = request.target_state
    for i, bit in enumerate(reversed(target)):
        if bit == "0":
            qc.x(i)
    qc.h(n-1)
    qc.mcx(list(range(n-1)), n-1)
    qc.h(n-1)
    for i, bit in enumerate(reversed(target)):
        if bit == "0":
            qc.x(i)
    
    # Diffusion
    for i in range(n):
        qc.h(i)
        qc.x(i)
    qc.h(n-1)
    qc.mcx(list(range(n-1)), n-1)
    qc.h(n-1)
    for i in range(n):
        qc.x(i)
        qc.h(i)
    
    qc.measure_all()
    
    simulator = AerSimulator()
    compiled = transpile(qc, simulator)
    job = simulator.run(compiled, shots=request.shots)
    counts = job.result().get_counts()
    
    return {"success": True, "target": request.target_state, "counts": counts}

@app.get("/backends")
async def list_backends():
    """列出可用的量子后端"""
    if not qiskit or not IBM_QUANTUM_TOKEN:
        return {"success": True, "backends": ["local_simulator"], "note": "IBM Quantum not configured"}
    
    try:
        from qiskit_ibm_runtime import QiskitRuntimeService
        service = QiskitRuntimeService(channel="ibm_quantum", token=IBM_QUANTUM_TOKEN)
        backends = [b.name for b in service.backends()]
        return {"success": True, "backends": ["local_simulator"] + backends}
    except Exception as e:
        return {"success": True, "backends": ["local_simulator"], "error": str(e)}

@app.post("/mcp/call")
async def mcp_call(request: dict):
    tool = request.get("tool", "")
    params = request.get("params", {})
    if tool == "run_circuit": return await run_circuit(CircuitRequest(**params))
    elif tool == "bell_state": return await create_bell_state(params.get("shots", 1024))
    elif tool == "grover": return await grover_search(GroverRequest(**params))
    elif tool == "backends": return await list_backends()
    raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8057)
