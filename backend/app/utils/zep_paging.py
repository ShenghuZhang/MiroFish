"""
Graphiti Graph 分页读取工具

Graphiti 使用搜索而非分页 API，此模块封装获取所有结果的逻辑
"""

from ..services.graphiti_wrapper import Zep, GraphitiNode as ZepNode, GraphitiEdge as ZepEdge
from .logger import get_logger

logger = get_logger('mirofish.zep_paging')

_DEFAULT_PAGE_SIZE = 100
_MAX_NODES = 2000
_MAX_RETRIES = 3
_DEFAULT_RETRY_DELAY = 2.0  # seconds, doubles each retry


def fetch_all_nodes(
    client: Zep,
    graph_id: str,
    page_size: int = _DEFAULT_PAGE_SIZE,
    max_items: int = _MAX_NODES,
    max_retries: int = _MAX_RETRIES,
    retry_delay: float = _DEFAULT_RETRY_DELAY
) -> list[ZepNode]:
    """
    获取图谱节点，最多返回 max_items 条（默认 2000）。

    Graphiti 使用搜索获取所有节点，支持大结果集。
    """
    all_nodes: list[ZepNode] = []
    page_num = 0

    # 使用搜索获取节点
    try:
        results = client.graph_node_get_by_graph_id(
            graph_id=graph_id,
            limit=max_items
        )

        for node in results:
            # 转换为 Zep 兼容格式
            all_nodes.append(ZepNode(
                uuid_=node.uuid_,
                name=node.name,
                labels=node.labels or [],
                summary=node.summary or "",
                attributes=node.attributes or {},
                created_at=node.created_at
            ))

    except Exception as e:
        logger.error(f"获取节点失败: {str(e)}")
        return all_nodes

    logger.info(f"获取到 {len(all_nodes)} 个节点")
    return all_nodes


def fetch_all_edges(
    client: Zep,
    graph_id: str,
    page_size: int = _DEFAULT_PAGE_SIZE,
    max_items: int = _MAX_NODES,
    max_retries: int = _MAX_RETRIES,
    retry_delay: float = _DEFAULT_RETRY_DELAY
) -> list[ZepEdge]:
    """
    获取图谱所有边，返回完整列表。

    Graphiti 使用搜索获取所有边，支持大结果集。
    """
    all_edges: list[ZepEdge] = []
    page_num = 0

    # 使用搜索获取边
    try:
        results = client.graph_edge_get_by_graph_id(
            graph_id=graph_id,
            limit=max_items
        )

        for edge in results:
            # 转换为 Zep 兼容格式
            all_edges.append(ZepEdge(
                uuid_=edge.uuid_,
                name=edge.name,
                fact=edge.fact,
                source_node_uuid=edge.source_node_uuid,
                target_node_uuid=edge.target_node_uuid,
                attributes=edge.attributes or {},
                created_at=edge.created_at,
                valid_at=edge.valid_at,
                invalid_at=edge.invalid_at,
                expired_at=edge.expired_at,
                episodes=edge.episodes
            ))

    except Exception as e:
        logger.error(f"获取边失败: {str(e)}")
        return all_edges

    logger.info(f"获取到 {len(all_edges)} 条边")
    return all_edges
