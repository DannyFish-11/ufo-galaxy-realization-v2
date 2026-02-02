"""
Node 68: Security Enforcer
UFO Galaxy 64-Core MCP Matrix - DeepSeek Audited Architecture

Enforces access control rules between nodes.
Validates that only authorized nodes can communicate with each other.
"""

import os
import json
import logging
from typing import Dict, List, Optional
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn
import httpx

# =============================================================================
# Configuration
# =============================================================================

NODE_ID = os.getenv("NODE_ID", "68")
NODE_NAME = os.getenv("NODE_NAME", "SecurityEnforcer")
STATE_MACHINE_URL = os.getenv("STATE_MACHINE_URL", "http://localhost:8000")
WHITELIST_PATH = os.getenv("WHITELIST_PATH", "/app/whitelist.json")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format=f"[Node {NODE_ID}] %(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# =============================================================================
# Models
# =============================================================================

class AccessCheckRequest(BaseModel):
    source_node: str
    target_node: str
    action: str = "call"
    resource: Optional[str] = None

class AccessCheckResponse(BaseModel):
    allowed: bool
    reason: str
    rule_matched: Optional[str] = None

class SecurityEvent(BaseModel):
    timestamp: str
    event_type: str
    source_node: str
    target_node: Optional[str] = None
    action: str
    allowed: bool
    reason: str

# =============================================================================
# Security Rules Engine
# =============================================================================

