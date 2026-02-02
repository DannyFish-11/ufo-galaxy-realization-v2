#!/usr/bin/env python3
"""
Knowledge Graph Module for UFO Galaxy v5.0

Implements a NetworkX-based knowledge graph with:
- 13 entity types
- 38 relationship types
- Graph visualization export
- Advanced graph queries

The knowledge graph serves as the central repository for all learned
knowledge, enabling complex reasoning and inference.

Author: UFO Galaxy Team
Version: 5.0.0
"""

import json
import logging
import hashlib
from datetime import datetime
from typing import Dict, List, Optional, Any, Set, Tuple, Union
from dataclasses import dataclass, field, asdict
from enum import Enum, auto
from collections import defaultdict
import asyncio

import networkx as nx
import numpy as np
from networkx.algorithms import community
from networkx.readwrite import json_graph

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class EntityType(Enum):
    """13 entity types for the knowledge graph."""
    CONCEPT = "concept"
    PERSON = "person"
    ORGANIZATION = "organization"
    TECHNOLOGY = "technology"
    EVENT = "event"
    LOCATION = "location"
    DOCUMENT = "document"
    PATTERN = "pattern"
    ALGORITHM = "algorithm"
    DATASET = "dataset"
    METRIC = "metric"
    HYPOTHESIS = "hypothesis"
    EXPERIMENT = "experiment"


class RelationshipType(Enum):
    """38 relationship types for connecting entities."""
    # Hierarchical relationships
    IS_A = "is_a"
    PART_OF = "part_of"
    HAS_PART = "has_part"
    INSTANCE_OF = "instance_of"
    
    # Causal relationships
    CAUSES = "causes"
    CAUSED_BY = "caused_by"
    ENABLES = "enables"
    PREVENTS = "prevents"
    
    # Temporal relationships
    PRECEDES = "precedes"
    FOLLOWS = "follows"
    CO_OCCURS_WITH = "co_occurs_with"
    
    # Semantic relationships
    RELATED_TO = "related_to"
    SIMILAR_TO = "similar_to"
    CONTRASTS_WITH = "contrasts_with"
    SYNONYM_OF = "synonym_of"
    ANTONYM_OF = "antonym_of"
    
    # Attribution relationships
    CREATED_BY = "created_by"
    USES = "uses"
    USED_BY = "used_by"
    IMPLEMENTS = "implements"
    IMPLEMENTED_BY = "implemented_by"
    
    # Domain-specific relationships
    EVALUATES = "evaluates"
    EVALUATED_BY = "evaluated_by"
    PRODUCES = "produces"
    PRODUCED_BY = "produced_by"
    APPLIES_TO = "applies_to"
    APPLIED_TO = "applied_to"
    
    # Learning-specific relationships
    VALIDATES = "validates"
    VALIDATED_BY = "validated_by"
    REFUTES = "refutes"
    REFUTED_BY = "refuted_by"
    SUPPORTS = "supports"
    SUPPORTED_BY = "supported_by"
    
    # Emergence relationships
    EMERGES_FROM = "emerges_from"
    GIVES_RISE_TO = "gives_rise_to"
    INTERACTS_WITH = "interacts_with"


