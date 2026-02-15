# -*- coding: utf-8 -*-

"""
Node_73_Learning: 机器学习服务节点

本节点提供一个完整的机器学习服务，支持模型的训练和推理。
它包含配置加载、服务初始化、核心业务逻辑、健康检查和状态查询等功能。
"""

import asyncio
import logging
import os
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional, Type

# --- 日志配置 ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("node_73_learning.log")
    ]
)

logger = logging.getLogger(__name__)

# --- 枚举定义 ---

class ServiceStatus(Enum):
    """服务状态枚举"""
    UNINITIALIZED = "未初始化"
    INITIALIZING = "初始化中"
    RUNNING = "运行中"
    STOPPED = "已停止"
    ERROR = "错误"

class ModelType(Enum):
    """支持的模型类型"""
    CLASSIFICATION = "分类"
    REGRESSION = "回归"
    CLUSTERING = "聚类"

class TaskStatus(Enum):
    """任务状态枚举"""
    PENDING = "待处理"
    TRAINING = "训练中"
    INFERENCING = "推理中"
    COMPLETED = "已完成"
    FAILED = "失败"

# --- 配置类定义 ---

@dataclass
class ModelConfig:
    """模型配置"""
    name: str
    path: str
    model_type: ModelType
    version: str = "1.0.0"

@dataclass
class NodeConfig:
    """节点主配置类"""
    node_name: str = "Node_73_Learning"
    log_level: str = "INFO"
    api_port: int = 8073
    max_concurrent_tasks: int = 10
    models: Dict[str, ModelConfig] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NodeConfig":
        """从字典加载配置"""
        models_data = data.get("models", {})
        models = {
            name: ModelConfig(
                name=model_data["name"],
                path=model_data["path"],
                model_type=ModelType[model_data["model_type"].upper()],
                version=model_data.get("version", "1.0.0")
            ) for name, model_data in models_data.items()
        }
        return cls(
            node_name=data.get("node_name", "Node_73_Learning"),
            log_level=data.get("log_level", "INFO"),
            api_port=data.get("api_port", 8073),
            max_concurrent_tasks=data.get("max_concurrent_tasks", 10),
            models=models
        )

# --- 主服务类 ---

class LearningService:
    """机器学习主服务类"""

    def __init__(self, config: NodeConfig):
        """
        初始化服务。

        :param config: 节点配置实例
        """
        self.config = config
        self.status = ServiceStatus.UNINITIALIZED
        self.models: Dict[str, Any] = {}
        self.task_queue = asyncio.Queue()
        self.active_tasks = 0

        self._update_logger_level()
        logger.info(f"节点 {self.config.node_name} 正在初始化...")

    def _update_logger_level(self):
        """根据配置更新日志级别"""
        level = getattr(logging, self.config.log_level.upper(), logging.INFO)
        logger.setLevel(level)

    async def initialize(self):
        """
        异步初始化服务，加载所有配置的模型。
        """
        self.status = ServiceStatus.INITIALIZING
        logger.info("开始加载机器学习模型...")
        try:
            for model_name, model_config in self.config.models.items():
                await self._load_model(model_name, model_config)
            self.status = ServiceStatus.RUNNING
            logger.info(f"服务初始化完成，当前状态: {self.status.value}")
        except Exception as e:
            self.status = ServiceStatus.ERROR
            logger.error(f"服务初始化失败: {e}", exc_info=True)
            raise

    async def _load_model(self, model_name: str, model_config: ModelConfig):
        """
        模拟加载单个模型。
        在实际应用中，这里会是加载序列化模型文件（如 pickle, onnx）的逻辑。

        :param model_name: 模型名称
        :param model_config: 模型配置
        """
        logger.info(f"正在加载模型 '{model_name}' (类型: {model_config.model_type.value}) 从路径: {model_config.path}")
        # 模拟耗时操作
        await asyncio.sleep(1)
        if not os.path.exists(model_config.path):
            logger.warning(f"模型文件 {model_config.path} 不存在。将使用模拟模型。")
            # 创建一个模拟模型对象
            self.models[model_name] = f"Simulated_{model_config.model_type.name}_Model"
        else:
            # 在实际场景中，这里会用类似 joblib.load() 的方法
            # with open(model_config.path, 'rb') as f:
            #     self.models[model_name] = pickle.load(f)
            self.models[model_name] = f"Loaded_{model_config.model_type.name}_Model_From_{model_config.path}"
        
        logger.info(f"模型 '{model_name}' 加载成功。")

    async def schedule_task(self, task_type: str, model_name: str, data: Any) -> Dict[str, Any]:
        """
        将任务加入队列，等待执行。

        :param task_type: 任务类型 ('train' 或 'inference')
        :param model_name: 使用的模型名称
        :param data: 任务数据
        :return: 任务状态信息
        """
        if self.status != ServiceStatus.RUNNING:
            raise Exception("服务未运行，无法接受新任务。")
        
        if self.active_tasks >= self.config.max_concurrent_tasks:
            logger.warning("任务队列已满，请稍后重试。")
            return {"status": TaskStatus.FAILED.value, "message": "任务队列已满"}

        task_id = f"task_{int(asyncio.get_running_loop().time())}"
        task = {"id": task_id, "type": task_type, "model": model_name, "data": data, "status": TaskStatus.PENDING}
        await self.task_queue.put(task)
        self.active_tasks += 1
        logger.info(f"任务 {task_id} 已加入队列。")
        return {"task_id": task_id, "status": TaskStatus.PENDING.value}

    async def _process_tasks(self):
        """
        循环处理任务队列中的任务。
        """
        while self.status == ServiceStatus.RUNNING:
            try:
                task = await self.task_queue.get()
                logger.info(f"开始处理任务 {task['id']}...")
                if task['type'] == 'train':
                    result = await self._train(task['model'], task['data'])
                elif task['type'] == 'inference':
                    result = await self._inference(task['model'], task['data'])
                else:
                    result = {"status": TaskStatus.FAILED.value, "error": "未知的任务类型"}
                
                logger.info(f"任务 {task['id']} 处理完成，结果: {result['status']}. ")
                # 实际应用中可能会将结果存入数据库或通知其他服务

            except Exception as e:
                logger.error(f"处理任务时发生错误: {e}", exc_info=True)
            finally:
                self.active_tasks -= 1
                self.task_queue.task_done()

    async def _train(self, model_name: str, data: Any) -> Dict[str, Any]:
        """
        模拟模型训练过程。

        :param model_name: 模型名称
        :param data: 训练数据
        :return: 训练结果
        """
        logger.info(f"开始使用模型 '{model_name}' 进行训练...")
        # 模拟耗时的训练过程
        await asyncio.sleep(10)
        logger.info(f"模型 '{model_name}' 训练完成。")
        return {"status": TaskStatus.COMPLETED.value, "message": "模型训练成功"}

    async def _inference(self, model_name: str, data: Any) -> Dict[str, Any]:
        """
        模拟模型推理过程。

        :param model_name: 模型名称
        :param data: 推理数据
        :return: 推理结果
        """
        logger.info(f"开始使用模型 '{model_name}' 进行推理...")
        if model_name not in self.models:
            return {"status": TaskStatus.FAILED.value, "error": f"模型 {model_name} 未找到"}
        
        # 模拟耗时的推理过程
        await asyncio.sleep(2)
        # 模拟推理结果
        prediction = {"label": "positive", "confidence": 0.95}
        logger.info(f"模型 '{model_name}' 推理完成。")
        return {"status": TaskStatus.COMPLETED.value, "prediction": prediction}

    def get_status(self) -> Dict[str, Any]:
        """
        获取服务的当前状态。

        :return: 包含服务状态、模型和任务信息的字典
        """
        return {
            "service_status": self.status.value,
            "node_name": self.config.node_name,
            "loaded_models": list(self.models.keys()),
            "active_tasks": self.active_tasks,
            "queued_tasks": self.task_queue.qsize(),
            "max_concurrent_tasks": self.config.max_concurrent_tasks
        }

    def get_health(self) -> Dict[str, Any]:
        """
        健康检查接口。

        :return: 健康状态字典
        """
        is_healthy = self.status == ServiceStatus.RUNNING
        return {
            "status": "healthy" if is_healthy else "unhealthy",
            "details": self.get_status()
        }

    async def shutdown(self):
        """
        优雅地关闭服务。
        """
        logger.info("开始关闭服务...")
        self.status = ServiceStatus.STOPPED
        # 等待所有任务完成
        await self.task_queue.join()
        logger.info("所有任务已处理完毕，服务已关闭。")

