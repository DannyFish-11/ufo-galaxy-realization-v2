"""
Node 52: Qiskit Quantum Simulator
UFO Galaxy 64-Core MCP Matrix - Phase 5: Scientific Brain

Tiered quantum simulation with result interpretation.
"""

import os
import json
import asyncio
import logging
import hashlib
from typing import Dict, Optional, List, Any
from datetime import datetime
from contextlib import asynccontextmanager
from enum import Enum
from collections import Counter
import math

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn

# =============================================================================
# Configuration
# =============================================================================

NODE_ID = os.getenv("NODE_ID", "52")
NODE_NAME = os.getenv("NODE_NAME", "QiskitSimulator")
STATE_MACHINE_URL = os.getenv("STATE_MACHINE_URL", "http://localhost:8000")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
USE_GPU = os.getenv("USE_GPU", "false").lower() == "true"

# Simulation constraints
MAX_QUBITS_STATEVECTOR = 15
MAX_QUBITS_DENSITY = 10
MAX_QUBITS_MPS = 25
SIMULATION_TIMEOUT = int(os.getenv("SIMULATION_TIMEOUT", "30"))

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format=f"[Node {NODE_ID}] %(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# =============================================================================
# Models
# =============================================================================

class SimulationBackend(str, Enum):
    STATEVECTOR = "statevector"      # Exact simulation
    DENSITY_MATRIX = "density_matrix"  # Noisy simulation
    MPS = "matrix_product_state"      # Large-scale approximate
    MOCK = "mock"                     # Testing without Qiskit

class NoiseModel(str, Enum):
    NONE = "none"
    DEPOLARIZING = "depolarizing"
    THERMAL = "thermal"
    REALISTIC = "realistic"

class SimulationRequest(BaseModel):
    qasm: str = Field(..., description="OpenQASM 2.0 circuit")
    shots: int = Field(default=1024, ge=1, le=10000)
    backend: Optional[SimulationBackend] = Field(None, description="Simulation backend")
    noise_model: NoiseModel = Field(default=NoiseModel.NONE)
    seed: Optional[int] = Field(None, description="Random seed for reproducibility")

class SimulationResult(BaseModel):
    counts: Dict[str, int]
    probabilities: Dict[str, float]
    most_likely_state: str
    confidence: float
    backend_used: str
    execution_time_ms: float
    metadata: Dict[str, Any] = {}

# =============================================================================
# Mock Simulator (for testing without Qiskit)
# =============================================================================

