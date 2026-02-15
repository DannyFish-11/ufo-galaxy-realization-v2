"""
Node 51: Quantum Task Dispatcher
UFO Galaxy 64-Core MCP Matrix - Phase 5: Scientific Brain

Natural Language to Quantum Circuit (NL2QC) translation and dispatch.
"""

import os
import json
import asyncio
import logging
import re
import hashlib
from typing import Dict, Optional, List, Any, Tuple
from datetime import datetime
from contextlib import asynccontextmanager
from enum import Enum
from dataclasses import dataclass

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn
import httpx

# =============================================================================
# Configuration
# =============================================================================

NODE_ID = os.getenv("NODE_ID", "51")
NODE_NAME = os.getenv("NODE_NAME", "QuantumDispatcher")
STATE_MACHINE_URL = os.getenv("STATE_MACHINE_URL", "http://localhost:8000")
SIMULATOR_URL = os.getenv("SIMULATOR_URL", "http://localhost:8052")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Quantum constraints
MAX_QUBITS = int(os.getenv("MAX_QUBITS", "20"))
MAX_CIRCUIT_DEPTH = int(os.getenv("MAX_CIRCUIT_DEPTH", "100"))
SIMULATION_TIMEOUT = int(os.getenv("SIMULATION_TIMEOUT", "30"))

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format=f"[Node {NODE_ID}] %(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# =============================================================================
# Models
# =============================================================================

class QuantumAlgorithm(str, Enum):
    QAOA = "qaoa"           # Optimization problems
    GROVER = "grover"       # Search problems
    VQE = "vqe"             # Eigenvalue problems
    QNN = "qnn"             # Machine learning
    QSVM = "qsvm"           # Classification
    BERNSTEIN_VAZIRANI = "bv"  # Hidden string
    DEUTSCH_JOZSA = "dj"    # Function analysis

class ProblemType(str, Enum):
    OPTIMIZATION = "optimization"
    SEARCH = "search"
    SAMPLING = "sampling"
    MACHINE_LEARNING = "machine_learning"
    CRYPTOGRAPHY = "cryptography"
    SIMULATION = "simulation"

@dataclass
class QuantumCircuit:
    """Represents a quantum circuit ready for simulation."""
    qasm: str
    num_qubits: int
    depth: int
    algorithm: QuantumAlgorithm
    parameters: Dict[str, Any]
    problem_mapping: Dict[str, Any]
    expected_complexity: str
    circuit_hash: str

class QuantumRequest(BaseModel):
    prompt: str = Field(..., description="Natural language problem description")
    problem_type: Optional[ProblemType] = Field(None, description="Explicit problem type")
    constraints: Dict[str, Any] = Field(default={}, description="Problem constraints")
    max_qubits: int = Field(default=10, ge=1, le=MAX_QUBITS)
    shots: int = Field(default=1024, ge=1, le=10000)
    optimization_level: int = Field(default=1, ge=0, le=3)

class QuantumResponse(BaseModel):
    circuit: Dict[str, Any]
    problem_analysis: Dict[str, Any]
    recommended_algorithm: str
    estimated_runtime_ms: int
    warnings: List[str] = []

# =============================================================================
# Problem Analyzer
# =============================================================================

