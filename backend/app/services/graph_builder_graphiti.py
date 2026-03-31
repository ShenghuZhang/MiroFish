"""
图谱构建服务 - Graphiti 版本
使用 Graphiti + Neo4j 构建知识图谱
保持与原 graph_builder.py 的业务逻辑兼容
"""

import os
import uuid
import time
import threading
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass

from .graphiti_wrapper import GraphitiClient, GraphitiNode, GraphitiEdge, run_async
from ..config import Config
from ..models.task import TaskManager, TaskStatus
from dataclasses import field


@dataclass
class GraphInfo:
    """图谱信息"""
    graph_id: str
    node_count: int
    edge_count: int
    entity_types: List[str]
    episode_count: int = field(default=0)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "graph_id": self.graph_id,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "entity_types": self.entity_types,
            "episode_count": self.episode_count,
        }


class GraphBuilderService:
    """
    图谱构建服务 - Graphiti 版本

    关键变化：
    - 使用 GraphitiClient 替代 Zep
    - graph_id 映射到 group_id
    - Episode 立即可用，无需等待 processed 状态
    - 保持原有业务逻辑和 API 接口不变
    """

    def __init__(self, api_key: Optional[str] = None):
        """
        初始化图谱构建服务

        注意：api_key 参数已废弃，保留用于兼容性
        Graphiti 使用 Neo4j 配置
        """
        # 使用 Graphiti 客户端（内部已处理 Neo4j 连接）
        self.client = GraphitiClient()
        self.task_manager = TaskManager()
        self._entity_types = None  # Store entity_types from ontology

    def build_graph_async(
        self,
        text: str,
        ontology: Dict[str, Any],
        graph_name: str = "MiroFish Graph",
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        batch_size: int = 3
    ) -> str:
        """
        异步构建图谱

        Args:
            text: 输入文本
            ontology: 本体定义（来自接口1的输出）
            graph_name: 图谱名称
            chunk_size: 文本块大小
            chunk_overlap: 块重叠大小
            batch_size: 每批发送的块数量

        Returns:
            任务ID

        ⚠️ Graphiti 变化：无需等待 episode processed 状态
        """
        # 创建任务
        task_id = self.task_manager.create_task(
            task_type="graph_build",
            metadata={
                "graph_name": graph_name,
                "chunk_size": chunk_size,
                "text_length": len(text),
            }
        )

        # 在后台线程中执行构建
        thread = threading.Thread(
            target=self._build_graph_worker,
            args=(task_id, text, ontology, graph_name, chunk_size, chunk_overlap, batch_size),
            daemon=True
        )
        thread.start()

        return task_id

    def _build_graph_worker(
        self,
        task_id: str,
        text: str,
        ontology: Dict[str, Any],
        graph_name: str,
        chunk_size: int,
        chunk_overlap: int,
        batch_size: int
    ):
        """图谱构建工作线程"""
        try:
            self.task_manager.update_task(
                task_id,
                status=TaskStatus.PROCESSING,
                progress=5,
                message="开始构建图谱..."
            )

            # 1. 创建图谱
            graph_id = self.create_graph(graph_name)
            self.task_manager.update_task(
                task_id,
                progress=10,
                message=f"图谱已创建: {graph_id}"
            )

            # 2. 设置本体
            self.set_ontology(graph_id, ontology)
            self.task_manager.update_task(
                task_id,
                progress=15,
                message="本体已设置"
            )

            # 3. 文本分块
            from .text_processor import TextProcessor
            chunks = TextProcessor.split_text(text, chunk_size, chunk_overlap)
            total_chunks = len(chunks)
            self.task_manager.update_task(
                task_id,
                progress=20,
                message=f"文本已分割为 {total_chunks} 个块"
            )

            # 4. 分批发送数据
            episode_uuids = self.add_text_batches(
                graph_id, chunks, batch_size,
                lambda msg, prog: self.task_manager.update_task(
                    task_id,
                    progress=20 + int(prog * 0.4),  # 20-60%
                    message=msg
                )
            )

            # ⚠️ Graphiti 变化：无需等待 episode processed 状态
            # Episode 在添加后立即可用，节点和边已提取完成
            self.task_manager.update_task(
                task_id,
                progress=90,
                message="数据处理完成"
            )

            # 5. 获取图谱信息
            self.task_manager.update_task(
                task_id,
                progress=90,
                message="获取图谱信息..."
            )

            graph_info = self._get_graph_info(graph_id)

            # 完成
            self.task_manager.complete_task(task_id, {
                "graph_id": graph_id,
                "graph_info": graph_info.to_dict(),
                "chunks_processed": total_chunks,
            })

        except Exception as e:
            import traceback
            error_msg = f"{str(e)}\n{traceback.format_exc()}"
            self.task_manager.fail_task(task_id, error_msg)

    def create_graph(self, name: str) -> str:
        """创建图谱（Graphiti 使用 group_id）"""
        graph_id = f"mirofish_{uuid.uuid4().hex[:16]}"

        # Graphiti: 只返回 group_id，无需显式创建
        self.client.graph_create(
            graph_id=graph_id,
            name=name,
            description="MiroFish Social Simulation Graph"
        )

        return graph_id

    def set_ontology(self, graph_id: str, ontology: Dict[str, Any]):
        """设置图谱本体

        Graphiti 的本体通过 entity_types 参数在 add_episode 时传递
        这里保存到实例中，供添加数据时使用

        Args:
            graph_id: Graph ID
            ontology: Ontology dict with entity_types list
        """
        # 保存到实例中
        self._current_ontology = ontology
        self._current_graph_id = graph_id

        # Convert entity_types to Pydantic BaseModel classes
        from .graphiti_wrapper import ontology_to_pydantic_models
        import logging
        logger = logging.getLogger(__name__)
        self._entity_types = ontology_to_pydantic_models(ontology)
        logger.info(f"set_ontology: Converted {len(ontology.get('entity_types', []))} entity types to Pydantic models")
        logger.info(f"  Entity types: {list(self._entity_types.keys())}")

    def add_text_batches(
        self,
        graph_id: str,
        chunks: List[str],
        batch_size: int = 3,
        progress_callback: Optional[Callable] = None
    ) -> List[str]:
        """
        分批添加文本到图谱

        ⚠️ Graphiti 变化：
        - 返回 episode uuid 列表
        - Episode 立即可用，无需等待 processed
        """
        import logging
        logger = logging.getLogger(__name__)
        episode_uuids = []
        total_chunks = len(chunks)

        logger.info(f"add_text_batches: Starting with {total_chunks} chunks, batch_size={batch_size}")

        for i in range(0, total_chunks, batch_size):
            batch_chunks = chunks[i:i + batch_size]
            batch_num = i // batch_size + 1
            total_batches = (total_chunks + batch_size - 1) // batch_size

            if progress_callback:
                progress = (i + len(batch_chunks)) / total_chunks
                progress_callback(
                    f"发送第 {batch_num}/{total_batches} 批数据 ({len(batch_chunks)} 块)...",
                    progress
                )

            # 发送到 Graphiti（graph_add_batch expects List[str], not GraphitiEpisodeData objects）
            try:
                logger.debug(f"add_text_batches: Processing batch {batch_num}/{total_batches}")
                batch_result = self.client.graph_add_batch(graph_id, batch_chunks, entity_types=self._entity_types)

                # 收集返回的 episode uuid
                if batch_result and isinstance(batch_result, list):
                    for result in batch_result:
                        # Graphiti 返回 GraphitiEpisodeData 对象，直接访问 uuid 属性
                        episode_uuid = result.uuid
                        episode_uuids.append(episode_uuid)
                    logger.debug(f"add_text_batches: Batch {batch_num} returned {len(batch_result)} episodes")
                else:
                    logger.warning(f"add_text_batches: Batch {batch_num} returned unexpected result: {type(batch_result)}")

                # 避免请求过快
                time.sleep(1)

            except Exception as e:
                import traceback
                logger.error(f"add_text_batches: Error in batch {batch_num}: {str(e)}")
                logger.debug(traceback.format_exc())
                if progress_callback:
                    progress_callback(f"批次 {batch_num} 发送失败: {str(e)}", 0)
                raise

        logger.info(f"add_text_batches: Completed {len(episode_uuids)} episodes")
        return episode_uuids

    def _wait_for_episodes(
        self,
        episode_uuids: List[str],
        progress_callback: Optional[Callable] = None,
        timeout: int = 600
    ):
        """
        等待所有 episode 处理完成

        ⚠️ Graphiti 变化：
        - Graphiti 的 Episode 添加后立即可用
        - 不需要等待 processed 状态
        - 此方法保留用于兼容，直接返回
        """
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"_wait_for_episodes: Called with {len(episode_uuids)} episodes")

        if not episode_uuids:
            if progress_callback:
                progress_callback("无需等待（没有 episode）", 1.0)
            return

        # Graphiti: Episode 立即可用，直接标记完成
        total_episodes = len(episode_uuids)

        if progress_callback:
            progress_callback(
                f"处理完成: {total_episodes}/{total_episodes}",
                1.0
            )

        logger.info(f"_wait_for_episodes: Completed")

    def _get_graph_info(self, graph_id: str) -> GraphInfo:
        """获取图谱信息"""
        # 获取节点（分页）
        nodes = self.client.graph_node_get_by_graph_id(graph_id, limit=10000)

        # 获取边（分页）
        edges = self.client.graph_edge_get_by_graph_id(graph_id, limit=10000)

        # 统计实体类型
        entity_types = set()
        for node in nodes:
            if node.labels:
                for label in node.labels:
                    if label not in ["Entity", "Node"]:
                        entity_types.add(label)

        # 统计 episode 数量（Graphiti 特有）
        episode_count = 0
        for edge in edges:
            episode_count += len(edge.episodes)

        return GraphInfo(
            graph_id=graph_id,
            node_count=len(nodes),
            edge_count=len(edges),
            entity_types=list(entity_types),
            episode_count=episode_count
        )

    def get_graph_data(self, graph_id: str) -> Dict[str, Any]:
        """
        获取完整图谱数据（包含详细信息）

        Args:
            graph_id: 图谱ID

        Returns:
            包含nodes和edges的字典，包括时间信息、属性等详细数据
        """
        # 获取节点
        nodes = self.client.graph_node_get_by_graph_id(graph_id, limit=10000)

        # 获取边
        edges = self.client.graph_edge_get_by_graph_id(graph_id, limit=10000)

        # 创建节点映射用于获取节点名称
        node_map = {}
        for node in nodes:
            node_map[node.uuid_] = node.name or ""

        nodes_data = []
        for node in nodes:
            created_at = node.created_at

            nodes_data.append({
                "uuid": node.uuid_,
                "name": node.name,
                "labels": node.labels or [],
                "summary": node.summary or "",
                "attributes": node.attributes or {},
                "created_at": str(created_at) if created_at else None,
            })

        edges_data = []
        for edge in edges:
            # 时间信息
            created_at = edge.created_at
            valid_at = edge.valid_at
            invalid_at = edge.invalid_at
            expired_at = edge.expired_at

            # episodes 关联
            episodes = edge.episodes

            # fact_type
            fact_type = edge.name or ""

            edges_data.append({
                "uuid": edge.uuid_,
                "name": edge.name or "",
                "fact": edge.fact or "",
                "fact_type": fact_type,
                "source_node_uuid": edge.source_node_uuid,
                "target_node_uuid": edge.target_node_uuid,
                "source_node_name": node_map.get(edge.source_node_uuid, ""),
                "target_node_name": node_map.get(edge.target_node_uuid, ""),
                "attributes": edge.attributes or {},
                "created_at": str(created_at) if created_at else None,
                "valid_at": str(valid_at) if valid_at else None,
                "invalid_at": str(invalid_at) if invalid_at else None,
                "expired_at": str(expired_at) if expired_at else None,
                "episodes": episodes or [],
            })

        return {
            "graph_id": graph_id,
            "nodes": nodes_data,
            "edges": edges_data,
            "node_count": len(nodes_data),
            "edge_count": len(edges_data),
        }

    def delete_graph(self, graph_id: str):
        """删除图谱"""
        self.client.graph_delete(graph_id)