@dataclass
class Entity:
    """Represents an entity in the knowledge graph."""
    id: str
    entity_type: EntityType
    name: str
    description: str = ""
    properties: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    source: str = "unknown"
    
    def __post_init__(self):
        if not self.id:
            self.id = self._generate_id()
    
    def _generate_id(self) -> str:
        """Generate unique entity ID."""
        content = f"{self.entity_type.value}:{self.name}"
        return hashlib.md5(content.encode()).hexdigest()[:16]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert entity to dictionary."""
        return {
            'id': self.id,
            'entity_type': self.entity_type.value,
            'name': self.name,
            'description': self.description,
            'properties': self.properties,
            'confidence': self.confidence,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'source': self.source
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Entity':
        """Create entity from dictionary."""
        return cls(
            id=data['id'],
            entity_type=EntityType(data['entity_type']),
            name=data['name'],
            description=data.get('description', ''),
            properties=data.get('properties', {}),
            confidence=data.get('confidence', 1.0),
            created_at=datetime.fromisoformat(data['created_at']),
            updated_at=datetime.fromisoformat(data['updated_at']),
            source=data.get('source', 'unknown')
        )


@dataclass
class Relationship:
    """Represents a relationship between entities."""
    id: str
    source_id: str
    target_id: str
    relationship_type: RelationshipType
    properties: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    created_at: datetime = field(default_factory=datetime.now)
    
    def __post_init__(self):
        if not self.id:
            self.id = self._generate_id()
    
    def _generate_id(self) -> str:
        """Generate unique relationship ID."""
        content = f"{self.source_id}:{self.relationship_type.value}:{self.target_id}"
        return hashlib.md5(content.encode()).hexdigest()[:16]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert relationship to dictionary."""
        return {
            'id': self.id,
            'source_id': self.source_id,
            'target_id': self.target_id,
            'relationship_type': self.relationship_type.value,
            'properties': self.properties,
            'confidence': self.confidence,
            'created_at': self.created_at.isoformat()
        }