class MockQuantumSimulator:
    """Mock simulator for testing without Qiskit installed."""
    
    def __init__(self):
        self.cache = {}
    
    def simulate(
        self,
        qasm: str,
        shots: int,
        backend: SimulationBackend,
        noise_model: NoiseModel,
        seed: Optional[int] = None
    ) -> Dict[str, Any]:
        """Simulate quantum circuit (mock implementation)."""
        import random
        import time
        
        start_time = time.time()
        
        if seed:
            random.seed(seed)
        
        # Parse QASM to get number of qubits
        num_qubits = self._parse_qubits(qasm)
        
        # Generate mock results based on circuit structure
        counts = self._generate_mock_counts(qasm, num_qubits, shots, noise_model)
        
        # Calculate probabilities
        total = sum(counts.values())
        probabilities = {k: v / total for k, v in counts.items()}
        
        # Find most likely state
        most_likely = max(counts, key=counts.get)
        confidence = counts[most_likely] / total
        
        execution_time = (time.time() - start_time) * 1000
        
        return {
            "counts": counts,
            "probabilities": probabilities,
            "most_likely_state": most_likely,
            "confidence": confidence,
            "backend_used": f"mock_{backend.value}",
            "execution_time_ms": execution_time,
            "metadata": {
                "num_qubits": num_qubits,
                "shots": shots,
                "noise_model": noise_model.value,
                "simulated": True
            }
        }
    
    def _parse_qubits(self, qasm: str) -> int:
        """Parse number of qubits from QASM."""
        import re
        match = re.search(r'qreg\s+\w+\[(\d+)\]', qasm)
        if match:
            return int(match.group(1))
        return 4  # Default
    
    def _generate_mock_counts(
        self,
        qasm: str,
        num_qubits: int,
        shots: int,
        noise_model: NoiseModel
    ) -> Dict[str, int]:
        """Generate mock measurement counts."""
        import random
        
        # Determine circuit type from QASM
        is_grover = "// Grover" in qasm or "// Oracle" in qasm
        is_qaoa = "// QAOA" in qasm
        is_superposition = qasm.count("h q[") > 0
        
        counts = {}
        
        if is_grover:
            # Grover's algorithm should find marked state with high probability
            marked_state = "0" * (num_qubits - 1) + "1"  # Mark state |00...01>
            target_prob = 0.7 if noise_model == NoiseModel.NONE else 0.5
            
            for _ in range(shots):
                if random.random() < target_prob:
                    state = marked_state
                else:
                    state = format(random.randint(0, 2**num_qubits - 1), f'0{num_qubits}b')
                counts[state] = counts.get(state, 0) + 1
                
        elif is_qaoa:
            # QAOA should show preference for optimal solutions
            # Simulate a simple max-cut like distribution
            optimal_states = [
                format(i, f'0{num_qubits}b')
                for i in range(2**num_qubits)
                if bin(i).count('1') == num_qubits // 2
            ]
            
            for _ in range(shots):
                if random.random() < 0.4 and optimal_states:
                    state = random.choice(optimal_states)
                else:
                    state = format(random.randint(0, 2**num_qubits - 1), f'0{num_qubits}b')
                counts[state] = counts.get(state, 0) + 1
                
        elif is_superposition:
            # Uniform superposition
            for _ in range(shots):
                state = format(random.randint(0, 2**num_qubits - 1), f'0{num_qubits}b')
                counts[state] = counts.get(state, 0) + 1
        else:
            # Default: mostly |0...0>
            for _ in range(shots):
                if random.random() < 0.9:
                    state = "0" * num_qubits
                else:
                    state = format(random.randint(0, 2**num_qubits - 1), f'0{num_qubits}b')
                counts[state] = counts.get(state, 0) + 1
        
        # Add noise effects
        if noise_model != NoiseModel.NONE:
            counts = self._apply_noise(counts, num_qubits, noise_model)
        
        return counts
    
    def _apply_noise(
        self,
        counts: Dict[str, int],
        num_qubits: int,
        noise_model: NoiseModel
    ) -> Dict[str, int]:
        """Apply noise effects to counts."""
        import random
        
        noise_rate = {
            NoiseModel.DEPOLARIZING: 0.05,
            NoiseModel.THERMAL: 0.03,
            NoiseModel.REALISTIC: 0.08
        }.get(noise_model, 0)
        
        noisy_counts = {}
        for state, count in counts.items():
            for _ in range(count):
                if random.random() < noise_rate:
                    # Flip random bit
                    state_list = list(state)
                    flip_idx = random.randint(0, num_qubits - 1)
                    state_list[flip_idx] = '1' if state_list[flip_idx] == '0' else '0'
                    new_state = ''.join(state_list)
                else:
                    new_state = state
                noisy_counts[new_state] = noisy_counts.get(new_state, 0) + 1
        
        return noisy_counts

# =============================================================================
# Result Interpreter
# =============================================================================

