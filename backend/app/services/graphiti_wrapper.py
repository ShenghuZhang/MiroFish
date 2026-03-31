"""
Graphiti 核心包装器 - 简化版本
提供异步/同步桥接,以及与 Zep Cloud API 的兼容层
"""

import asyncio
import threading
from typing import Dict, Any, List, Optional
from datetime import datetime
from dataclasses import dataclass, field
from queue import Queue

# Graphiti imports
from graphiti_core import Graphiti
from graphiti_core.llm_client import OpenAIClient
from graphiti_core.llm_client.config import LLMConfig
from graphiti_core.embedder import OpenAIEmbedder
from graphiti_core.embedder.openai import OpenAIEmbedderConfig

# Custom LLM client for structured output compatibility
from .graphiti_llm_client import LangChainStructuredLLMClient

# Import reranker client classes
from graphiti_core.cross_encoder import CrossEncoderClient
from graphiti_core.helpers import semaphore_gather
from graphiti_core.llm_client import LLMConfig, RateLimitError
from graphiti_core.prompts import Message
from graphiti_core.cross_encoder.client import CrossEncoderClient as BaseCrossEncoderClient
from graphiti_core.search.search_config_recipes import (
    COMBINED_HYBRID_SEARCH_CROSS_ENCODER,
    EDGE_HYBRID_SEARCH_CROSS_ENCODER,
    NODE_HYBRID_SEARCH_CROSS_ENCODER
)
from graphiti_core.utils.maintenance.graph_data_operations import build_indices_and_constraints

from ..config import Config


def ontology_to_pydantic_models(ontology: Dict[str, Any]) -> Dict[str, type]:
    """
    Convert ontology entity_types dict to Pydantic BaseModel classes for Graphiti

    Args:
        ontology: Ontology dict with entity_types list

    Returns:
        Dict mapping entity type names to Pydantic BaseModel classes
    """
    from pydantic import BaseModel as PydanticBaseModel, Field, create_model, ConfigDict



    entity_models = {}

    for entity_def in ontology.get("entity_types", []):
        name = entity_def["name"]
        description = entity_def.get("description", f"A {name} entity.")

        # Build Pydantic model fields - use Field with type annotation
        fields = {}
        for attr in entity_def.get("attributes", []):
            attr_name = attr["name"]
            attr_desc = attr.get("description", attr_name)
            fields[attr_name] = (Optional[str], Field(description=attr_desc, default=None))

        # Create Pydantic model dynamically using create_model
        entity_model = create_model(
            name,
            __base__=PydanticBaseModel,
            __doc__=description,
            __config__=ConfigDict(arbitrary_types_allowed=True),
            **fields  # Pass fields directly as dict
        )
        entity_models[name] = entity_model

    return entity_models


# 使用单例事件循环,避免多循环冲突
_event_loop = None
_loop_lock = threading.Lock()


# ==================== Custom Reranker Client ====================

