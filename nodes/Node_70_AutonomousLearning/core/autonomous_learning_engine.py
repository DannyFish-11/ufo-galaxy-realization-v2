"""
Node 70: Autonomous Learning Engine (ALE) - Enhanced with Real ML Algorithms
功能:
1. 观察：接收 Node 15/113 (VLM) 的结构化 UI 数据。
2. 分析：使用 Qwen-Think-Max 分析 UI 变化和任务执行结果。
3. 实验：生成新的操作序列，通过 Node 33 (ADB) 执行。
4. 知识图谱：更新系统知识图谱 (Node 53) 以实现长期记忆。
5. 机器学习：经验聚类、模式发现、技能泛化、经验回放
"""
import os
import json
import asyncio
import hashlib
import numpy as np
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
from collections import defaultdict
import logging

# ML imports
try:
    from sklearn.cluster import KMeans, DBSCAN, AgglomerativeClustering
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics.pairwise import cosine_similarity
    from sklearn.decomposition import PCA
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    logging.warning("sklearn not available, using fallback implementations")

logger = logging.getLogger("Node70_ALE")


class Experience:
    """经验数据模型"""
    def __init__(self, 
                 experience_id: str,
                 device_id: str,
                 ui_tree: Dict[str, Any],
                 task_context: Dict[str, Any],
                 action: str,
                 outcome: Dict[str, Any],
                 timestamp: Optional[datetime] = None,
                 skill_type: str = "general"):
        self.experience_id = experience_id or self._generate_id()
        self.device_id = device_id
        self.ui_tree = ui_tree
        self.task_context = task_context
        self.action = action
        self.outcome = outcome
        self.timestamp = timestamp or datetime.now()
        self.skill_type = skill_type
        self.reward = outcome.get("reward", 0.0)
        self.success = outcome.get("success", False)
        self.feature_vector = None
        
    def _generate_id(self) -> str:
        return hashlib.md5(f"{datetime.now().isoformat()}".encode()).hexdigest()[:16]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "experience_id": self.experience_id,
            "device_id": self.device_id,
            "ui_tree": self.ui_tree,
            "task_context": self.task_context,
            "action": self.action,
            "outcome": self.outcome,
            "timestamp": self.timestamp.isoformat(),
            "skill_type": self.skill_type,
            "reward": self.reward,
            "success": self.success
        }


class SkillPattern:
    """技能模式模型"""
    def __init__(self, 
                 pattern_id: str,
                 skill_type: str,
                 experiences: List[str],
                 confidence: float = 0.0,
                 avg_reward: float = 0.0):
        self.pattern_id = pattern_id
        self.skill_type = skill_type
        self.experiences = experiences
        self.confidence = confidence
        self.avg_reward = avg_reward
        self.created_at = datetime.now()
        self.usage_count = 0
        self.generalized_action = None
        
    def to_dict(self) -> Dict[str, Any]:
        return {
            "pattern_id": self.pattern_id,
            "skill_type": self.skill_type,
            "experiences": self.experiences,
            "confidence": self.confidence,
            "avg_reward": self.avg_reward,
            "created_at": self.created_at.isoformat(),
            "usage_count": self.usage_count,
            "generalized_action": self.generalized_action
        }


