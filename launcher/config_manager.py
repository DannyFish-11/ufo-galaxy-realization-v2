"""
Configuration Manager for UFO Galaxy Launcher

Manages unified configuration from multiple sources:
- node_dependencies.json
- NODE_CONFIG in galaxy_launcher.py
- Environment variables
- User overrides
"""

import os
import json
import logging
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field, asdict
from pathlib import Path
from enum import Enum

logger = logging.getLogger(__name__)


class NodeGroup(str, Enum):
    """Node classification groups"""
    CORE = "core"           # Essential nodes (must start)
    EXTENDED = "extended"   # Extended features
    OPTIONAL = "optional"   # Optional features
    HARDWARE = "hardware"   # Hardware control nodes
    AI = "ai"               # AI/ML nodes
    CLOUD = "cloud"         # Cloud service nodes


@dataclass
class NodeConfig:
    """Complete node configuration"""
    id: str
    name: str
    group: NodeGroup
    port: int
    description: str = ""
    dependencies: List[str] = field(default_factory=list)
    priority: int = 50  # Lower = higher priority
    auto_start: bool = True
    restart_policy: str = "always"  # always, on-failure, never
    max_restarts: int = 3
    health_check_url: str = ""
    health_check_interval: int = 30
    startup_timeout: int = 30
    env_vars: Dict[str, str] = field(default_factory=dict)
    resource_limits: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        if not self.health_check_url:
            self.health_check_url = f"http://localhost:{self.port}/health"


