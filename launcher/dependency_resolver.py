"""
Dependency Resolver for UFO Galaxy Launcher

Resolves node dependencies and calculates optimal startup order.
Uses topological sorting with priority consideration.
"""

import logging
from typing import Dict, List, Set, Optional
from collections import defaultdict, deque
from dataclasses import dataclass

from .config_manager import NodeConfig

logger = logging.getLogger(__name__)


class CircularDependencyError(Exception):
    """Raised when circular dependency is detected"""
    pass


class DependencyResolver:
    """
    Dependency resolver using topological sort
    
    Features:
    - Detects circular dependencies
    - Respects priority ordering
    - Supports parallel startup groups
    - Calculates dependency depth
    
    Example:
        >>> resolver = DependencyResolver(nodes)
        >>> order = resolver.resolve_startup_order(["50", "51"])
        >>> print(order)  # Dependencies first
    """
    
    def __init__(self, nodes: Dict[str, NodeConfig]):
        """
        Initialize resolver
        
        Args:
            nodes: Dictionary of node configurations
        """
        self.nodes = nodes
        self._dependency_graph: Optional[Dict[str, Set[str]]] = None
        self._reverse_graph: Optional[Dict[str, Set[str]]] = None
        self._build_graphs()
    
    def _build_graphs(self):
        """Build dependency and reverse dependency graphs"""
        self._dependency_graph = defaultdict(set)
        self._reverse_graph = defaultdict(set)
        
        for node_id, config in self.nodes.items():
            for dep_id in config.dependencies:
                if dep_id in self.nodes:
                    self._dependency_graph[node_id].add(dep_id)
                    self._reverse_graph[dep_id].add(node_id)
    
    def resolve_startup_order(
        self,
        target_nodes: List[str],
        include_dependencies: bool = True
    ) -> List[str]:
        """
        Resolve startup order for target nodes
        
        Args:
            target_nodes: Node IDs to start
            include_dependencies: Whether to include dependency nodes
            
        Returns:
            Ordered list of node IDs
            
        Raises:
            CircularDependencyError: If circular dependency detected
        """
        # Collect all nodes (including dependencies)
        all_nodes = set(target_nodes)
        
        if include_dependencies:
            for node_id in target_nodes:
                all_nodes.update(self._get_all_dependencies(node_id))
        
        # Filter to existing nodes
        all_nodes = {n for n in all_nodes if n in self.nodes}
        
        # Calculate in-degrees
        in_degree = {node_id: 0 for node_id in all_nodes}
        for node_id in all_nodes:
            for dep_id in self._dependency_graph[node_id]:
                if dep_id in all_nodes:
                    in_degree[node_id] += 1
        
        # Topological sort with priority
        result = []
        queue = deque()
        
        # Start with nodes that have no dependencies
        for node_id in all_nodes:
            if in_degree[node_id] == 0:
                queue.append(node_id)
        
        # Sort queue by priority
        queue = deque(sorted(queue, key=lambda x: self.nodes[x].priority))
        
        while queue:
            # Get highest priority node
            current = queue.popleft()
            result.append(current)
            
            # Update in-degrees of dependent nodes
            for dependent in self._reverse_graph[current]:
                if dependent in all_nodes:
                    in_degree[dependent] -= 1
                    if in_degree[dependent] == 0:
                        # Insert in priority order
                        self._insert_by_priority(queue, dependent)
        
        # Check for circular dependencies
        if len(result) != len(all_nodes):
            unresolved = all_nodes - set(result)
            raise CircularDependencyError(
                f"Circular dependency detected among: {unresolved}"
            )
        
        return result
    
    def resolve_all_startup_order(self) -> List[str]:
        """Resolve startup order for all nodes"""
        return self.resolve_startup_order(list(self.nodes.keys()))
    
    def get_parallel_groups(self, node_ids: List[str]) -> List[List[str]]:
        """
        Group nodes that can be started in parallel
        
        Args:
            node_ids: Node IDs to group
            
        Returns:
            List of groups, where each group can be started in parallel
        """
        order = self.resolve_startup_order(node_ids)
        groups = []
        current_group = []
        current_depth = 0
        
        for node_id in order:
            depth = self._get_dependency_depth(node_id)
            
            if depth > current_depth:
                if current_group:
                    groups.append(current_group)
                current_group = [node_id]
                current_depth = depth
            else:
                current_group.append(node_id)
        
        if current_group:
            groups.append(current_group)
        
        return groups
    
    def _get_all_dependencies(self, node_id: str, visited: Optional[Set[str]] = None) -> Set[str]:
        """Get all transitive dependencies of a node"""
        if visited is None:
            visited = set()
        
        if node_id in visited:
            return set()
        
        visited.add(node_id)
        deps = set(self._dependency_graph.get(node_id, set()))
        
        for dep_id in list(deps):
            deps.update(self._get_all_dependencies(dep_id, visited))
        
        return deps
    
    def _get_dependency_depth(self, node_id: str, cache: Optional[Dict[str, int]] = None) -> int:
        """Calculate dependency depth (longest path to a root node)"""
        if cache is None:
            cache = {}
        
        if node_id in cache:
            return cache[node_id]
        
        deps = self._dependency_graph.get(node_id, set())
        if not deps:
            cache[node_id] = 0
            return 0
        
        max_depth = max(
            self._get_dependency_depth(dep_id, cache)
            for dep_id in deps if dep_id in self.nodes
        )
        
        cache[node_id] = max_depth + 1
        return cache[node_id]
    
    def _insert_by_priority(self, queue: deque, node_id: str):
        """Insert node into queue maintaining priority order"""
        priority = self.nodes[node_id].priority
        
        # Convert to list for insertion
        items = list(queue)
        
        # Find insertion point
        insert_idx = len(items)
        for i, item in enumerate(items):
            if self.nodes[item].priority > priority:
                insert_idx = i
                break
        
        # Insert and rebuild queue
        items.insert(insert_idx, node_id)
        queue.clear()
        queue.extend(items)
    
    def detect_circular_dependencies(self) -> List[List[str]]:
        """
        Detect all circular dependencies in the graph
        
        Returns:
            List of circular dependency cycles
        """
        cycles = []
        visited = set()
        rec_stack = set()
        
        def dfs(node_id: str, path: List[str]):
            visited.add(node_id)
            rec_stack.add(node_id)
            path.append(node_id)
            
            for dep_id in self._dependency_graph.get(node_id, set()):
                if dep_id not in visited:
                    dfs(dep_id, path)
                elif dep_id in rec_stack:
                    # Found cycle
                    cycle_start = path.index(dep_id)
                    cycle = path[cycle_start:] + [dep_id]
                    cycles.append(cycle)
            
            path.pop()
            rec_stack.remove(node_id)
        
        for node_id in self.nodes:
            if node_id not in visited:
                dfs(node_id, [])
        
        return cycles
    
    def get_dependency_tree(self, node_id: str, depth: int = 0) -> str:
        """Get visual representation of dependency tree"""
        lines = []
        indent = "  " * depth
        node = self.nodes.get(node_id)
        
        if node:
            lines.append(f"{indent}{node_id}: {node.name}")
            
            for dep_id in node.dependencies:
                if dep_id in self.nodes:
                    lines.append(self.get_dependency_tree(dep_id, depth + 1))
        
        return "\n".join(lines)
    
    def validate(self) -> Dict[str, any]:
        """Validate dependency graph"""
        result = {
            "valid": True,
            "errors": [],
            "warnings": [],
            "stats": {
                "total_nodes": len(self.nodes),
                "total_dependencies": sum(
                    len(deps) for deps in self._dependency_graph.values()
                ),
                "root_nodes": len([
                    n for n in self.nodes
                    if not self._dependency_graph.get(n.id, set())
                ]),
                "max_depth": max(
                    (self._get_dependency_depth(n.id) for n in self.nodes.values()),
                    default=0
                )
            }
        }
        
        # Check for missing dependencies
        for node_id, config in self.nodes.items():
            for dep_id in config.dependencies:
                if dep_id not in self.nodes:
                    result["warnings"].append(
                        f"Node {node_id} depends on non-existent node {dep_id}"
                    )
        
        # Check for circular dependencies
        cycles = self.detect_circular_dependencies()
        if cycles:
            result["valid"] = False
            for cycle in cycles:
                result["errors"].append(
                    f"Circular dependency: {' -> '.join(cycle)}"
                )
        
        return result