class AutonomousLearningEngine:
    def __init__(self, knowledge_graph_url: str, qwen_think_url: str):
        self.knowledge_graph_url = knowledge_graph_url
        self.qwen_think_url = qwen_think_url
        
        # 经验存储
        self.experiences: Dict[str, Experience] = {}
        self.experience_buffer: List[Experience] = []
        self.buffer_size = 1000
        
        # 技能模式存储
        self.patterns: Dict[str, SkillPattern] = {}
        self.skill_library: Dict[str, List[str]] = defaultdict(list)
        
        # 聚类模型
        self.kmeans_model = None
        self.dbscan_model = None
        self.scaler = StandardScaler() if SKLEARN_AVAILABLE else None
        
        # 特征维度
        self.feature_dim = 20
        
        logger.info("ALE Initialized with Qwen-Think, KG, and ML capabilities.")

    # ==================== 核心ML方法 ====================
    
    def _extract_features(self, experience: Experience) -> np.ndarray:
        """从经验中提取特征向量
        
        特征包括:
        - UI结构特征 (元素数量、层级深度等)
        - 任务上下文特征 (任务类型、复杂度等)
        - 动作特征 (动作类型、坐标等)
        - 结果特征 (奖励、成功率等)
        """
        features = []
        
        # 1. UI结构特征 (5维)
        ui_tree = experience.ui_tree
        features.append(len(ui_tree.get("elements", [])))  # 元素数量
        features.append(self._calculate_tree_depth(ui_tree))  # 树深度
        features.append(len(ui_tree.get("clickable", [])))  # 可点击元素
        features.append(len(ui_tree.get("text_inputs", [])))  # 文本输入
        features.append(self._hash_skill_type(experience.skill_type) % 100)  # 技能类型哈希
        
        # 2. 任务上下文特征 (5维)
        task = experience.task_context
        features.append(len(task.get("steps", [])))  # 任务步骤数
        features.append(task.get("difficulty", 5))  # 难度
        features.append(self._hash_string(task.get("app_name", "")) % 100)  # 应用名哈希
        features.append(task.get("retry_count", 0))  # 重试次数
        features.append(len(task.get("constraints", [])))  # 约束数量
        
        # 3. 动作特征 (5维)
        action = experience.action
        features.append(self._hash_action_type(action))  # 动作类型编码
        features.extend(self._extract_action_coords(action))  # 动作坐标
        features.append(len(action))  # 动作长度
        
        # 4. 结果特征 (5维)
        features.append(experience.reward)  # 奖励值
        features.append(1.0 if experience.success else 0.0)  # 成功标志
        features.append((datetime.now() - experience.timestamp).total_seconds() / 3600)  # 时间衰减
        features.append(self._calculate_outcome_quality(experience.outcome))  # 结果质量
        features.append(experience.outcome.get("execution_time", 0))  # 执行时间
        
        # 确保特征维度一致
        feature_vector = np.array(features, dtype=np.float32)
        if len(feature_vector) < self.feature_dim:
            feature_vector = np.pad(feature_vector, (0, self.feature_dim - len(feature_vector)))
        else:
            feature_vector = feature_vector[:self.feature_dim]
            
        experience.feature_vector = feature_vector
        return feature_vector
    
    def _calculate_tree_depth(self, ui_tree: Dict) -> int:
        """计算UI树的深度"""
        elements = ui_tree.get("elements", [])
        if not elements:
            return 0
        max_depth = 0
        for elem in elements:
            depth = elem.get("depth", 0)
            max_depth = max(max_depth, depth)
        return max_depth
    
    def _hash_skill_type(self, skill_type: str) -> int:
        """将技能类型哈希为数值"""
        return int(hashlib.md5(skill_type.encode()).hexdigest(), 16)
    
    def _hash_string(self, s: str) -> int:
        """字符串哈希"""
        return int(hashlib.md5(s.encode()).hexdigest(), 16) if s else 0
    
    def _hash_action_type(self, action: str) -> float:
        """提取动作类型并编码"""
        action_types = {
            "click": 1.0, "swipe": 2.0, "input": 3.0,
            "long_press": 4.0, "back": 5.0, "home": 6.0
        }
        for act_type, code in action_types.items():
            if act_type in action.lower():
                return code
        return 0.0
    
    def _extract_action_coords(self, action: str) -> List[float]:
        """从动作字符串提取坐标"""
        import re
        coords = re.findall(r'\d+', action)
        if len(coords) >= 2:
            return [float(coords[0]) / 1000, float(coords[1]) / 1000]
        return [0.0, 0.0]
    
    def _calculate_outcome_quality(self, outcome: Dict) -> float:
        """计算结果质量分数"""
        quality = 0.0
        if outcome.get("success"):
            quality += 0.5
        quality += min(outcome.get("reward", 0) / 10, 0.5)
        return quality
    
    def cluster_experiences(self, n_clusters: int = 5) -> Dict[str, Any]:
        """使用 KMeans 对经验进行聚类
        
        Args:
            n_clusters: 聚类数量
            
        Returns:
            聚类结果，包含每个聚类的中心点和成员
        """
        if not self.experiences:
            logger.warning("No experiences to cluster")
            return {"status": "no_data", "clusters": []}
        
        if not SKLEARN_AVAILABLE:
            logger.warning("sklearn not available, using simple grouping")
            return self._fallback_clustering(n_clusters)
        
        # 提取所有特征
        exp_list = list(self.experiences.values())
        feature_matrix = np.array([self._extract_features(exp) for exp in exp_list])
        
        # 标准化
        scaled_features = self.scaler.fit_transform(feature_matrix)
        
        # KMeans聚类
        n_clusters = min(n_clusters, len(exp_list))
        self.kmeans_model = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
        labels = self.kmeans_model.fit_predict(scaled_features)
        
        # 组织聚类结果
        clusters = []
        for i in range(n_clusters):
            cluster_exps = [exp_list[j].experience_id for j, label in enumerate(labels) if label == i]
            cluster_skill_types = [exp_list[j].skill_type for j, label in enumerate(labels) if label == i]
            
            # 计算聚类统计
            avg_reward = np.mean([exp_list[j].reward for j, label in enumerate(labels) if label == i])
            success_rate = np.mean([1.0 if exp_list[j].success else 0.0 for j, label in enumerate(labels) if label == i])
            
            clusters.append({
                "cluster_id": i,
                "center": self.kmeans_model.cluster_centers_[i].tolist(),
                "experience_ids": cluster_exps,
                "dominant_skill": max(set(cluster_skill_types), key=cluster_skill_types.count) if cluster_skill_types else "unknown",
                "avg_reward": float(avg_reward),
                "success_rate": float(success_rate),
                "size": len(cluster_exps)
            })
        
        logger.info(f"Clustered {len(exp_list)} experiences into {n_clusters} clusters")
        return {
            "status": "success",
            "n_clusters": n_clusters,
            "clusters": clusters,
            "inertia": float(self.kmeans_model.inertia_)
        }
    
    def _fallback_clustering(self, n_clusters: int) -> Dict[str, Any]:
        """当sklearn不可用时使用的简单分组"""
        groups = defaultdict(list)
        for exp in self.experiences.values():
            groups[exp.skill_type].append(exp.experience_id)
        
        clusters = []
        for i, (skill_type, exp_ids) in enumerate(groups.items()):
            exps = [self.experiences[eid] for eid in exp_ids]
            avg_reward = np.mean([e.reward for e in exps])
            success_rate = np.mean([1.0 if e.success else 0.0 for e in exps])
            
            clusters.append({
                "cluster_id": i,
                "center": [0.0] * self.feature_dim,
                "experience_ids": exp_ids,
                "dominant_skill": skill_type,
                "avg_reward": float(avg_reward),
                "success_rate": float(success_rate),
                "size": len(exp_ids)
            })
        
        return {"status": "fallback", "n_clusters": len(clusters), "clusters": clusters}
    
    def discover_patterns(self, min_samples: int = 3, eps: float = 0.5) -> List[Dict[str, Any]]:
        """使用 DBSCAN 发现经验模式
        
        Args:
            min_samples: 形成核心点所需的最小样本数
            eps: 邻域半径
            
        Returns:
            发现的模式列表
        """
        if len(self.experiences) < min_samples:
            logger.warning("Not enough experiences for pattern discovery")
            return []
        
        if not SKLEARN_AVAILABLE:
            return self._fallback_pattern_discovery(min_samples)
        
        # 提取特征
        exp_list = list(self.experiences.values())
        feature_matrix = np.array([self._extract_features(exp) for exp in exp_list])
        scaled_features = self.scaler.fit_transform(feature_matrix)
        
        # DBSCAN聚类
        self.dbscan_model = DBSCAN(eps=eps, min_samples=min_samples)
        labels = self.dbscan_model.fit_predict(scaled_features)
        
        # 提取模式
        patterns = []
        unique_labels = set(labels)
        
        for label in unique_labels:
            if label == -1:  # 噪声点
                continue
                
            cluster_indices = [i for i, l in enumerate(labels) if l == label]
            cluster_exps = [exp_list[i] for i in cluster_indices]
            
            # 创建模式
            pattern_id = f"pattern_{label}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
            exp_ids = [exp.experience_id for exp in cluster_exps]
            
            # 计算模式统计
            avg_reward = np.mean([exp.reward for exp in cluster_exps])
            success_rate = np.mean([1.0 if exp.success else 0.0 for exp in cluster_exps])
            confidence = success_rate * (1 - 1 / (len(cluster_exps) + 1))
            
            # 确定主导技能类型
            skill_types = [exp.skill_type for exp in cluster_exps]
            dominant_skill = max(set(skill_types), key=skill_types.count)
            
            pattern = SkillPattern(
                pattern_id=pattern_id,
                skill_type=dominant_skill,
                experiences=exp_ids,
                confidence=confidence,
                avg_reward=avg_reward
            )
            
            self.patterns[pattern_id] = pattern
            self.skill_library[dominant_skill].append(pattern_id)
            
            patterns.append({
                "pattern_id": pattern_id,
                "skill_type": dominant_skill,
                "experience_count": len(cluster_exps),
                "confidence": confidence,
                "avg_reward": avg_reward,
                "success_rate": success_rate,
                "sample_actions": [exp.action for exp in cluster_exps[:3]]
            })
        
        logger.info(f"Discovered {len(patterns)} patterns from {len(self.experiences)} experiences")
        return patterns
    
    def _fallback_pattern_discovery(self, min_samples: int) -> List[Dict[str, Any]]:
        """当sklearn不可用时使用的简单模式发现"""
        patterns = []
        for skill_type, pattern_ids in self.skill_library.items():
            if len(pattern_ids) >= min_samples:
                exps = [self.experiences[pid] for pid in pattern_ids if pid in self.experiences]
                if len(exps) >= min_samples:
                    avg_reward = np.mean([e.reward for e in exps])
                    success_rate = np.mean([1.0 if e.success else 0.0 for e in exps])
                    patterns.append({
                        "pattern_id": f"pattern_{skill_type}",
                        "skill_type": skill_type,
                        "experience_count": len(exps),
                        "confidence": success_rate,
                        "avg_reward": avg_reward,
                        "success_rate": success_rate,
                        "sample_actions": [e.action for e in exps[:3]]
                    })
        return patterns
    
    def generalize_skill(self, pattern_id: str) -> Dict[str, Any]:
        """从模式中泛化技能
        
        Args:
            pattern_id: 模式ID
            
        Returns:
            泛化后的技能
        """
        if pattern_id not in self.patterns:
            return {"status": "error", "message": "Pattern not found"}
        
        pattern = self.patterns[pattern_id]
        
        # 获取相关经验
        experiences = [self.experiences[eid] for eid in pattern.experiences if eid in self.experiences]
        
        if not experiences:
            return {"status": "error", "message": "No experiences found for pattern"}
        
        # 分析动作模式
        actions = [exp.action for exp in experiences]
        action_patterns = self._analyze_action_patterns(actions)
        
        # 生成泛化动作模板
        generalized_action = self._generate_generalized_action(action_patterns, experiences)
        pattern.generalized_action = generalized_action
        
        # 计算泛化置信度
        consistency_score = self._calculate_action_consistency(actions)
        pattern.confidence = pattern.confidence * consistency_score
        
        result = {
            "status": "success",
            "pattern_id": pattern_id,
            "skill_type": pattern.skill_type,
            "generalized_action": generalized_action,
            "confidence": pattern.confidence,
            "avg_reward": pattern.avg_reward,
            "action_patterns": action_patterns,
            "consistency_score": consistency_score,
            "based_on_experiences": len(experiences)
        }
        
        logger.info(f"Generalized skill for pattern {pattern_id}: {generalized_action}")
        return result
    
    def _analyze_action_patterns(self, actions: List[str]) -> Dict[str, Any]:
        """分析动作模式"""
        patterns = {
            "action_types": defaultdict(int),
            "common_coords": [],
            "common_texts": []
        }
        
        for action in actions:
            # 统计动作类型
            if "click" in action.lower():
                patterns["action_types"]["click"] += 1
            elif "swipe" in action.lower():
                patterns["action_types"]["swipe"] += 1
            elif "input" in action.lower():
                patterns["action_types"]["input"] += 1
            else:
                patterns["action_types"]["other"] += 1
        
        return patterns
    
    def _generate_generalized_action(self, patterns: Dict, experiences: List[Experience]) -> str:
        """生成泛化动作"""
        # 选择最常见的动作类型
        most_common = max(patterns["action_types"].items(), key=lambda x: x[1])
        action_type = most_common[0]
        
        # 基于经验生成泛化动作
        if action_type == "click":
            # 计算平均点击位置
            coords = []
            for exp in experiences:
                c = self._extract_action_coords(exp.action)
                if c != [0.0, 0.0]:
                    coords.append(c)
            if coords:
                avg_x = int(np.mean([c[0] for c in coords]) * 1000)
                avg_y = int(np.mean([c[1] for c in coords]) * 1000)
                return f"click({avg_x}, {avg_y})"
            return "click(x, y)"
        elif action_type == "swipe":
            return "swipe(start_x, start_y, end_x, end_y)"
        elif action_type == "input":
            return "input(text)"
        else:
            return "action()"
    
    def _calculate_action_consistency(self, actions: List[str]) -> float:
        """计算动作一致性分数"""
        if not actions:
            return 0.0
        
        # 基于动作类型的一致性
        action_types = []
        for action in actions:
            if "click" in action.lower():
                action_types.append("click")
            elif "swipe" in action.lower():
                action_types.append("swipe")
            elif "input" in action.lower():
                action_types.append("input")
            else:
                action_types.append("other")
        
        if not action_types:
            return 0.0
        
        most_common = max(set(action_types), key=action_types.count)
        consistency = action_types.count(most_common) / len(action_types)
        return consistency
    
    def replay_experiences(self, skill_type: str, limit: int = 10) -> List[Dict[str, Any]]:
        """回放相关经验用于强化学习
        
        Args:
            skill_type: 技能类型
            limit: 返回经验数量上限
            
        Returns:
            相关经验列表
        """
        # 1. 获取该技能类型的所有经验
        relevant_exps = [
            exp for exp in self.experiences.values()
            if exp.skill_type == skill_type
        ]
        
        if not relevant_exps:
            logger.warning(f"No experiences found for skill type: {skill_type}")
            return []
        
        # 2. 按优先级排序
        # 优先级 = 奖励 * 成功标志 * 时间衰减因子
        now = datetime.now()
        prioritized_exps = []
        
        for exp in relevant_exps:
            time_decay = np.exp(-(now - exp.timestamp).total_seconds() / 86400)  # 24小时衰减
            priority = exp.reward * (1.0 if exp.success else 0.5) * time_decay
            prioritized_exps.append((exp, priority))
        
        # 3. 按优先级排序
        prioritized_exps.sort(key=lambda x: x[1], reverse=True)
        
        # 4. 返回前N个
        selected_exps = prioritized_exps[:limit]
        
        # 5. 更新使用计数
        for exp, _ in selected_exps:
            if exp.experience_id in self.experiences:
                # 可以在这里添加经验使用统计
                pass
        
        result = [
            {
                "experience_id": exp.experience_id,
                "action": exp.action,
                "outcome": exp.outcome,
                "reward": exp.reward,
                "success": exp.success,
                "priority": priority,
                "timestamp": exp.timestamp.isoformat()
            }
            for exp, priority in selected_exps
        ]
        
        logger.info(f"Replayed {len(result)} experiences for skill type: {skill_type}")
        return result
    
    def find_similar_skills(self, query_exp_id: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """基于相似度查找相关技能
        
        Args:
            query_exp_id: 查询经验ID
            top_k: 返回最相似的K个
            
        Returns:
            相似技能列表
        """
        if query_exp_id not in self.experiences:
            return []
        
        if not SKLEARN_AVAILABLE:
            return self._fallback_similarity(query_exp_id, top_k)
        
        query_exp = self.experiences[query_exp_id]
        query_features = self._extract_features(query_exp).reshape(1, -1)
        
        # 计算与所有经验的相似度
        similarities = []
        for exp_id, exp in self.experiences.items():
            if exp_id != query_exp_id:
                exp_features = self._extract_features(exp).reshape(1, -1)
                sim = cosine_similarity(query_features, exp_features)[0][0]
                similarities.append((exp_id, sim, exp))
        
        # 排序并返回前K个
        similarities.sort(key=lambda x: x[1], reverse=True)
        top_similar = similarities[:top_k]
        
        return [
            {
                "experience_id": exp_id,
                "similarity": float(sim),
                "skill_type": exp.skill_type,
                "action": exp.action,
                "reward": exp.reward
            }
            for exp_id, sim, exp in top_similar
        ]
    
    def _fallback_similarity(self, query_exp_id: str, top_k: int) -> List[Dict[str, Any]]:
        """当sklearn不可用时使用的简单相似度"""
        query_exp = self.experiences[query_exp_id]
        
        similar = []
        for exp_id, exp in self.experiences.items():
            if exp_id != query_exp_id:
                # 简单匹配：相同技能类型得高分
                sim = 1.0 if exp.skill_type == query_exp.skill_type else 0.0
                similar.append((exp_id, sim, exp))
        
        similar.sort(key=lambda x: x[1], reverse=True)
        return [
            {
                "experience_id": exp_id,
                "similarity": float(sim),
                "skill_type": exp.skill_type,
                "action": exp.action,
                "reward": exp.reward
            }
            for exp_id, sim, exp in similar[:top_k]
        ]
    
    # ==================== 原有方法增强 ====================
    
    async def process_observation(self, device_id: str, ui_tree: Dict[str, Any], 
                                   task_context: Dict[str, Any]) -> Dict[str, Any]:
        """处理 VLM 观察结果，生成下一步行动计划（增强版）"""
        
        # 1. 检查是否有相似的历史经验
        similar_skills = []
        if self.experiences:
            # 创建临时经验用于查找相似
            temp_exp = Experience(
                experience_id="temp",
                device_id=device_id,
                ui_tree=ui_tree,
                task_context=task_context,
                action="",
                outcome={},
                skill_type=task_context.get("skill_type", "general")
            )
            temp_features = self._extract_features(temp_exp).reshape(1, -1)
            
            # 查找相似经验
            for exp_id, exp in list(self.experiences.items())[:50]:  # 限制搜索范围
                exp_features = self._extract_features(exp).reshape(1, -1)
                if SKLEARN_AVAILABLE:
                    sim = cosine_similarity(temp_features, exp_features)[0][0]
                else:
                    sim = 1.0 if exp.skill_type == temp_exp.skill_type else 0.0
                
                if sim > 0.7:  # 相似度阈值
                    similar_skills.append({
                        "experience_id": exp_id,
                        "similarity": float(sim),
                        "action": exp.action,
                        "success": exp.success
                    })
        
        # 2. 如果有高置信度的相似经验，优先使用
        if similar_skills:
            similar_skills.sort(key=lambda x: x["similarity"], reverse=True)
            best_match = similar_skills[0]
            if best_match["success"] and best_match["similarity"] > 0.8:
                logger.info(f"Using similar experience {best_match['experience_id']} with similarity {best_match['similarity']}")
                return {
                    "status": "plan_generated_from_memory",
                    "commands": [best_match["action"]],
                    "similarity": best_match["similarity"],
                    "source_experience": best_match["experience_id"]
                }
        
        # 3. 否则调用 Qwen-Think-Max 进行推理
        prompt = self._build_qwen_prompt(device_id, ui_tree, task_context)
        plan_response = await self._call_qwen_think(prompt)
        adb_commands = self._parse_plan_to_adb(plan_response)
        
        # 4. 存储新经验
        new_exp = Experience(
            experience_id=None,
            device_id=device_id,
            ui_tree=ui_tree,
            task_context=task_context,
            action=adb_commands[0] if adb_commands else "",
            outcome={"pending": True},
            skill_type=task_context.get("skill_type", "general")
        )
        self._store_experience(new_exp)
        
        return {
            "status": "plan_generated",
            "commands": adb_commands,
            "similar_experiences": similar_skills[:3]
        }
    
    def _store_experience(self, experience: Experience):
        """存储经验到缓冲区"""
        self.experiences[experience.experience_id] = experience
        self.experience_buffer.append(experience)
        
        # 限制缓冲区大小
        if len(self.experience_buffer) > self.buffer_size:
            removed = self.experience_buffer.pop(0)
            if removed.experience_id in self.experiences:
                del self.experiences[removed.experience_id]
        
        logger.debug(f"Stored experience {experience.experience_id}, buffer size: {len(self.experience_buffer)}")
    
    def update_experience_outcome(self, experience_id: str, outcome: Dict[str, Any]):
        """更新经验结果（用于强化学习反馈）"""
        if experience_id in self.experiences:
            exp = self.experiences[experience_id]
            exp.outcome = outcome
            exp.reward = outcome.get("reward", 0.0)
            exp.success = outcome.get("success", False)
            logger.info(f"Updated experience {experience_id} with outcome: success={exp.success}, reward={exp.reward}")
            return True
        return False
    
    def get_learning_stats(self) -> Dict[str, Any]:
        """获取学习统计信息"""
        if not self.experiences:
            return {"total_experiences": 0}
        
        total = len(self.experiences)
        successful = sum(1 for exp in self.experiences.values() if exp.success)
        avg_reward = np.mean([exp.reward for exp in self.experiences.values()])
        
        skill_distribution = defaultdict(int)
        for exp in self.experiences.values():
            skill_distribution[exp.skill_type] += 1
        
        return {
            "total_experiences": total,
            "successful_experiences": successful,
            "success_rate": successful / total if total > 0 else 0,
            "average_reward": float(avg_reward),
            "skill_distribution": dict(skill_distribution),
            "pattern_count": len(self.patterns),
            "buffer_size": len(self.experience_buffer)
        }
    
    # ==================== 内部方法 ====================
    
    async def _call_qwen_think(self, prompt: str) -> Dict:
        """调用 Qwen-Think-Max (Node 04) 进行推理"""
        # 实际应调用 Node 04 (Router)
        return {"plan": "click(100, 200)", "reason": "Identified 'Next' button."}
    
    def _build_qwen_prompt(self, device_id: str, ui_tree: Dict, context: Dict) -> str:
        """构建Qwen提示"""
        return f"Device: {device_id}. UI Tree: {json.dumps(ui_tree)}. Context: {json.dumps(context)}. Generate next action."
    
    def _parse_plan_to_adb(self, plan_response: Dict) -> List[str]:
        """解析计划为ADB命令"""
        return [plan_response.get("plan", "")]
    
    async def _update_knowledge_graph(self, device_id: str, context: Dict, commands: List[str]):
        """更新知识图谱"""
        logger.info(f"Updating KG for {device_id} with new knowledge.")


# ==================== 便捷函数 ====================

def create_learning_engine(kg_url: str = "", qwen_url: str = "") -> AutonomousLearningEngine:
    """创建学习引擎实例"""
    return AutonomousLearningEngine(kg_url, qwen_url)


# 示例用法
if __name__ == "__main__":
    # 创建引擎
    engine = create_learning_engine()
    
    # 添加一些示例经验
    for i in range(10):
        exp = Experience(
            experience_id=None,
            device_id="device_001",
            ui_tree={"elements": [{"id": i}], "clickable": [i % 3]},
            task_context={"skill_type": "navigation" if i < 5 else "input", "steps": [i]},
            action=f"click({100 + i * 10}, {200})" if i < 5 else f"input('text_{i}')",
            outcome={"reward": 0.5 + i * 0.05, "success": i % 3 != 0},
            skill_type="navigation" if i < 5 else "input"
        )
        engine._store_experience(exp)
    
    # 测试聚类
    print("=== Clustering Experiences ===")
    clusters = engine.cluster_experiences(n_clusters=3)
    print(json.dumps(clusters, indent=2, default=str))
    
    # 测试模式发现
    print("\n=== Discovering Patterns ===")
    patterns = engine.discover_patterns(min_samples=2)
    print(json.dumps(patterns, indent=2, default=str))
    
    # 测试经验回放
    print("\n=== Replaying Experiences ===")
    replay = engine.replay_experiences("navigation", limit=5)
    print(json.dumps(replay, indent=2, default=str))
    
    # 测试统计
    print("\n=== Learning Stats ===")
    stats = engine.get_learning_stats()
    print(json.dumps(stats, indent=2, default=str))