class ProblemAnalyzer:
    """Analyzes natural language to identify quantum-suitable problems."""
    
    # Problem type patterns
    OPTIMIZATION_PATTERNS = [
        r"optim\w*", r"minimize", r"maximize", r"best\s+route",
        r"shortest\s+path", r"traveling\s+salesman", r"tsp",
        r"knapsack", r"scheduling", r"allocation", r"assignment"
    ]
    
    SEARCH_PATTERNS = [
        r"find\s+\w+\s+in", r"search\s+for", r"locate",
        r"database\s+search", r"unstructured\s+search",
        r"needle\s+in\s+haystack", r"satisfiability"
    ]
    
    SAMPLING_PATTERNS = [
        r"sample", r"distribution", r"probability",
        r"monte\s+carlo", r"random\s+walk", r"eigenvalue",
        r"ground\s+state", r"energy\s+level"
    ]
    
    ML_PATTERNS = [
        r"classif\w*", r"cluster\w*", r"neural\s+network",
        r"machine\s+learning", r"pattern\s+recognition",
        r"feature\s+map", r"kernel"
    ]
    
    def __init__(self):
        self.patterns = {
            ProblemType.OPTIMIZATION: [re.compile(p, re.IGNORECASE) for p in self.OPTIMIZATION_PATTERNS],
            ProblemType.SEARCH: [re.compile(p, re.IGNORECASE) for p in self.SEARCH_PATTERNS],
            ProblemType.SAMPLING: [re.compile(p, re.IGNORECASE) for p in self.SAMPLING_PATTERNS],
            ProblemType.MACHINE_LEARNING: [re.compile(p, re.IGNORECASE) for p in self.ML_PATTERNS],
        }
    
    def analyze(self, prompt: str, explicit_type: Optional[ProblemType] = None) -> Dict[str, Any]:
        """Analyze problem and extract parameters."""
        
        # Use explicit type if provided
        if explicit_type:
            problem_type = explicit_type
            confidence = 1.0
        else:
            problem_type, confidence = self._detect_problem_type(prompt)
        
        # Extract numerical parameters
        numbers = self._extract_numbers(prompt)
        
        # Estimate problem size
        problem_size = self._estimate_problem_size(prompt, numbers)
        
        # Determine recommended algorithm
        algorithm = self._recommend_algorithm(problem_type, problem_size)
        
        # Calculate qubit requirements
        qubit_estimate = self._estimate_qubits(problem_type, problem_size, algorithm)
        
        return {
            "problem_type": problem_type.value,
            "confidence": confidence,
            "extracted_numbers": numbers,
            "problem_size": problem_size,
            "recommended_algorithm": algorithm.value,
            "qubit_estimate": qubit_estimate,
            "is_quantum_suitable": qubit_estimate <= MAX_QUBITS,
            "classical_alternative": self._suggest_classical_alternative(problem_type)
        }
    
    def _detect_problem_type(self, prompt: str) -> Tuple[ProblemType, float]:
        """Detect problem type from prompt."""
        scores = {}
        
        for ptype, patterns in self.patterns.items():
            score = sum(1 for p in patterns if p.search(prompt))
            scores[ptype] = score
        
        if not any(scores.values()):
            return ProblemType.OPTIMIZATION, 0.3  # Default
        
        best_type = max(scores, key=scores.get)
        total = sum(scores.values())
        confidence = scores[best_type] / total if total > 0 else 0.5
        
        return best_type, confidence
    
    def _extract_numbers(self, prompt: str) -> List[int]:
        """Extract numerical values from prompt."""
        numbers = re.findall(r'\b(\d+)\b', prompt)
        return [int(n) for n in numbers if int(n) < 1000]
    
    def _estimate_problem_size(self, prompt: str, numbers: List[int]) -> int:
        """Estimate problem size (number of variables/items)."""
        if numbers:
            return max(numbers)
        
        # Heuristic based on keywords
        size_keywords = {
            "small": 5, "few": 5, "simple": 5,
            "medium": 10, "moderate": 10,
            "large": 20, "many": 20, "complex": 20
        }
        
        for keyword, size in size_keywords.items():
            if keyword in prompt.lower():
                return size
        
        return 8  # Default
    
    def _recommend_algorithm(self, problem_type: ProblemType, size: int) -> QuantumAlgorithm:
        """Recommend quantum algorithm based on problem type."""
        algorithm_map = {
            ProblemType.OPTIMIZATION: QuantumAlgorithm.QAOA,
            ProblemType.SEARCH: QuantumAlgorithm.GROVER,
            ProblemType.SAMPLING: QuantumAlgorithm.VQE,
            ProblemType.MACHINE_LEARNING: QuantumAlgorithm.QNN,
            ProblemType.CRYPTOGRAPHY: QuantumAlgorithm.BERNSTEIN_VAZIRANI,
            ProblemType.SIMULATION: QuantumAlgorithm.VQE,
        }
        return algorithm_map.get(problem_type, QuantumAlgorithm.QAOA)
    
    def _estimate_qubits(self, problem_type: ProblemType, size: int, algorithm: QuantumAlgorithm) -> int:
        """Estimate required qubits."""
        # Different algorithms have different qubit requirements
        if algorithm == QuantumAlgorithm.GROVER:
            return max(3, int(size).bit_length())  # log2(N) qubits
        elif algorithm == QuantumAlgorithm.QAOA:
            return min(size, MAX_QUBITS)  # One qubit per variable
        elif algorithm == QuantumAlgorithm.VQE:
            return min(size * 2, MAX_QUBITS)  # 2 qubits per orbital
        else:
            return min(size, MAX_QUBITS)
    
    def _suggest_classical_alternative(self, problem_type: ProblemType) -> str:
        """Suggest classical alternative if quantum is not suitable."""
        alternatives = {
            ProblemType.OPTIMIZATION: "Simulated Annealing or Genetic Algorithm",
            ProblemType.SEARCH: "Binary Search or Hash Table",
            ProblemType.SAMPLING: "MCMC or Importance Sampling",
            ProblemType.MACHINE_LEARNING: "Classical Neural Network",
        }
        return alternatives.get(problem_type, "Classical heuristic")