class SecurityEnforcer:
    """
    Enforces the UFO Galaxy security rules.
    
    Core Rules (from DeepSeek Audit):
    1. Layer 3 nodes CANNOT talk to each other
    2. Layer 3 nodes CANNOT talk to the Internet
    3. ALL Hardware requests MUST pass through Node 50
    4. ALL Global State MUST sync via Node 00
    """
    
    # Layer definitions (immutable)
    LAYERS = {
        "L0_KERNEL": ["00", "03", "04", "65", "66", "67", "68"],
        "L1_GATEWAY": ["01", "02", "50", "58"],
        "L2_TOOLS": ["06", "07", "08", "09", "10", "11", "12", "13", "14", "15",
                     "20", "21", "22", "23", "24", "25"],
        "L3_PHYSICAL": ["33", "34", "39", "41", "45", "49", "51", "52", "53",
                        "54", "55", "56", "57", "59", "60", "61", "62", "63"]
    }
    
    # Hardware nodes that can only be accessed via Node 50
    HARDWARE_NODES = ["33", "34", "39", "41", "45", "49", "51", "52", "53",
                      "54", "55", "56", "57", "59", "60", "61", "62", "63"]
    
    def __init__(self, whitelist_path: str = None):
        self.whitelist = self._load_whitelist(whitelist_path)
        self.security_events: List[SecurityEvent] = []
        self.max_events = 1000
        
        logger.info("Security Enforcer initialized")
        logger.info(f"Loaded {len(self.whitelist.get('rules', []))} custom rules")
    
    def _load_whitelist(self, path: str) -> Dict:
        """Load whitelist configuration."""
        default_whitelist = {
            "rules": [
                # Node 50 can access all hardware nodes
                {"source": "50", "target": "33", "action": "*", "allow": True},
                {"source": "50", "target": "34", "action": "*", "allow": True},
                {"source": "50", "target": "39", "action": "*", "allow": True},
                {"source": "50", "target": "41", "action": "*", "allow": True},
                {"source": "50", "target": "45", "action": "*", "allow": True},
                {"source": "50", "target": "49", "action": "*", "allow": True},
                
                # Node 58 can access Node 50 (for hardware requests)
                {"source": "58", "target": "50", "action": "*", "allow": True},
                
                # All nodes can access Node 00 (state machine)
                {"source": "*", "target": "00", "action": "*", "allow": True},
                
                # All nodes can access Node 68 (security check)
                {"source": "*", "target": "68", "action": "*", "allow": True},
                
                # Gateway nodes can access tool nodes
                {"source": "50", "target": "L2_TOOLS", "action": "*", "allow": True},
                {"source": "58", "target": "L2_TOOLS", "action": "*", "allow": True},
            ],
            "deny_rules": [
                # L3 nodes cannot talk to each other
                {"source": "L3_PHYSICAL", "target": "L3_PHYSICAL", "action": "*", "allow": False},
                
                # L3 nodes cannot access external services
                {"source": "L3_PHYSICAL", "target": "external", "action": "*", "allow": False},
            ]
        }
        
        if path and os.path.exists(path):
            try:
                with open(path, 'r') as f:
                    custom_whitelist = json.load(f)
                    # Merge with defaults
                    default_whitelist["rules"].extend(custom_whitelist.get("rules", []))
                    default_whitelist["deny_rules"].extend(custom_whitelist.get("deny_rules", []))
            except Exception as e:
                logger.warning(f"Failed to load custom whitelist: {e}")
        
        return default_whitelist
    
    def get_node_layer(self, node_id: str) -> Optional[str]:
        """Get the layer of a node."""
        for layer, nodes in self.LAYERS.items():
            if node_id in nodes:
                return layer
        return None
    
    def check_access(self, source_node: str, target_node: str, action: str = "call") -> AccessCheckResponse:
        """
        Check if source_node is allowed to access target_node.
        
        Returns AccessCheckResponse with allowed status and reason.
        """
        source_layer = self.get_node_layer(source_node)
        target_layer = self.get_node_layer(target_node)
        
        # Rule 1: L3 nodes cannot talk to each other
        if source_layer == "L3_PHYSICAL" and target_layer == "L3_PHYSICAL":
            self._log_event(source_node, target_node, action, False, "L3 isolation rule")
            return AccessCheckResponse(
                allowed=False,
                reason="Layer 3 nodes cannot communicate with each other (Security Rule #1)",
                rule_matched="L3_ISOLATION"
            )
        
        # Rule 3: Hardware requests must go through Node 50
        if target_node in self.HARDWARE_NODES and source_node != "50":
            self._log_event(source_node, target_node, action, False, "Hardware gateway rule")
            return AccessCheckResponse(
                allowed=False,
                reason=f"Hardware node {target_node} can only be accessed via Node 50 (Security Rule #3)",
                rule_matched="HARDWARE_GATEWAY"
            )
        
        # Check explicit allow rules
        for rule in self.whitelist.get("rules", []):
            if self._rule_matches(rule, source_node, target_node, action, source_layer, target_layer):
                if rule.get("allow", True):
                    self._log_event(source_node, target_node, action, True, f"Rule: {rule}")
                    return AccessCheckResponse(
                        allowed=True,
                        reason="Access allowed by whitelist rule",
                        rule_matched=str(rule)
                    )
        
        # Check explicit deny rules
        for rule in self.whitelist.get("deny_rules", []):
            if self._rule_matches(rule, source_node, target_node, action, source_layer, target_layer):
                self._log_event(source_node, target_node, action, False, f"Deny rule: {rule}")
                return AccessCheckResponse(
                    allowed=False,
                    reason="Access denied by security rule",
                    rule_matched=str(rule)
                )
        
        # Default: Allow same layer communication, deny cross-layer unless explicitly allowed
        if source_layer == target_layer:
            # Same layer communication is generally allowed (except L3)
            self._log_event(source_node, target_node, action, True, "Same layer default")
            return AccessCheckResponse(
                allowed=True,
                reason="Same layer communication allowed by default",
                rule_matched="SAME_LAYER_DEFAULT"
            )
        
        # Adjacent layer communication
        layer_order = ["L0_KERNEL", "L1_GATEWAY", "L2_TOOLS", "L3_PHYSICAL"]
        if source_layer and target_layer:
            source_idx = layer_order.index(source_layer) if source_layer in layer_order else -1
            target_idx = layer_order.index(target_layer) if target_layer in layer_order else -1
            
            if abs(source_idx - target_idx) == 1:
                # Adjacent layers can communicate
                self._log_event(source_node, target_node, action, True, "Adjacent layer default")
                return AccessCheckResponse(
                    allowed=True,
                    reason="Adjacent layer communication allowed",
                    rule_matched="ADJACENT_LAYER"
                )
        
        # Default deny for unmatched cases
        self._log_event(source_node, target_node, action, False, "Default deny")
        return AccessCheckResponse(
            allowed=False,
            reason="Access denied by default security policy",
            rule_matched="DEFAULT_DENY"
        )
    
    def _rule_matches(
        self, 
        rule: Dict, 
        source_node: str, 
        target_node: str, 
        action: str,
        source_layer: str,
        target_layer: str
    ) -> bool:
        """Check if a rule matches the request."""
        rule_source = rule.get("source", "*")
        rule_target = rule.get("target", "*")
        rule_action = rule.get("action", "*")
        
        # Check source
        source_match = (
            rule_source == "*" or 
            rule_source == source_node or 
            rule_source == source_layer
        )
        
        # Check target
        target_match = (
            rule_target == "*" or 
            rule_target == target_node or 
            rule_target == target_layer
        )
        
        # Check action
        action_match = rule_action == "*" or rule_action == action
        
        return source_match and target_match and action_match
    
    def _log_event(
        self, 
        source_node: str, 
        target_node: str, 
        action: str, 
        allowed: bool, 
        reason: str
    ):
        """Log a security event."""
        event = SecurityEvent(
            timestamp=datetime.now().isoformat(),
            event_type="access_check",
            source_node=source_node,
            target_node=target_node,
            action=action,
            allowed=allowed,
            reason=reason
        )
        
        self.security_events.append(event)
        
        # Trim old events
        if len(self.security_events) > self.max_events:
            self.security_events = self.security_events[-self.max_events:]
        
        log_level = logging.INFO if allowed else logging.WARNING
        logger.log(log_level, f"Access {'ALLOWED' if allowed else 'DENIED'}: {source_node} -> {target_node} ({action}): {reason}")
    
    def get_recent_events(self, limit: int = 100) -> List[SecurityEvent]:
        """Get recent security events."""
        return self.security_events[-limit:]