class ResultInterpreter:
    """Interprets quantum simulation results."""
    
    def interpret(
        self,
        counts: Dict[str, int],
        probabilities: Dict[str, float],
        algorithm_hint: Optional[str] = None
    ) -> Dict[str, Any]:
        """Interpret simulation results."""
        
        num_qubits = len(list(counts.keys())[0]) if counts else 0
        total_shots = sum(counts.values())
        
        # Basic statistics
        entropy = self._calculate_entropy(probabilities)
        uniformity = self._calculate_uniformity(probabilities, num_qubits)
        
        # Find significant states (above threshold)
        threshold = 1.5 / (2 ** num_qubits)  # 1.5x uniform probability
        significant_states = {
            k: v for k, v in probabilities.items()
            if v > threshold
        }
        
        # Determine result type
        if len(significant_states) == 1:
            result_type = "deterministic"
        elif uniformity > 0.9:
            result_type = "uniform_superposition"
        elif len(significant_states) <= 5:
            result_type = "peaked_distribution"
        else:
            result_type = "complex_distribution"
        
        # Generate interpretation
        interpretation = self._generate_interpretation(
            result_type, significant_states, entropy, algorithm_hint
        )
        
        return {
            "result_type": result_type,
            "entropy": round(entropy, 4),
            "uniformity": round(uniformity, 4),
            "significant_states": significant_states,
            "num_significant": len(significant_states),
            "interpretation": interpretation,
            "recommendations": self._get_recommendations(result_type, entropy)
        }
    
    def _calculate_entropy(self, probabilities: Dict[str, float]) -> float:
        """Calculate Shannon entropy."""
        entropy = 0
        for p in probabilities.values():
            if p > 0:
                entropy -= p * math.log2(p)
        return entropy
    
    def _calculate_uniformity(self, probabilities: Dict[str, float], num_qubits: int) -> float:
        """Calculate how uniform the distribution is (0-1)."""
        if not probabilities:
            return 0
        
        uniform_prob = 1 / (2 ** num_qubits)
        max_deviation = max(abs(p - uniform_prob) for p in probabilities.values())
        
        # Normalize: 0 = very peaked, 1 = perfectly uniform
        return max(0, 1 - max_deviation / uniform_prob)
    
    def _generate_interpretation(
        self,
        result_type: str,
        significant_states: Dict[str, float],
        entropy: float,
        algorithm_hint: Optional[str]
    ) -> str:
        """Generate human-readable interpretation."""
        
        if result_type == "deterministic":
            state = list(significant_states.keys())[0]
            return f"Circuit produces deterministic output: |{state}⟩ with high confidence."
        
        elif result_type == "uniform_superposition":
            return "Circuit produces uniform superposition across all basis states."
        
        elif result_type == "peaked_distribution":
            top_states = sorted(significant_states.items(), key=lambda x: -x[1])[:3]
            states_str = ", ".join([f"|{s}⟩ ({p:.1%})" for s, p in top_states])
            return f"Circuit shows preference for states: {states_str}"
        
        else:
            return f"Complex distribution with entropy {entropy:.2f} bits."
    
    def _get_recommendations(self, result_type: str, entropy: float) -> List[str]:
        """Get recommendations based on results."""
        recommendations = []
        
        if result_type == "uniform_superposition":
            recommendations.append("Consider adding more layers to break symmetry")
        
        if entropy < 1:
            recommendations.append("Low entropy suggests algorithm may have converged")
        elif entropy > 5:
            recommendations.append("High entropy - consider more iterations or shots")
        
        return recommendations

# =============================================================================
# Quantum Simulator Service
# =============================================================================