class KnowledgeGraph:
    """
    NetworkX-based knowledge graph for UFO Galaxy.
    
    Features:
    - Multi-entity type support (13 types)
    - Rich relationship semantics (38 types)
    - Graph algorithms for inference
    - Visualization export
    - Async operations support
    """
    
    def __init__(self, name: str = "ufo_knowledge_graph"):
        self.name = name
        self._graph = nx.DiGraph()
        self._entity_index: Dict[str, Entity] = {}
        self._relationship_index: Dict[str, Relationship] = {}
        self._entity_type_index: Dict[EntityType, Set[str]] = defaultdict(set)
        self._relationship_type_index: Dict[RelationshipType, Set[str]] = defaultdict(set)
        
        # Statistics
        self._stats = {
            'entities_added': 0,
            'entities_removed': 0,
            'relationships_added': 0,
            'relationships_removed': 0,
            'last_updated': None
        }
        
        logger.info(f"KnowledgeGraph '{name}' initialized")
    
    # Entity Management
    
    def add_entity(self, entity: Entity) -> str:
        """
        Add an entity to the knowledge graph.
        
        Args:
            entity: Entity to add
            
        Returns:
            Entity ID
        """
        # Add to graph
        self._graph.add_node(
            entity.id,
            **entity.to_dict()
        )
        
        # Update indices
        self._entity_index[entity.id] = entity
        self._entity_type_index[entity.entity_type].add(entity.id)
        
        # Update stats
        self._stats['entities_added'] += 1
        self._stats['last_updated'] = datetime.now().isoformat()
        
        logger.debug(f"Added entity: {entity.name} ({entity.entity_type.value})")
        return entity.id
    
    def add_entities(self, entities: List[Entity]) -> List[str]:
        """Add multiple entities efficiently."""
        ids = []
        for entity in entities:
            ids.append(self.add_entity(entity))
        return ids
    
    def get_entity(self, entity_id: str) -> Optional[Entity]:
        """Get entity by ID."""
        return self._entity_index.get(entity_id)
    
    def get_entities_by_type(
        self,
        entity_type: EntityType,
        limit: Optional[int] = None
    ) -> List[Entity]:
        """Get all entities of a specific type."""
        entity_ids = list(self._entity_type_index[entity_type])
        entities = [self._entity_index[eid] for eid in entity_ids if eid in self._entity_index]
        
        if limit:
            entities = entities[:limit]
        
        return entities
    
    def update_entity(
        self,
        entity_id: str,
        updates: Dict[str, Any]
    ) -> Optional[Entity]:
        """Update entity properties."""
        entity = self._entity_index.get(entity_id)
        if not entity:
            return None
        
        # Update fields
        for key, value in updates.items():
            if hasattr(entity, key):
                setattr(entity, key, value)
        
        entity.updated_at = datetime.now()
        
        # Update graph node
        self._graph.nodes[entity_id].update(entity.to_dict())
        
        return entity
    
    def remove_entity(self, entity_id: str) -> bool:
        """Remove an entity and its relationships."""
        if entity_id not in self._entity_index:
            return False
        
        entity = self._entity_index[entity_id]
        
        # Remove from graph
        self._graph.remove_node(entity_id)
        
        # Update indices
        del self._entity_index[entity_id]
        self._entity_type_index[entity.entity_type].discard(entity_id)
        
        # Remove related relationships
        rels_to_remove = [
            rid for rid, rel in self._relationship_index.items()
            if rel.source_id == entity_id or rel.target_id == entity_id
        ]
        for rid in rels_to_remove:
            self.remove_relationship(rid)
        
        # Update stats
        self._stats['entities_removed'] += 1
        
        logger.debug(f"Removed entity: {entity_id}")
        return True
    
    # Relationship Management
    
    def add_relationship(self, relationship: Relationship) -> str:
        """
        Add a relationship between entities.
        
        Args:
            relationship: Relationship to add
            
        Returns:
            Relationship ID
        """
        # Validate entities exist
        if relationship.source_id not in self._entity_index:
            raise ValueError(f"Source entity not found: {relationship.source_id}")
        if relationship.target_id not in self._entity_index:
            raise ValueError(f"Target entity not found: {relationship.target_id}")
        
        # Add edge to graph
        self._graph.add_edge(
            relationship.source_id,
            relationship.target_id,
            **relationship.to_dict()
        )
        
        # Update indices
        self._relationship_index[relationship.id] = relationship
        self._relationship_type_index[relationship.relationship_type].add(relationship.id)
        
        # Update stats
        self._stats['relationships_added'] += 1
        
        logger.debug(
            f"Added relationship: {relationship.relationship_type.value} "
            f"({relationship.source_id} -> {relationship.target_id})"
        )
        return relationship.id
    
    def add_relationships(self, relationships: List[Relationship]) -> List[str]:
        """Add multiple relationships efficiently."""
        ids = []
        for rel in relationships:
            try:
                ids.append(self.add_relationship(rel))
            except ValueError as e:
                logger.warning(f"Skipping invalid relationship: {e}")
        return ids
    
    def get_relationship(self, relationship_id: str) -> Optional[Relationship]:
        """Get relationship by ID."""
        return self._relationship_index.get(relationship_id)
    
    def get_relationships_by_type(
        self,
        relationship_type: RelationshipType,
        limit: Optional[int] = None
    ) -> List[Relationship]:
        """Get all relationships of a specific type."""
        rel_ids = list(self._relationship_type_index[relationship_type])
        relationships = [self._relationship_index[rid] for rid in rel_ids if rid in self._relationship_index]
        
        if limit:
            relationships = relationships[:limit]
        
        return relationships
    
    def get_entity_relationships(
        self,
        entity_id: str,
        direction: str = "both"  # "out", "in", "both"
    ) -> List[Relationship]:
        """Get all relationships for an entity."""
        relationships = []
        
        if direction in ("out", "both"):
            for _, target, data in self._graph.out_edges(entity_id, data=True):
                if 'id' in data:
                    rel = self._relationship_index.get(data['id'])
                    if rel:
                        relationships.append(rel)
        
        if direction in ("in", "both"):
            for source, _, data in self._graph.in_edges(entity_id, data=True):
                if 'id' in data:
                    rel = self._relationship_index.get(data['id'])
                    if rel:
                        relationships.append(rel)
        
        return relationships
    
    def remove_relationship(self, relationship_id: str) -> bool:
        """Remove a relationship."""
        if relationship_id not in self._relationship_index:
            return False
        
        relationship = self._relationship_index[relationship_id]
        
        # Remove from graph
        self._graph.remove_edge(
            relationship.source_id,
            relationship.target_id
        )
        
        # Update indices
        del self._relationship_index[relationship_id]
        self._relationship_type_index[relationship.relationship_type].discard(relationship_id)
        
        # Update stats
        self._stats['relationships_removed'] += 1
        
        return True
    
    # Graph Queries
    
    def find_path(
        self,
        source_id: str,
        target_id: str,
        max_length: int = 5
    ) -> Optional[List[str]]:
        """Find shortest path between two entities."""
        try:
            path = nx.shortest_path(
                self._graph,
                source_id,
                target_id
            )
            if len(path) <= max_length + 1:
                return path
            return None
        except nx.NetworkXNoPath:
            return None
    
    def find_connected_entities(
        self,
        entity_id: str,
        max_depth: int = 2
    ) -> Dict[str, List[str]]:
        """Find entities connected within a certain depth."""
        connected = defaultdict(list)
        
        for depth in range(1, max_depth + 1):
            nodes = set()
            self._bfs_collect(entity_id, depth, nodes)
            connected[f"depth_{depth}"] = list(nodes - {entity_id})
        
        return dict(connected)
    
    def _bfs_collect(
        self,
        start: str,
        max_depth: int,
        collected: Set[str]
    ):
        """BFS to collect connected nodes."""
        visited = {start}
        queue = [(start, 0)]
        
        while queue:
            node, depth = queue.pop(0)
            
            if depth >= max_depth:
                continue
            
            for neighbor in self._graph.neighbors(node):
                if neighbor not in visited:
                    visited.add(neighbor)
                    collected.add(neighbor)
                    queue.append((neighbor, depth + 1))
    
    def find_similar_entities(
        self,
        entity_id: str,
        min_common_neighbors: int = 2
    ) -> List[Tuple[str, int]]:
        """Find entities with similar connection patterns."""
        if entity_id not in self._graph:
            return []
        
        entity_neighbors = set(self._graph.neighbors(entity_id))
        similarities = []
        
        for other_id in self._graph.nodes():
            if other_id == entity_id:
                continue
            
            other_neighbors = set(self._graph.neighbors(other_id))
            common = entity_neighbors & other_neighbors
            
            if len(common) >= min_common_neighbors:
                similarities.append((other_id, len(common)))
        
        return sorted(similarities, key=lambda x: x[1], reverse=True)
    
    def detect_communities(self) -> List[List[str]]:
        """Detect communities in the knowledge graph."""
        try:
            # Convert to undirected for community detection
            undirected = self._graph.to_undirected()
            communities_list = community.greedy_modularity_communities(undirected)
            return [list(c) for c in communities_list]
        except Exception as e:
            logger.error(f"Community detection failed: {e}")
            return []
    
    def calculate_centrality(self, top_n: int = 10) -> Dict[str, float]:
        """Calculate centrality scores for entities."""
        try:
            centrality = nx.degree_centrality(self._graph)
            sorted_centrality = sorted(
                centrality.items(),
                key=lambda x: x[1],
                reverse=True
            )
            return dict(sorted_centrality[:top_n])
        except Exception as e:
            logger.error(f"Centrality calculation failed: {e}")
            return {}
    
    def infer_relationship(
        self,
        entity_id1: str,
        entity_id2: str
    ) -> Optional[RelationshipType]:
        """Infer potential relationship between entities."""
        # Check if direct relationship exists
        if self._graph.has_edge(entity_id1, entity_id2):
            edge_data = self._graph.get_edge_data(entity_id1, entity_id2)
            if edge_data and 'relationship_type' in edge_data:
                return RelationshipType(edge_data['relationship_type'])
        
        # Try to infer from common neighbors
        neighbors1 = set(self._graph.neighbors(entity_id1))
        neighbors2 = set(self._graph.neighbors(entity_id2))
        common = neighbors1 & neighbors2
        
        if len(common) >= 3:
            return RelationshipType.RELATED_TO
        
        return None
    
    # Search and Query
    
    def search(
        self,
        query: str,
        entity_types: Optional[List[EntityType]] = None,
        limit: int = 10
    ) -> List[Entity]:
        """Search entities by name or description."""
        query_lower = query.lower()
        results = []
        
        for entity in self._entity_index.values():
            # Filter by type if specified
            if entity_types and entity.entity_type not in entity_types:
                continue
            
            # Search in name and description
            score = 0
            if query_lower in entity.name.lower():
                score += 2
            if query_lower in entity.description.lower():
                score += 1
            
            if score > 0:
                results.append((entity, score))
        
        # Sort by score
        results.sort(key=lambda x: x[1], reverse=True)
        
        return [entity for entity, _ in results[:limit]]
    
    def query_by_properties(
        self,
        property_filters: Dict[str, Any],
        entity_type: Optional[EntityType] = None
    ) -> List[Entity]:
        """Query entities by property values."""
        results = []
        
        entities = self._entity_index.values()
        if entity_type:
            entity_ids = self._entity_type_index[entity_type]
            entities = [self._entity_index[eid] for eid in entity_ids]
        
        for entity in entities:
            match = True
            for key, value in property_filters.items():
                if key not in entity.properties or entity.properties[key] != value:
                    match = False
                    break
            
            if match:
                results.append(entity)
        
        return results
    
    # Visualization Export
    
    def export_to_json(self, filepath: str):
        """Export graph to JSON format."""
        data = {
            'name': self.name,
            'entities': [e.to_dict() for e in self._entity_index.values()],
            'relationships': [r.to_dict() for r in self._relationship_index.values()],
            'stats': self._stats,
            'export_time': datetime.now().isoformat()
        }
        
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2, default=str)
        
        logger.info(f"Exported knowledge graph to {filepath}")
    
    def export_to_graphml(self, filepath: str):
        """Export graph to GraphML format for visualization."""
        nx.write_graphml(self._graph, filepath)
        logger.info(f"Exported graph to GraphML: {filepath}")
    
    def export_to_gexf(self, filepath: str):
        """Export graph to GEXF format for Gephi."""
        nx.write_gexf(self._graph, filepath)
        logger.info(f"Exported graph to GEXF: {filepath}")
    
    def export_to_cytoscape(self) -> Dict[str, Any]:
        """Export graph to Cytoscape.js format."""
        cyto_data = json_graph.cytoscape_data(self._graph)
        return cyto_data
    
    def export_to_d3(self) -> Dict[str, Any]:
        """Export graph to D3.js format."""
        nodes = []
        links = []
        
        for entity_id, entity in self._entity_index.items():
            nodes.append({
                'id': entity_id,
                'name': entity.name,
                'type': entity.entity_type.value,
                'group': list(self._entity_type_index.keys()).index(entity.entity_type)
            })
        
        for rel in self._relationship_index.values():
            links.append({
                'source': rel.source_id,
                'target': rel.target_id,
                'type': rel.relationship_type.value
            })
        
        return {'nodes': nodes, 'links': links}
    
    # Statistics and Analysis
    
    def get_stats(self) -> Dict[str, Any]:
        """Get comprehensive graph statistics."""
        return {
            'name': self.name,
            'entity_count': len(self._entity_index),
            'relationship_count': len(self._relationship_index),
            'entity_types': {
                et.value: len(eids)
                for et, eids in self._entity_type_index.items()
            },
            'relationship_types': {
                rt.value: len(rids)
                for rt, rids in self._relationship_type_index.items()
            },
            'density': nx.density(self._graph),
            'is_connected': nx.is_weakly_connected(self._graph),
            'connected_components': nx.number_weakly_connected_components(self._graph),
            'operation_stats': self._stats
        }
    
    def get_entity_distribution(self) -> Dict[str, int]:
        """Get distribution of entity types."""
        return {
            et.value: len(eids)
            for et, eids in self._entity_type_index.items()
        }
    
    def get_relationship_distribution(self) -> Dict[str, int]:
        """Get distribution of relationship types."""
        return {
            rt.value: len(rids)
            for rt, rids in self._relationship_type_index.items()
        }
    
    # Persistence
    
    def save(self, filepath: str):
        """Save knowledge graph to file."""
        data = {
            'name': self.name,
            'entities': [e.to_dict() for e in self._entity_index.values()],
            'relationships': [r.to_dict() for r in self._relationship_index.values()],
            'stats': self._stats
        }
        
        with open(filepath, 'w') as f:
            json.dump(data, f, default=str)
        
        logger.info(f"Saved knowledge graph to {filepath}")
    
    @classmethod
    def load(cls, filepath: str) -> 'KnowledgeGraph':
        """Load knowledge graph from file."""
        with open(filepath, 'r') as f:
            data = json.load(f)
        
        kg = cls(name=data.get('name', 'loaded_graph'))
        
        # Load entities
        for entity_data in data.get('entities', []):
            entity = Entity.from_dict(entity_data)
            kg.add_entity(entity)
        
        # Load relationships
        for rel_data in data.get('relationships', []):
            relationship = Relationship(
                id=rel_data['id'],
                source_id=rel_data['source_id'],
                target_id=rel_data['target_id'],
                relationship_type=RelationshipType(rel_data['relationship_type']),
                properties=rel_data.get('properties', {}),
                confidence=rel_data.get('confidence', 1.0),
                created_at=datetime.fromisoformat(rel_data['created_at'])
            )
            try:
                kg.add_relationship(relationship)
            except ValueError:
                logger.warning(f"Skipping invalid relationship: {relationship.id}")
        
        kg._stats = data.get('stats', kg._stats)
        
        logger.info(f"Loaded knowledge graph from {filepath}")
        return kg