# =============================================================================
# Circuit Generator
# =============================================================================

class CircuitGenerator:
    """Generates quantum circuits from problem specifications."""
    
    def generate(
        self,
        problem_type: ProblemType,
        algorithm: QuantumAlgorithm,
        num_qubits: int,
        parameters: Dict[str, Any],
        optimization_level: int = 1
    ) -> QuantumCircuit:
        """Generate quantum circuit for the problem."""
        
        # Generate QASM based on algorithm
        if algorithm == QuantumAlgorithm.QAOA:
            qasm, depth = self._generate_qaoa(num_qubits, parameters)
        elif algorithm == QuantumAlgorithm.GROVER:
            qasm, depth = self._generate_grover(num_qubits, parameters)
        elif algorithm == QuantumAlgorithm.VQE:
            qasm, depth = self._generate_vqe(num_qubits, parameters)
        elif algorithm == QuantumAlgorithm.QNN:
            qasm, depth = self._generate_qnn(num_qubits, parameters)
        else:
            qasm, depth = self._generate_generic(num_qubits, parameters)
        
        # Optimize circuit if requested
        if optimization_level > 0:
            qasm, depth = self._optimize_circuit(qasm, depth, optimization_level)
        
        # Calculate circuit hash
        circuit_hash = hashlib.sha256(qasm.encode()).hexdigest()[:16]
        
        return QuantumCircuit(
            qasm=qasm,
            num_qubits=num_qubits,
            depth=depth,
            algorithm=algorithm,
            parameters=parameters,
            problem_mapping={"type": problem_type.value},
            expected_complexity=self._calculate_complexity(algorithm, num_qubits),
            circuit_hash=circuit_hash
        )
    
    def _generate_qaoa(self, num_qubits: int, params: Dict) -> Tuple[str, int]:
        """Generate QAOA circuit for optimization."""
        layers = params.get("layers", 2)
        
        qasm = f"""OPENQASM 2.0;
include "qelib1.inc";
qreg q[{num_qubits}];
creg c[{num_qubits}];

// Initial superposition
"""
        for i in range(num_qubits):
            qasm += f"h q[{i}];\n"
        
        qasm += "\n// QAOA layers\n"
        for layer in range(layers):
            # Cost layer (ZZ interactions)
            for i in range(num_qubits - 1):
                qasm += f"cx q[{i}], q[{i+1}];\n"
                qasm += f"rz(0.5) q[{i+1}];\n"
                qasm += f"cx q[{i}], q[{i+1}];\n"
            
            # Mixer layer (X rotations)
            for i in range(num_qubits):
                qasm += f"rx(0.5) q[{i}];\n"
        
        qasm += "\n// Measurement\n"
        for i in range(num_qubits):
            qasm += f"measure q[{i}] -> c[{i}];\n"
        
        depth = layers * (3 * (num_qubits - 1) + num_qubits) + num_qubits + num_qubits
        return qasm, depth
    
    def _generate_grover(self, num_qubits: int, params: Dict) -> Tuple[str, int]:
        """Generate Grover's search circuit."""
        iterations = params.get("iterations", int((3.14159 / 4) * (2 ** (num_qubits / 2))))
        iterations = min(iterations, 10)  # Cap iterations
        
        qasm = f"""OPENQASM 2.0;
include "qelib1.inc";
qreg q[{num_qubits}];
creg c[{num_qubits}];

// Initial superposition
"""
        for i in range(num_qubits):
            qasm += f"h q[{i}];\n"
        
        qasm += "\n// Grover iterations\n"
        for _ in range(iterations):
            # Oracle (placeholder - marks target state)
            qasm += f"// Oracle\n"
            qasm += f"z q[{num_qubits-1}];\n"
            
            # Diffusion operator
            qasm += f"// Diffusion\n"
            for i in range(num_qubits):
                qasm += f"h q[{i}];\n"
                qasm += f"x q[{i}];\n"
            
            # Multi-controlled Z
            if num_qubits >= 2:
                qasm += f"h q[{num_qubits-1}];\n"
                qasm += f"cx q[0], q[{num_qubits-1}];\n"
                qasm += f"h q[{num_qubits-1}];\n"
            
            for i in range(num_qubits):
                qasm += f"x q[{i}];\n"
                qasm += f"h q[{i}];\n"
        
        qasm += "\n// Measurement\n"
        for i in range(num_qubits):
            qasm += f"measure q[{i}] -> c[{i}];\n"
        
        depth = num_qubits + iterations * (1 + 4 * num_qubits + 3) + num_qubits
        return qasm, depth
    
    def _generate_vqe(self, num_qubits: int, params: Dict) -> Tuple[str, int]:
        """Generate VQE ansatz circuit."""
        layers = params.get("layers", 2)
        
        qasm = f"""OPENQASM 2.0;
include "qelib1.inc";
qreg q[{num_qubits}];
creg c[{num_qubits}];

// Hardware-efficient ansatz
"""
        for layer in range(layers):
            # Single-qubit rotations
            for i in range(num_qubits):
                qasm += f"ry(0.5) q[{i}];\n"
                qasm += f"rz(0.5) q[{i}];\n"
            
            # Entangling layer
            for i in range(num_qubits - 1):
                qasm += f"cx q[{i}], q[{i+1}];\n"
        
        qasm += "\n// Measurement\n"
        for i in range(num_qubits):
            qasm += f"measure q[{i}] -> c[{i}];\n"
        
        depth = layers * (2 * num_qubits + (num_qubits - 1)) + num_qubits
        return qasm, depth
    
    def _generate_qnn(self, num_qubits: int, params: Dict) -> Tuple[str, int]:
        """Generate quantum neural network circuit."""
        return self._generate_vqe(num_qubits, params)  # Similar structure
    
    def _generate_generic(self, num_qubits: int, params: Dict) -> Tuple[str, int]:
        """Generate generic quantum circuit."""
        qasm = f"""OPENQASM 2.0;
include "qelib1.inc";
qreg q[{num_qubits}];
creg c[{num_qubits}];

// Generic circuit
"""
        for i in range(num_qubits):
            qasm += f"h q[{i}];\n"
        
        for i in range(num_qubits):
            qasm += f"measure q[{i}] -> c[{i}];\n"
        
        return qasm, num_qubits * 2
    
    def _optimize_circuit(self, qasm: str, depth: int, level: int) -> Tuple[str, int]:
        """Optimize circuit (placeholder for real transpilation)."""
        # In production, this would use Qiskit's transpiler
        optimized_depth = int(depth * (1 - 0.1 * level))
        return qasm, optimized_depth
    
    def _calculate_complexity(self, algorithm: QuantumAlgorithm, num_qubits: int) -> str:
        """Calculate expected computational complexity."""
        complexity_map = {
            QuantumAlgorithm.QAOA: f"O(2^{num_qubits})",
            QuantumAlgorithm.GROVER: f"O(√2^{num_qubits})",
            QuantumAlgorithm.VQE: f"O(poly({num_qubits}))",
            QuantumAlgorithm.QNN: f"O(poly({num_qubits}))",
        }
        return complexity_map.get(algorithm, f"O(2^{num_qubits})")