class CustomRerankerClient(BaseCrossEncoderClient):
    """
    自定义 Reranker 客户端

    使用当前 model 而不是硬编码的 DEFAULT_MODEL
    """

    def __init__(
        self,
        config: LLMConfig | None = None,
        client: Any | None = None,
    ):
        """
        Initialize CustomRerankerClient with provided configuration.

        Args:
            config (LLMConfig | None): The configuration for LLM client.
            client (Any | None): An optional async client instance to use.
        """
        if config is None:
            config = LLMConfig()

        self.config = config
        if client is None:
            from openai import AsyncOpenAI
            self.client = AsyncOpenAI(api_key=config.api_key, base_url=config.base_url)
        else:
            self.client = client

    async def rank(self, query: str, passages: list[str]) -> list[tuple[str, float]]:
        import numpy as np
        import openai
        import logging

        logger = logging.getLogger(__name__)

        openai_messages_list: Any = [
            [
                Message(
                    role='system',
                    content='You are an expert tasked with determining whether passage is relevant to query',
                ),
                Message(
                    role='user',
                    content=f"""
                           Respond with "True" if PASSAGE is relevant to QUERY and "False" otherwise.
                           <PASSAGE>
                           {passage}
                           </PASSAGE>
                           <QUERY>
                           {query}
                           </QUERY>
                           """,
                ),
            ]
            for passage in passages
        ]
        try:
            # 使用配置中的 model 而不是硬编码的 DEFAULT_MODEL
            model = self.config.model if self.config.model else 'gpt-4o-mini'

            responses = await semaphore_gather(
                *[
                    self.client.chat.completions.create(
                        model=model,
                        messages=[msg.model_dump() for msg in msgs],
                        temperature=0,
                        max_tokens=1,
                        logit_bias={'6432': 1, '7983': 1},
                        logprobs=True,
                        top_logprobs=2,
                    )
                    for msgs in openai_messages_list
                ]
            )

            responses_top_logprobs = [
                response.choices[0].logprobs.content[0].top_logprobs
                if response.choices[0].logprobs is not None
                and response.choices[0].logprobs.content is not None
                else []
                for response in responses
            ]
            scores: list[float] = []
            for top_logprobs in responses_top_logprobs:
                if len(top_logprobs) == 0:
                    continue
                norm_logprobs = np.exp(top_logprobs[0].logprob)
                if bool(top_logprobs[0].token):
                    scores.append(norm_logprobs)
                else:
                    scores.append(1 - norm_logprobs)

            results = [(passage, score) for passage, score in zip(passages, scores, strict=True)]
            results.sort(reverse=True, key=lambda x: x[1])
            return results
        except openai.RateLimitError as e:
            raise RateLimitError from e
        except Exception as e:
            logger.error(f'Error in generating reranker response: {e}')
            raise


def run_async(coro):
    """
    在同步上下文中运行异步协程

    Flask 是同步框架,Graphiti 是异步的,
    需要这个桥接函数

    使用单例事件循环,避免 Neo4j 连接池在多个循环间共享导致的冲突
    """
    global _event_loop
    with _loop_lock:
        if _event_loop is None or _event_loop.is_closed():
            _event_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(_event_loop)
        return _event_loop.run_until_complete(coro)


# ==================== 数据模型 ====================

@dataclass
class GraphitiNode:
    """Graphiti 节点数据结构"""
    uuid_: str
    name: Optional[str] = None
    labels: List[str] = field(default_factory=list)
    summary: Optional[str] = None
    attributes: Dict[str, Any] = field(default_factory=dict)
    created_at: Optional[datetime] = None


@dataclass
class GraphitiEdge:
    """Graphiti 边数据结构"""
    uuid_: str
    fact: str
    source_node_uuid: str
    target_node_uuid: str
    name: Optional[str] = None
    attributes: Dict[str, Any] = field(default_factory=dict)
    created_at: Optional[datetime] = None
    valid_at: Optional[datetime] = None
    invalid_at: Optional[datetime] = None
    expired_at: Optional[datetime] = None
    episodes: list = field(default_factory=list)


@dataclass
class GraphitiEpisodeData:
    """Graphiti Episode 数据结构"""
    uuid: str = ""
    nodes: List[GraphitiNode] = field(default_factory=list)
    edges: List[GraphitiEdge] = field(default_factory=list)


@dataclass
class GraphitiInfo:
    """图谱信息"""
    graph_id: str
    node_count: int
    edge_count: int
    entity_types: List[str] = field(default_factory=list)


# ==================== Graphiti 客户端 ====================