# =============================================================================
# FastAPI Application
# =============================================================================

security_enforcer: Optional[SecurityEnforcer] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global security_enforcer
    
    logger.info(f"Starting Node {NODE_ID}: {NODE_NAME}")
    
    security_enforcer = SecurityEnforcer(WHITELIST_PATH)
    
    # Register with state machine
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{STATE_MACHINE_URL}/node/register",
                json={
                    "node_id": NODE_ID,
                    "node_name": NODE_NAME,
                    "layer": "L0_KERNEL",
                    "ip_address": "10.88.0.68",
                    "capabilities": ["access_control", "security_audit"]
                },
                timeout=5.0
            )
            logger.info("Registered with state machine")
    except Exception as e:
        logger.warning(f"Failed to register with state machine: {e}")
    
    logger.info(f"Node {NODE_ID} ({NODE_NAME}) is ready")
    
    yield
    
    logger.info(f"Shutting down Node {NODE_ID}")

app = FastAPI(
    title=f"UFO Galaxy Node {NODE_ID}: {NODE_NAME}",
    description="Security Enforcer - Access Control for UFO Galaxy",
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
        "events_logged": len(security_enforcer.security_events) if security_enforcer else 0
    }

@app.post("/check", response_model=AccessCheckResponse)
async def check_access(request: AccessCheckRequest):
    """Check if access is allowed between two nodes."""
    return security_enforcer.check_access(
        source_node=request.source_node,
        target_node=request.target_node,
        action=request.action
    )

@app.get("/events")
async def get_events(limit: int = 100):
    """Get recent security events."""
    events = security_enforcer.get_recent_events(limit)
    return {
        "events": [e.dict() for e in events],
        "count": len(events)
    }

@app.get("/rules")
async def get_rules():
    """Get current security rules."""
    return {
        "layers": security_enforcer.LAYERS,
        "hardware_nodes": security_enforcer.HARDWARE_NODES,
        "whitelist": security_enforcer.whitelist
    }

@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "node_id": NODE_ID,
        "node_name": NODE_NAME,
        "layer": "L0_KERNEL",
        "status": "running",
        "security_rules": [
            "Layer 3 nodes CANNOT talk to each other",
            "Layer 3 nodes CANNOT talk to the Internet",
            "ALL Hardware requests MUST pass through Node 50",
            "ALL Global State MUST sync via Node 00"
        ]
    }

# =============================================================================
# Main Entry Point
# =============================================================================

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8068,
        reload=False,
        log_level=LOG_LEVEL.lower()
    )