# =============================================================================
# Quantum Dispatcher
# =============================================================================

class QuantumDispatcher:
    """Main dispatcher for quantum tasks."""
    
    def __init__(self, simulator_url: str):
        self.simulator_url = simulator_url
        self.analyzer = ProblemAnalyzer()
        self.generator = CircuitGenerator()
        self.http_client = httpx.AsyncClient(timeout=SIMULATION_TIMEOUT)
        
        # Statistics
        self.stats = {
            "total_requests": 0,
            "successful_dispatches": 0,
            "classical_fallbacks": 0
        }
    
    async def dispatch(self, request: QuantumRequest) -> QuantumResponse:
        """Dispatch a quantum computation request."""
        self.stats["total_requests"] += 1
        warnings = []
        
        # Analyze problem
        analysis = self.analyzer.analyze(request.prompt, request.problem_type)
        
        # Check if quantum is suitable
        if not analysis["is_quantum_suitable"]:
            warnings.append(
                f"Problem size ({analysis['qubit_estimate']} qubits) exceeds limit ({MAX_QUBITS}). "
                f"Consider: {analysis['classical_alternative']}"
            )
            # Reduce to max qubits
            analysis["qubit_estimate"] = MAX_QUBITS
        
        # Determine final qubit count
        num_qubits = min(request.max_qubits, analysis["qubit_estimate"])
        
        # Generate circuit
        algorithm = QuantumAlgorithm(analysis["recommended_algorithm"])
        circuit = self.generator.generate(
            problem_type=ProblemType(analysis["problem_type"]),
            algorithm=algorithm,
            num_qubits=num_qubits,
            parameters={
                "layers": 2,
                "shots": request.shots,
                **request.constraints
            },
            optimization_level=request.optimization_level
        )
        
        # Estimate runtime
        estimated_runtime = self._estimate_runtime(circuit)
        
        if estimated_runtime > SIMULATION_TIMEOUT * 1000:
            warnings.append(
                f"Estimated runtime ({estimated_runtime}ms) may exceed timeout ({SIMULATION_TIMEOUT}s)"
            )
        
        self.stats["successful_dispatches"] += 1
        
        return QuantumResponse(
            circuit={
                "qasm": circuit.qasm,
                "num_qubits": circuit.num_qubits,
                "depth": circuit.depth,
                "algorithm": circuit.algorithm.value,
                "circuit_hash": circuit.circuit_hash,
                "expected_complexity": circuit.expected_complexity
            },
            problem_analysis=analysis,
            recommended_algorithm=algorithm.value,
            estimated_runtime_ms=estimated_runtime,
            warnings=warnings
        )
    
    def _estimate_runtime(self, circuit: QuantumCircuit) -> int:
        """Estimate simulation runtime in milliseconds."""
        # Rough estimate: 2^n * depth * constant
        base_time = (2 ** circuit.num_qubits) * circuit.depth * 0.01
        return int(min(base_time, SIMULATION_TIMEOUT * 1000))
    
    async def get_stats(self) -> Dict[str, Any]:
        """Get dispatcher statistics."""
        return {
            **self.stats,
            "max_qubits": MAX_QUBITS,
            "max_depth": MAX_CIRCUIT_DEPTH,
            "timeout_seconds": SIMULATION_TIMEOUT
        }