# Example usage
def demo():
    """Demonstrate knowledge graph functionality."""
    kg = KnowledgeGraph("demo_graph")
    
    # Create entities
    entities = [
        Entity(id="", entity_type=EntityType.CONCEPT, name="Machine Learning",
               description="Field of AI focused on learning from data"),
        Entity(id="", entity_type=EntityType.CONCEPT, name="Deep Learning",
               description="Subset of ML using neural networks"),
        Entity(id="", entity_type=EntityType.TECHNOLOGY, name="TensorFlow",
               description="Open-source ML framework"),
        Entity(id="", entity_type=EntityType.PERSON, name="Geoffrey Hinton",
               description="Pioneer in deep learning"),
        Entity(id="", entity_type=EntityType.ALGORITHM, name="Backpropagation",
               description="Algorithm for training neural networks"),
    ]
    
    entity_ids = kg.add_entities(entities)
    print(f"Added {len(entity_ids)} entities")
    
    # Create relationships
    relationships = [
        Relationship(id="", source_id=entity_ids[1], target_id=entity_ids[0],
                    relationship_type=RelationshipType.IS_A),
        Relationship(id="", source_id=entity_ids[2], target_id=entity_ids[1],
                    relationship_type=RelationshipType.IMPLEMENTS),
        Relationship(id="", source_id=entity_ids[3], target_id=entity_ids[4],
                    relationship_type=RelationshipType.CREATED_BY),
        Relationship(id="", source_id=entity_ids[4], target_id=entity_ids[1],
                    relationship_type=RelationshipType.ENABLES),
    ]
    
    rel_ids = kg.add_relationships(relationships)
    print(f"Added {len(rel_ids)} relationships")
    
    # Query
    print("\n=== Graph Statistics ===")
    print(json.dumps(kg.get_stats(), indent=2, default=str))
    
    # Search
    print("\n=== Search Results for 'learning' ===")
    results = kg.search("learning")
    for entity in results:
        print(f"  - {entity.name} ({entity.entity_type.value})")
    
    # Find path
    print("\n=== Path from TensorFlow to ML ===")
    path = kg.find_path(entity_ids[2], entity_ids[0])
    if path:
        path_names = [kg.get_entity(eid).name for eid in path]
        print(f"  {' -> '.join(path_names)}")
    
    # Communities
    print("\n=== Communities ===")
    communities = kg.detect_communities()
    for i, comm in enumerate(communities):
        comm_names = [kg.get_entity(eid).name for eid in comm]
        print(f"  Community {i+1}: {', '.join(comm_names)}")
    
    # Export
    kg.export_to_json("/mnt/okcomputer/output/ufo-galaxy-v5/enhancements/learning/demo_graph.json")
    print("\nExported to demo_graph.json")


if __name__ == "__main__":
    demo()