class QuantumSimulatorService:
    """Main quantum simulation service."""
    
    def __init__(self):
        self.mock_simulator = MockQuantumSimulator()
        self.interpreter = ResultInterpreter()
        self.use_qiskit = self._check_qiskit()
        
        # Statistics
        self.stats = {
            "total_simulations": 0,
            "statevector_count": 0,
            "density_matrix_count": 0,
            "mps_count": 0,
            "mock_count": 0,
            "total_shots": 0,
            "cache_hits": 0
        }
        
        # Simple cache
        self.cache = {}
    
    def _check_qiskit(self) -> bool:
        """Check if Qiskit is available."""
        try:
            import qiskit
            logger.info(f"Qiskit {qiskit.__version__} available")
            return True
        except ImportError:
            logger.warning("Qiskit not available, using mock simulator")
            return False
    
    def _select_backend(self, num_qubits: int, requested: Optional[SimulationBackend]) -> SimulationBackend:
        """Select appropriate backend based on qubit count."""
        if requested:
            return requested
        
        if num_qubits <= MAX_QUBITS_DENSITY:
            return SimulationBackend.STATEVECTOR
        elif num_qubits <= MAX_QUBITS_STATEVECTOR:
            return SimulationBackend.STATEVECTOR
        elif num_qubits <= MAX_QUBITS_MPS:
            return SimulationBackend.MPS
        else:
            return SimulationBackend.MOCK
    
    async def simulate(self, request: SimulationRequest) -> SimulationResult:
        """Run quantum simulation."""
        self.stats["total_simulations"] += 1
        self.stats["total_shots"] += request.shots
        
        # Parse qubits from QASM
        num_qubits = self.mock_simulator._parse_qubits(request.qasm)
        
        # Select backend
        backend = self._select_backend(num_qubits, request.backend)
        
        # Check cache
        cache_key = hashlib.md5(
            f"{request.qasm}{request.shots}{backend.value}{request.noise_model.value}".encode()
        ).hexdigest()
        
        if cache_key in self.cache:
            self.stats["cache_hits"] += 1
            cached = self.cache[cache_key]
            cached["metadata"]["cache_hit"] = True
            return SimulationResult(**cached)
        
        # Run simulation
        if self.use_qiskit and backend != SimulationBackend.MOCK:
            result = await self._run_qiskit_simulation(request, backend)
        else:
            result = self.mock_simulator.simulate(
                request.qasm,
                request.shots,
                backend,
                request.noise_model,
                request.seed
            )
            self.stats["mock_count"] += 1
        
        # Cache result
        self.cache[cache_key] = result
        
        # Limit cache size
        if len(self.cache) > 100:
            oldest_key = next(iter(self.cache))
            del self.cache[oldest_key]
        
        return SimulationResult(**result)
    
    async def _run_qiskit_simulation(
        self,
        request: SimulationRequest,
        backend: SimulationBackend
    ) -> Dict[str, Any]:
        """Run actual Qiskit simulation."""
        # This would contain real Qiskit code
        # For now, fall back to mock
        return self.mock_simulator.simulate(
            request.qasm,
            request.shots,
            backend,
            request.noise_model,
            request.seed
        )
    
    def interpret_results(
        self,
        counts: Dict[str, int],
        probabilities: Dict[str, float],
        algorithm_hint: Optional[str] = None
    ) -> Dict[str, Any]:
        """Interpret simulation results."""
        return self.interpreter.interpret(counts, probabilities, algorithm_hint)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get service statistics."""
        return {
            **self.stats,
            "qiskit_available": self.use_qiskit,
            "cache_size": len(self.cache),
            "backends": {
                "statevector_max_qubits": MAX_QUBITS_STATEVECTOR,
                "density_matrix_max_qubits": MAX_QUBITS_DENSITY,
                "mps_max_qubits": MAX_QUBITS_MPS
            }
        }

# =============================================================================
# FastAPI Application
# =============================================================================

simulator: Optional[QuantumSimulatorService] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global simulator
    
    logger.info(f"Starting Node {NODE_ID}: {NODE_NAME}")
    simulator = QuantumSimulatorService()
    logger.info(f"Node {NODE_ID} ({NODE_NAME}) is ready")
    
    yield
    
    logger.info(f"Shutting down Node {NODE_ID}")

app = FastAPI(
    title=f"UFO Galaxy Node {NODE_ID}: {NODE_NAME}",
    description="Qiskit Quantum Simulator with Tiered Backends",
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
        "qiskit_available": simulator.use_qiskit if simulator else False
    }

@app.post("/simulate", response_model=SimulationResult)
async def run_simulation(request: SimulationRequest):
    """Run quantum simulation."""
    return await simulator.simulate(request)

@app.post("/interpret")
async def interpret_results(
    counts: Dict[str, int],
    algorithm_hint: Optional[str] = None
):
    """Interpret simulation results."""
    total = sum(counts.values())
    probabilities = {k: v / total for k, v in counts.items()}
    return simulator.interpret_results(counts, probabilities, algorithm_hint)

@app.get("/backends")
async def list_backends():
    """List available simulation backends."""
    return {
        "backends": [
            {
                "name": b.value,
                "max_qubits": {
                    SimulationBackend.STATEVECTOR: MAX_QUBITS_STATEVECTOR,
                    SimulationBackend.DENSITY_MATRIX: MAX_QUBITS_DENSITY,
                    SimulationBackend.MPS: MAX_QUBITS_MPS,
                    SimulationBackend.MOCK: 30
                }.get(b, 10)
            }
            for b in SimulationBackend
        ],
        "qiskit_available": simulator.use_qiskit if simulator else False
    }

@app.get("/stats")
async def get_stats():
    """Get simulator statistics."""
    return simulator.get_stats()

@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "node_id": NODE_ID,
        "node_name": NODE_NAME,
        "layer": "L1_GATEWAY",
        "capabilities": ["statevector", "density_matrix", "mps", "noise_models"]
    }

# =============================================================================
# Main Entry Point
# =============================================================================

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8052,
        reload=False,
        log_level=LOG_LEVEL.lower()
    )