# =============================================================================
# FastAPI Application
# =============================================================================

dispatcher: Optional[QuantumDispatcher] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global dispatcher
    
    logger.info(f"Starting Node {NODE_ID}: {NODE_NAME}")
    dispatcher = QuantumDispatcher(SIMULATOR_URL)
    logger.info(f"Node {NODE_ID} ({NODE_NAME}) is ready")
    
    yield
    
    logger.info(f"Shutting down Node {NODE_ID}")
    if dispatcher:
        await dispatcher.http_client.aclose()

app = FastAPI(
    title=f"UFO Galaxy Node {NODE_ID}: {NODE_NAME}",
    description="Quantum Task Dispatcher - NL2QC Translation",
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
        "max_qubits": MAX_QUBITS
    }

@app.post("/dispatch", response_model=QuantumResponse)
async def dispatch_quantum_task(request: QuantumRequest):
    """Dispatch a quantum computation task."""
    return await dispatcher.dispatch(request)

@app.post("/analyze")
async def analyze_problem(prompt: str, problem_type: Optional[ProblemType] = None):
    """Analyze a problem without generating circuit."""
    analysis = dispatcher.analyzer.analyze(prompt, problem_type)
    return {"prompt": prompt, "analysis": analysis}

@app.get("/algorithms")
async def list_algorithms():
    """List available quantum algorithms."""
    return {
        "algorithms": [
            {"name": a.value, "description": _get_algorithm_description(a)}
            for a in QuantumAlgorithm
        ]
    }

@app.get("/stats")
async def get_stats():
    """Get dispatcher statistics."""
    return await dispatcher.get_stats()

@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "node_id": NODE_ID,
        "node_name": NODE_NAME,
        "layer": "L1_GATEWAY",
        "capabilities": ["NL2QC", "QAOA", "Grover", "VQE", "QNN"]
    }

def _get_algorithm_description(algo: QuantumAlgorithm) -> str:
    """Get algorithm description."""
    descriptions = {
        QuantumAlgorithm.QAOA: "Quantum Approximate Optimization Algorithm - for combinatorial optimization",
        QuantumAlgorithm.GROVER: "Grover's Algorithm - for unstructured search (quadratic speedup)",
        QuantumAlgorithm.VQE: "Variational Quantum Eigensolver - for finding ground state energies",
        QuantumAlgorithm.QNN: "Quantum Neural Network - for machine learning tasks",
        QuantumAlgorithm.QSVM: "Quantum Support Vector Machine - for classification",
        QuantumAlgorithm.BERNSTEIN_VAZIRANI: "Bernstein-Vazirani Algorithm - for hidden string problems",
        QuantumAlgorithm.DEUTSCH_JOZSA: "Deutsch-Jozsa Algorithm - for function analysis",
    }
    return descriptions.get(algo, "Quantum algorithm")

# =============================================================================
# Main Entry Point
# =============================================================================

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8051,
        reload=False,
        log_level=LOG_LEVEL.lower()
    )