class ConfigManager:
    """
    Unified Configuration Manager
    
    Merges configuration from multiple sources:
    1. Default configuration
    2. node_dependencies.json
    3. Environment variables
    4. User configuration files
    
    Example:
        >>> config = ConfigManager()
        >>> config.load_all()
        >>> core_nodes = config.get_nodes_by_group(NodeGroup.CORE)
    """
    
    def __init__(self, base_path: Optional[Path] = None):
        """
        Initialize configuration manager
        
        Args:
            base_path: Base path for configuration files
        """
        self.base_path = base_path or Path(__file__).parent.parent
        self.nodes: Dict[str, NodeConfig] = {}
        self.groups: Dict[str, Dict[str, Any]] = {}
        self.global_config: Dict[str, Any] = {}
        
        # Initialize with defaults
        self._init_defaults()
    
    def _init_defaults(self):
        """Initialize default configuration"""
        # Core system nodes (must start)
        core_nodes = {
            "00": NodeConfig("00", "StateMachine", NodeGroup.CORE, 8000,
                           "Core state management", [], 10),
            "01": NodeConfig("01", "OneAPI", NodeGroup.CORE, 8001,
                           "Unified API gateway", [], 10),
            "02": NodeConfig("02", "Tasker", NodeGroup.CORE, 8002,
                           "Task scheduling", ["00"], 20),
            "03": NodeConfig("03", "Router", NodeGroup.CORE, 8003,
                           "Message routing", ["00"], 20),
            "05": NodeConfig("05", "Auth", NodeGroup.CORE, 8005,
                           "Authentication & authorization", [], 10),
            "06": NodeConfig("06", "Filesystem", NodeGroup.CORE, 8006,
                           "File system operations", [], 15),
            "65": NodeConfig("65", "LoggerCentral", NodeGroup.CORE, 8065,
                           "Central logging", [], 5),
            "67": NodeConfig("67", "HealthMonitor", NodeGroup.CORE, 8067,
                           "Health monitoring", ["65"], 10),
            "79": NodeConfig("79", "LocalLLM", NodeGroup.CORE, 8079,
                           "Local LLM inference", [], 15),
            "80": NodeConfig("80", "MemorySystem", NodeGroup.CORE, 8080,
                           "Memory management", [], 15),
        }
        
        # Extended nodes
        extended_nodes = {
            "04": NodeConfig("04", "Email", NodeGroup.EXTENDED, 8004,
                           "Email operations", [], 50),
            "07": NodeConfig("07", "Git", NodeGroup.EXTENDED, 8007,
                           "Git operations", [], 50),
            "08": NodeConfig("08", "Calendar", NodeGroup.EXTENDED, 8008,
                           "Calendar management", [], 50),
            "11": NodeConfig("11", "GitHub", NodeGroup.EXTENDED, 8011,
                           "GitHub integration", [], 50),
            "12": NodeConfig("12", "Postgres", NodeGroup.EXTENDED, 8012,
                           "PostgreSQL operations", [], 50),
            "13": NodeConfig("13", "SQLite", NodeGroup.EXTENDED, 8013,
                           "SQLite operations", [], 50),
            "15": NodeConfig("15", "OCR", NodeGroup.EXTENDED, 8015,
                           "OCR processing", [], 50),
            "17": NodeConfig("17", "Crypto", NodeGroup.EXTENDED, 8017,
                           "Cryptographic operations", [], 50),
            "19": NodeConfig("19", "EdgeTTS", NodeGroup.EXTENDED, 8019,
                           "Text-to-speech", [], 50),
            "22": NodeConfig("22", "BraveSearch", NodeGroup.EXTENDED, 8022,
                           "Brave search", [], 50),
            "23": NodeConfig("23", "Time", NodeGroup.EXTENDED, 8123,
                           "Time operations", [], 50),
            "24": NodeConfig("24", "Weather", NodeGroup.EXTENDED, 8024,
                           "Weather data", [], 50),
            "29": NodeConfig("29", "SSH", NodeGroup.EXTENDED, 8029,
                           "SSH operations", [], 50),
            "30": NodeConfig("30", "SFTP", NodeGroup.EXTENDED, 8030,
                           "SFTP operations", [], 50),
            "33": NodeConfig("33", "ADB", NodeGroup.EXTENDED, 8033,
                           "Android ADB", [], 50),
            "64": NodeConfig("64", "Telemetry", NodeGroup.EXTENDED, 8064,
                           "Telemetry collection", [], 50),
            "66": NodeConfig("66", "AuditLog", NodeGroup.EXTENDED, 8066,
                           "Audit logging", ["65"], 55),
            "68": NodeConfig("68", "Security", NodeGroup.EXTENDED, 8068,
                           "Security monitoring", ["65"], 55),
            "69": NodeConfig("69", "BackupRestore", NodeGroup.EXTENDED, 8069,
                           "Backup & restore", [], 50),
            "72": NodeConfig("72", "KnowledgeBase", NodeGroup.EXTENDED, 8072,
                           "Knowledge base", [], 50),
            "73": NodeConfig("73", "Learning", NodeGroup.EXTENDED, 8073,
                           "Learning system", [], 50),
        }
        
        # Hardware control nodes
        hardware_nodes = {
            "28": NodeConfig("28", "LinuxDBus", NodeGroup.HARDWARE, 8028,
                           "Linux D-Bus", [], 60),
            "31": NodeConfig("31", "MQTT", NodeGroup.HARDWARE, 8031,
                           "MQTT broker", [], 60),
            "32": NodeConfig("32", "CANbus", NodeGroup.HARDWARE, 8032,
                           "CAN bus control", [], 60),
            "34": NodeConfig("34", "BLE", NodeGroup.HARDWARE, 8034,
                           "Bluetooth LE", [], 60),
            "35": NodeConfig("35", "NFC", NodeGroup.HARDWARE, 8035,
                           "NFC operations", [], 60),
            "36": NodeConfig("36", "Camera", NodeGroup.HARDWARE, 8036,
                           "Camera control", [], 60),
            "37": NodeConfig("37", "Audio", NodeGroup.HARDWARE, 8037,
                           "Audio operations", [], 60),
            "38": NodeConfig("38", "Serial", NodeGroup.HARDWARE, 8038,
                           "Serial port", [], 60),
        }
        
        # AI/ML nodes
        ai_nodes = {
            "50": NodeConfig("50", "Transformer", NodeGroup.AI, 8050,
                           "Transformer models", ["01"], 40),
            "51": NodeConfig("51", "NLU", NodeGroup.AI, 8051,
                           "Natural language understanding", ["01"], 40),
            "52": NodeConfig("52", "Qiskit", NodeGroup.AI, 8052,
                           "Quantum computing", [], 60),
            "53": NodeConfig("53", "GraphLogic", NodeGroup.AI, 8053,
                           "Graph logic", [], 60),
            "54": NodeConfig("54", "SymbolicMath", NodeGroup.AI, 8054,
                           "Symbolic math", [], 60),
            "56": NodeConfig("56", "MultiAgent", NodeGroup.AI, 8056,
                           "Multi-agent system", ["01"], 45),
            "57": NodeConfig("57", "ReinforcementLearning", NodeGroup.AI, 8057,
                           "Reinforcement learning", [], 60),
            "58": NodeConfig("58", "NeuralArchSearch", NodeGroup.AI, 8058,
                           "Neural architecture search", [], 60),
            "59": NodeConfig("59", "FederatedLearning", NodeGroup.AI, 8059,
                           "Federated learning", [], 60),
            "62": NodeConfig("62", "ProbabilisticProgramming", NodeGroup.AI, 8062,
                           "Probabilistic programming", [], 60),
        }
        
        # Optional/Cloud nodes
        optional_nodes = {
            "09": NodeConfig("09", "Sandbox", NodeGroup.OPTIONAL, 8009,
                           "Sandbox environment", [], 70),
            "10": NodeConfig("10", "Slack", NodeGroup.OPTIONAL, 8010,
                           "Slack integration", [], 70),
            "14": NodeConfig("14", "Elasticsearch", NodeGroup.OPTIONAL, 8014,
                           "Elasticsearch", [], 70),
            "18": NodeConfig("18", "DeepL", NodeGroup.OPTIONAL, 8018,
                           "DeepL translation", [], 70),
            "20": NodeConfig("20", "S3", NodeGroup.OPTIONAL, 8020,
                           "S3 storage", [], 70),
            "21": NodeConfig("21", "Notion", NodeGroup.OPTIONAL, 8021,
                           "Notion integration", [], 70),
            "25": NodeConfig("25", "GoogleSearch", NodeGroup.OPTIONAL, 8025,
                           "Google search", [], 70),
            "70": NodeConfig("70", "BambuLab", NodeGroup.OPTIONAL, 8070,
                           "BambuLab 3D printer", [], 70),
            "71": NodeConfig("71", "MediaGen", NodeGroup.OPTIONAL, 8071,
                           "Media generation", [], 70),
            "74": NodeConfig("74", "DigitalTwin", NodeGroup.OPTIONAL, 8074,
                           "Digital twin", [], 70),
        }
        
        # Merge all nodes
        all_nodes = {}
        all_nodes.update(core_nodes)
        all_nodes.update(extended_nodes)
        all_nodes.update(hardware_nodes)
        all_nodes.update(ai_nodes)
        all_nodes.update(optional_nodes)
        
        self.nodes = all_nodes
        
        # Initialize groups
        self.groups = {
            "core": {
                "name": "Core System",
                "description": "Essential nodes for basic operation",
                "startup_delay": 1.0,
                "auto_start": True
            },
            "extended": {
                "name": "Extended Features",
                "description": "Additional functionality",
                "startup_delay": 0.5,
                "auto_start": False
            },
            "hardware": {
                "name": "Hardware Control",
                "description": "Hardware interface nodes",
                "startup_delay": 0.5,
                "auto_start": False
            },
            "ai": {
                "name": "AI/ML",
                "description": "Artificial intelligence nodes",
                "startup_delay": 1.0,
                "auto_start": False
            },
            "optional": {
                "name": "Optional Services",
                "description": "Third-party integrations",
                "startup_delay": 0.5,
                "auto_start": False
            }
        }
        
        # Global configuration
        self.global_config = {
            "log_dir": str(self.base_path / "logs"),
            "nodes_dir": str(self.base_path / "nodes"),
            "health_check_interval": 30,
            "startup_timeout": 30,
            "max_parallel_starts": 5,
            "restart_on_failure": True,
            "graceful_shutdown_timeout": 30
        }
    
    def load_from_json(self, filepath: Path) -> bool:
        """
        Load configuration from JSON file
        
        Args:
            filepath: Path to JSON configuration file
            
        Returns:
            True if loaded successfully
        """
        try:
            if not filepath.exists():
                logger.warning(f"Config file not found: {filepath}")
                return False
            
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Load nodes
            if "nodes" in data:
                for node_id, node_data in data["nodes"].items():
                    if node_id in self.nodes:
                        # Update existing
                        existing = self.nodes[node_id]
                        for key, value in node_data.items():
                            if hasattr(existing, key):
                                setattr(existing, key, value)
                    else:
                        # Create new
                        group = NodeGroup(node_data.get("group", "optional"))
                        self.nodes[node_id] = NodeConfig(
                            id=node_id,
                            name=node_data.get("name", f"Node_{node_id}"),
                            group=group,
                            port=node_data.get("port", 8000 + int(node_id)),
                            description=node_data.get("description", ""),
                            dependencies=node_data.get("dependencies", []),
                            priority=node_data.get("priority", 50),
                            auto_start=node_data.get("auto_start", True),
                            restart_policy=node_data.get("restart_policy", "always"),
                            max_restarts=node_data.get("max_restarts", 3)
                        )
            
            # Load groups
            if "groups" in data:
                self.groups.update(data["groups"])
            
            # Load global config
            if "global" in data:
                self.global_config.update(data["global"])
            
            logger.info(f"Loaded configuration from {filepath}")
            return True
            
        except Exception as e:
            logger.error(f"Error loading config from {filepath}: {e}")
            return False
    
    def load_from_env(self):
        """Load configuration from environment variables"""
        env_mappings = {
            "UFO_GALAXY_LOG_DIR": "log_dir",
            "UFO_GALAXY_NODES_DIR": "nodes_dir",
            "UFO_GALAXY_HEALTH_INTERVAL": ("health_check_interval", int),
            "UFO_GALAXY_STARTUP_TIMEOUT": ("startup_timeout", int),
            "UFO_GALAXY_MAX_PARALLEL": ("max_parallel_starts", int),
            "UFO_GALAXY_AUTO_RESTART": ("restart_on_failure", lambda x: x.lower() == "true")
        }
        
        for env_var, config_key in env_mappings.items():
            value = os.environ.get(env_var)
            if value:
                if isinstance(config_key, tuple):
                    key, converter = config_key
                    try:
                        self.global_config[key] = converter(value)
                    except Exception as e:
                        logger.warning(f"Error converting {env_var}: {e}")
                else:
                    self.global_config[config_key] = value
    
    def load_all(self):
        """Load configuration from all sources"""
        # Load from node_dependencies.json if exists
        deps_file = self.base_path / "node_dependencies.json"
        if deps_file.exists():
            self.load_from_json(deps_file)
        
        # Load from environment
        self.load_from_env()
        
        # Load from user config if exists
        user_config = self.base_path / "config" / "launcher.json"
        if user_config.exists():
            self.load_from_json(user_config)
    
    def get_node(self, node_id: str) -> Optional[NodeConfig]:
        """Get node configuration by ID"""
        return self.nodes.get(node_id)
    
    def get_nodes_by_group(self, group: NodeGroup) -> List[NodeConfig]:
        """Get all nodes in a group"""
        return [n for n in self.nodes.values() if n.group == group]
    
    def get_nodes_by_groups(self, groups: List[NodeGroup]) -> List[NodeConfig]:
        """Get all nodes in multiple groups"""
        return [n for n in self.nodes.values() if n.group in groups]
    
    def get_startup_order(self, node_ids: Optional[List[str]] = None) -> List[str]:
        """
        Get nodes in startup order (respecting dependencies)
        
        Args:
            node_ids: Specific nodes to order (None = all)
            
        Returns:
            List of node IDs in startup order
        """
        from .dependency_resolver import DependencyResolver
        
        resolver = DependencyResolver(self.nodes)
        if node_ids:
            return resolver.resolve_startup_order(node_ids)
        else:
            return resolver.resolve_all_startup_order()
    
    def save_to_file(self, filepath: Path):
        """Save current configuration to file"""
        data = {
            "nodes": {
                node_id: asdict(config)
                for node_id, config in self.nodes.items()
            },
            "groups": self.groups,
            "global": self.global_config
        }
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, default=str)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get configuration statistics"""
        return {
            "total_nodes": len(self.nodes),
            "by_group": {
                group.value: len(self.get_nodes_by_group(group))
                for group in NodeGroup
            },
            "core_nodes": len(self.get_nodes_by_group(NodeGroup.CORE)),
            "auto_start_nodes": len([n for n in self.nodes.values() if n.auto_start]),
            "total_dependencies": sum(
                len(n.dependencies) for n in self.nodes.values()
            )
        }