class GraphitiClient:
    """
    Graphiti 客户端包装器 - 简化实现

    直接使用 Graphiti 的 LLMClient 和 Embedder
    """

    def __init__(
        self,
        uri: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        llm_client: Optional[OpenAIClient] = None,
        embedder: Optional[OpenAIEmbedder] = None,
    ):
        self.uri = uri or Config.NEO4J_URI
        self.user = user or Config.NEO4J_USER
        self.password = password or Config.NEO4J_PASSWORD

        # 初始化 LLM 和 Embedder
        if llm_client is None:
            llm_config = LLMConfig(
                api_key=Config.LLM_API_KEY,
                model=Config.LLM_MODEL_NAME,
                base_url=Config.LLM_BASE_URL,
                # Graphiti 使用 ModelSize.small 来获取节点,确保 small_model 与主模型相同
                small_model=Config.LLM_MODEL_NAME
            )
            # 使用自定义 LLM Client 支持 function_calling 方法
            llm_client = LangChainStructuredLLMClient(config=llm_config)

        if embedder is None:
            embedder_config = OpenAIEmbedderConfig(
                api_key=Config.ZHIPUAI_API_KEY,
                embedding_model="embedding-3",
                base_url="https://open.bigmodel.cn/api/paas/v4",
                embedding_dim=2048
            )
            embedder = OpenAIEmbedder(config=embedder_config)

        self.llm_client = llm_client
        self.embedder = embedder

        # Graphiti 客户端(延迟初始化)
        self._graphiti: Optional[Graphiti] = None
        self._initialized = False
        self._lock = threading.Lock()

    def _get_graphiti(self) -> Graphiti:
        """获取或创建 Graphiti 客户端(线程安全)"""
        with self._lock:
            if self._graphiti is None:
                # 为 cross_encoder 创建配置 (使用 LLMConfig)
                reranker_config = LLMConfig(
                    api_key=Config.LLM_API_KEY,
                    model=Config.LLM_MODEL_NAME,
                    base_url=Config.LLM_BASE_URL
                )

                # 创建 cross_encoder 客户端 - 使用自定义 reranker
                cross_encoder = CustomRerankerClient(config=reranker_config)

                self._graphiti = Graphiti(
                    uri=self.uri,
                    user=self.user,
                    password=self.password,
                    llm_client=self.llm_client,
                    embedder=self.embedder,
                    cross_encoder=cross_encoder
                )
                # Create required indices and constraints for Graphiti
                run_async(build_indices_and_constraints(self._graphiti.driver))
                self._initialized = True
            return self._graphiti

    # ==================== Graph Management ====================

    def graph_create(
        self,
        graph_id: str,
        name: str,
        description: str
    ) -> str:
        """
        创建图谱

        返回 graph_id(实际上是 group_id)
        """
        graphiti = self._get_graphiti()

        # Graphiti 中不需要显式创建图谱
        # 只返回 group_id 即可
        return graph_id

    def graph_delete(self, graph_id: str):
        """
        删除图谱

        删除指定 group_id 的所有数据
        """
        graphiti = self._get_graphiti()

        # 执行 Cypher 查询删除 group 的所有节点和边
        query = """
        MATCH (n:Entity)
        WHERE n.group_id = $graph_id
        DETACH DELETE n
        """
        result = run_async(graphiti.driver.execute_query(query, {"graph_id": graph_id}))

        # 清除 Graphiti 客户端缓存
        if hasattr(self, '_graphiti'):
            self._graphiti = None
            self._initialized = False
        return result

    def graph_add(
        self,
        graph_id: str,
        data: str,
        type: str = "text",
        entity_types: Optional[Dict[str, type]] = None
    ) -> GraphitiEpisodeData:
        """
        添加内容到图谱

        Args:
            graph_id: Graph ID
            data: Episode content
            type: Content type (unused in Graphiti)
            entity_types: Pydantic BaseModel classes for entity type definitions

        Returns:
            包含节点和边的 Episode 数据
        """
        import logging
        import time
        logger = logging.getLogger(__name__)
        start_time = time.time()

        graphiti = self._get_graphiti()

        # 使用当前时间作为 reference_time
        reference_time = datetime.now()

        # 调用 Graphiti 的 add_episode 方法
        logger.debug(f"graph_add called with entity_types: {entity_types is not None}")
        if entity_types:
            logger.debug(f"  entity_types keys: {list(entity_types.keys())}")

        episode_start = time.time()
        result = run_async(graphiti.add_episode(
            name="Episode",
            episode_body=data,
            reference_time=reference_time,
            source_description="Graph addition",
            group_id=graph_id,
            entity_types=entity_types
        ))
        episode_time = time.time() - episode_start
        logger.info(f"graph_add: add_episode completed in {episode_time:.2f}s, {len(result.nodes)} nodes, {len(result.edges)} edges")

        # 转换为兼容格式
        return GraphitiEpisodeData(
            uuid=result.episode.uuid or "",
            nodes=[GraphitiNode(
                uuid_=node.uuid,
                name=node.name,
                labels=list(node.labels or []),
                summary=node.summary,
                attributes=dict(node.attributes or {}),
                created_at=node.created_at,
            ) for node in result.nodes],
            edges=[GraphitiEdge(
                uuid_=edge.uuid,
                fact=edge.fact,
                source_node_uuid=edge.source_node_uuid,
                target_node_uuid=edge.target_node_uuid,
                name=edge.name,
                attributes={},  # EntityEdge doesn't have attributes field
                created_at=edge.created_at,
                valid_at=edge.valid_at,
                invalid_at=edge.invalid_at,
                expired_at=edge.expired_at,
            ) for edge in result.edges]
        )

    def graph_add_batch(
        self,
        graph_id: str,
        episodes: List[str],
        entity_types: Optional[Dict[str, type]] = None
    ) -> List[GraphitiEpisodeData]:
        """
        批量添加内容到图谱

        Args:
            graph_id: Graph ID
            episodes: List of episode content strings
            entity_types: Pydantic BaseModel classes for entity type definitions
        """
        results = []
        for episode_data in episodes:
            result = self.graph_add(graph_id, episode_data, entity_types=entity_types)
            results.append(result)
        return results

    def graph_search(
        self,
        graph_id: str,
        query: str,
        config: str = "NODE_HYBRID_SEARCH_CROSS_ENCODER",
        limit: int = 10,
        scope: str = "both"
    ) -> Dict[str, Any]:
        """
        语义搜索

        返回搜索结果
        """
        graphiti = self._get_graphiti()

        # 调用 Graphiti 的 search 方法
        # Note: Graphiti's search returns EntityEdge objects
        results = run_async(graphiti.search(
            query=query,
            num_results=limit,
            group_ids=[graph_id]
        ))

        # 构建响应
        nodes_list = []
        edges_list = []

        # Extract unique nodes from edges
        node_uuids = set()
        for edge in results:
            if edge.source_node_uuid:
                node_uuids.add(edge.source_node_uuid)
            if edge.target_node_uuid:
                node_uuids.add(edge.target_node_uuid)

        # Get nodes by UUIDs
        if node_uuids:
            from graphiti_core.nodes import EntityNode
            nodes = run_async(EntityNode.get_by_uuids(graphiti.driver, list(node_uuids)))
            for node in nodes:
                nodes_list.append({
                    "uuid": node.uuid or "",
                    "name": node.name,
                    "labels": list(node.labels or []),
                    "summary": node.summary or "",
                    "attributes": dict(node.attributes or {}),
                    "created_at": str(node.created_at) if node.created_at else None,
                })

        # Process edges
        return {
            "nodes": nodes_list,
            "edges": edges_list,
            "total_count": len(nodes_list) + len(edges_list)
        }

    def graph_node_get_by_graph_id(
        self,
        graph_id: str,
        limit: int = 10000
    ) -> List[GraphitiNode]:
        """
        获取图谱的所有节点
        """
        graphiti = self._get_graphiti()

        # 执行 Cypher 查询
        query = f"""
        MATCH (n:Entity)
        WHERE n.group_id = $graph_id
        RETURN n
        """

        result = run_async(graphiti.driver.execute_query(query, {"graph_id": graph_id}))

        nodes_list = []
        # Neo4j driver 返回 EagerResult，需要访问 records 属性
        for record in result.records:
            # record["n"] 返回一个 Node 对象
            node_obj = record["n"]
            node = GraphitiNode(
                uuid_=node_obj.get("uuid", ""),
                name=node_obj.get("name"),
                labels=node_obj.get("labels", []),
                summary=node_obj.get("summary", ""),
                attributes=node_obj.get("attributes", {}),
                created_at=None
            )
            nodes_list.append(node)

        return nodes_list

    def graph_edge_get_by_graph_id(
        self,
        graph_id: str,
        limit: int = 10000
    ) -> List[GraphitiEdge]:
        """
        获取图谱的所有边
        """
        graphiti = self._get_graphiti()

        # 执行 Cypher 查询
        # 关系类型是动态的（如 MENTIONS, PROVIDES 等），不指定类型以获取所有关系
        query = """
        MATCH (n:Entity)-[r]->(m:Entity)
        WHERE n.group_id = $graph_id
        RETURN r, n.uuid AS source_uuid, m.uuid AS target_uuid
        LIMIT $limit
        """

        result = run_async(graphiti.driver.execute_query(query, {"graph_id": graph_id, "limit": limit}))

        edges_list = []
        for record in result.records:
            edge_obj = record["r"]
            edge = GraphitiEdge(
                uuid_=edge_obj.get("uuid", ""),
                name=edge_obj.get("name", ""),
                fact=edge_obj.get("fact", ""),
                source_node_uuid=record.get("source_uuid", ""),
                target_node_uuid=record.get("target_uuid", ""),
                attributes=edge_obj.get("attributes", {}),
                created_at=None,
                valid_at=edge_obj.get("valid_at"),
                invalid_at=edge_obj.get("invalid_at"),
                expired_at=edge_obj.get("expired_at")
            )
            edges_list.append(edge)

        return edges_list

    def graph_node_get(
        self,
        uuid_: str
    ) -> Optional[GraphitiNode]:
        """
        获取单个节点
        """
        graphiti = self._get_graphiti()

        # 执行 Cypher 查询
        query = """
        MATCH (n:Entity)
        WHERE n.uuid = $uuid_
        RETURN n
        """

        result = run_async(graphiti.driver.execute_query(query, {"uuid_": uuid_}))

        if not result.records:
            return None

        record = result.records[0]
        node_obj = record["n"]
        node = GraphitiNode(
            uuid_=node_obj.get("uuid", ""),
            name=node_obj.get("name"),
            labels=node_obj.get("labels", []),
            summary=node_obj.get("summary", ""),
            attributes=node_obj.get("attributes", {}),
            created_at=None
        )
        return node

    def graph_node_get_entity_edges(
        self,
        uuid_: str
    ) -> List[GraphitiEdge]:
        """
        获取节点的相关边
        """
        graphiti = self._get_graphiti()

        # 执行 Cypher 查询
        # 关系类型是动态的，不指定类型以获取所有关系
        query = """
        MATCH (n:Entity)-[r]->(m:Entity)
        WHERE n.uuid = $uuid_
        RETURN r, n.uuid AS source_uuid, m.uuid AS target_uuid
        """

        result = run_async(graphiti.driver.execute_query(query, {"uuid_": uuid_}))

        edges_list = []
        for record in result.records:
            edge_obj = record["r"]
            edge = GraphitiEdge(
                uuid_=edge_obj.get("uuid", ""),
                name=edge_obj.get("name", ""),
                fact=edge_obj.get("fact", ""),
                source_node_uuid=record.get("source_uuid", ""),
                target_node_uuid=record.get("target_uuid", ""),
                attributes=edge_obj.get("attributes", {}),
                created_at=None,
                valid_at=edge_obj.get("valid_at"),
                invalid_at=edge_obj.get("invalid_at"),
                expired_at=edge_obj.get("expired_at")
            )
            edges_list.append(edge)

        return edges_list