# --- 辅助函数和主程序 ---

def load_config(path: str = "config.json") -> NodeConfig:
    """
    从 JSON 文件加载配置。

    :param path: 配置文件路径
    :return: 节点配置实例
    """
    try:
        with open(path, 'r', encoding='utf-8') as f:
            config_data = json.load(f)
        return NodeConfig.from_dict(config_data)
    except FileNotFoundError:
        logger.warning(f"配置文件 {path} 未找到，将使用默认配置并生成示例文件。")
        default_config = NodeConfig(
            models={
                "classifier_a": ModelConfig(
                    name="ImageClassifier",
                    path="./models/classifier_a.pkl",
                    model_type=ModelType.CLASSIFICATION
                ),
                "regressor_b": ModelConfig(
                    name="PriceRegressor",
                    path="./models/regressor_b.onnx",
                    model_type=ModelType.REGRESSION
                )
            }
        )
        # 创建示例配置文件
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            # 需要一个辅助函数将dataclass转为可序列化的dict
            import dataclasses
            config_dict = dataclasses.asdict(default_config)
            # 枚举需要转为字符串
            for model in config_dict['models'].values():
                model['model_type'] = model['model_type'].name
            json.dump(config_dict, f, ensure_ascii=False, indent=4)
        return default_config
    except Exception as e:
        logger.error(f"加载配置文件时出错: {e}", exc_info=True)
        raise

async def main():
    """
    主执行函数
    """
    # 1. 加载配置
    config = load_config()

    # 2. 创建和初始化服务
    service = LearningService(config)
    await service.initialize()

    # 3. 启动任务处理协程
    task_processor = asyncio.create_task(service._process_tasks())

    # 4. 模拟API调用和任务调度
    if service.status == ServiceStatus.RUNNING:
        logger.info("--- 模拟API调用 ---")
        # 模拟健康检查
        health = service.get_health()
        logger.info(f"健康检查结果: {health['status']}")

        # 模拟状态查询
        status = service.get_status()
        logger.info(f"服务状态: {json.dumps(status, indent=2, ensure_ascii=False)}")

        # 模拟提交推理任务
        inference_task = await service.schedule_task(
            task_type='inference',
            model_name='classifier_a',
            data={"image_url": "http://example.com/image.jpg"}
        )
        logger.info(f"提交推理任务: {inference_task}")

        # 模拟提交训练任务
        train_task = await service.schedule_task(
            task_type='train',
            model_name='regressor_b',
            data={"dataset_path": "/data/training_data.csv"}
        )
        logger.info(f"提交训练任务: {train_task}")

    # 5. 等待一段时间让任务处理
    await asyncio.sleep(15)

    # 6. 关闭服务
    await service.shutdown()
    task_processor.cancel()
    try:
        await task_processor
    except asyncio.CancelledError:
        logger.info("任务处理器已成功取消。")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("程序被用户中断。")