# ==================== Zep Compatibility Layer ====================

class _ZepNodeInterface:
    """内部：Node 操作接口"""

    def __init__(self, client: GraphitiClient):
        self._client = client

    def get(self, uuid_: str) -> Optional[Dict]:
        """获取单个节点"""
        node = self._client.graph_node_get(uuid_=uuid_)
        if node:
            return {
                "uuid": node.uuid_,
                "name": node.name,
                "labels": node.labels,
                "summary": node.summary,
                "attributes": node.attributes,
                "created_at": str(node.created_at) if node.created_at else None,
            }
        return None

    def get_entity_edges(self, node_uuid: str) -> List[GraphitiEdge]:
        """获取节点的相关边"""
        return self._client.graph_node_get_entity_edges(uuid_=node_uuid)


class _ZepGraphInterface:
    """内部：Graph 操作接口"""

    def __init__(self, client: GraphitiClient):
        self._client = client
        self.node = _ZepNodeInterface(client)

    def add(self, graph_id: str, data: str, type: str = "text", entity_types: Optional[Dict[str, type]] = None) -> GraphitiEpisodeData:
        """添加数据到图谱"""
        return self._client.graph_add(
            graph_id=graph_id,
            data=data,
            type=type,
            entity_types=entity_types
        )

    def search(
        self,
        graph_id: str,
        query: str,
        limit: int = 10,
        scope: str = "both",
        reranker: str = None
    ) -> Dict[str, Any]:
        """语义搜索"""
        return self._client.graph_search(
            graph_id=graph_id,
            query=query,
            limit=limit,
            scope=scope
        )


class Zep:
    """
    Zep Cloud API 兼容类

    提供与原 Zep Cloud 相同的接口，内部使用 Graphiti

    使用方式:
        zep = Zep()
        zep.graph.add(graph_id="...", data="...")
        zep.graph.search(graph_id="...", query="...")
        zep.graph.node.get(uuid_="...")
    """

    def __init__(self):
        """初始化 Zep 兼容层"""
        # 创建 Graphiti 客户端
        self._graphiti_client = GraphitiClient()
        self.session_id = "default"
        # 提供嵌套的 graph 接口
        self.graph = _ZepGraphInterface(self._graphiti_client)

    def create_graph(
        self,
        name: str,
        description: str
    ) -> str:
        """创建图谱"""
        return self._graphiti_client.graph_create(
            graph_id=f"mirofish_{self.session_id}",
            name=name,
            description=description
        )

    def delete_graph(self, graph_id: str):
        """删除图谱"""
        self._graphiti_client.graph_delete(graph_id)

    def graph_delete(self, graph_id: str):
        """删除图谱（别名）"""
        self._graphiti_client.graph_delete(graph_id)

    def graph_add(self, graph_id: str, data: str, type: str = "text", entity_types: Optional[Dict[str, type]] = None) -> GraphitiEpisodeData:
        """添加数据到图谱（直接调用）"""
        return self._graphiti_client.graph_add(
            graph_id=graph_id,
            data=data,
            type=type,
            entity_types=entity_types
        )

    def graph_search(
        self,
        graph_id: str,
        query: str,
        limit: int = 10,
        scope: str = "both"
    ) -> Dict[str, Any]:
        """语义搜索（直接调用）"""
        return self._graphiti_client.graph_search(
            graph_id=graph_id,
            query=query,
            limit=limit,
            scope=scope
        )

    def graph_create(
        self,
        graph_id: str,
        name: str,
        description: str
    ) -> str:
        """创建图谱（直接调用）"""
        return self._graphiti_client.graph_create(
            graph_id=graph_id,
            name=name,
            description=description
        )

    def graph_node_get_by_graph_id(
        self,
        graph_id: str,
        limit: int = 10000
    ) -> List[GraphitiNode]:
        """获取图谱的所有节点（直接调用）"""
        return self._graphiti_client.graph_node_get_by_graph_id(graph_id, limit=limit)

    def graph_edge_get_by_graph_id(
        self,
        graph_id: str,
        limit: int = 10000
    ) -> List[GraphitiEdge]:
        """获取图谱的所有边（直接调用）"""
        return self._graphiti_client.graph_edge_get_by_graph_id(graph_id, limit=limit)
