#!/usr/bin/env python3
"""
检查 Neo4j 节点的实际标签
用于调试 0 个人设加载问题
"""

import sys
import os

sys.path.insert(0, '/Users/moya/Workspace/MiroFish/backend')

from app.services.graphiti_wrapper import GraphitiClient, run_async
from app.config import Config

def main():
    graph_id = 'mirofish_f04a287fed984adf'

    print(f"=== 检查图谱 {graph_id} 的节点标签 ===\n")

    try:
        client = GraphitiClient()
        graphiti = client._get_graphiti()

        # 查询所有节点及其标签
        query = f"""
        MATCH (n:Entity)
        WHERE n.group_id = $graph_id
        RETURN n.name, n.labels, n.summary
        ORDER BY n.name
        """

        async def async_query():
            result = await graphiti.driver.execute_query(query, {"graph_id": graph_id})
            return result

        result = run_async(async_query())

        print(f"总共 {len(result.records)} 个节点:\n")

        # 统计标签分布
        label_distribution = {}
        nodes_only_entity_label = []

        for i, record in enumerate(result.records, 1):
            name = record.get("n.name", "unknown")
            labels = record.get("n.labels", [])
            summary = record.get("n.summary", "")[:50]

            # 统计标签
            for label in labels:
                label_distribution[label] = label_distribution.get(label, 0) + 1

            # 检查是否只有 Entity 标签
            has_custom_label = any(l not in ["Entity", "Node"] for l in labels)
            if not has_custom_label:
                nodes_only_entity_label.append(name)

            print(f"{i:2d}. {name:30s}")
            print(f"    标签: {labels}")
            print(f"    摘要: {summary}")
            print()

        print(f"\n=== 标签统计 ===")
        for label, count in sorted(label_distribution.items(), key=lambda x: -x[1]):
            print(f"  {label}: {count} 个")

        print(f"\n=== 只有 'Entity' 标签的节点 ===")
        print(f"  共 {len(nodes_only_entity_label)} 个节点")
        for name in nodes_only_entity_label:
            print(f"  - {name}")

        # 检查关系类型
        print(f"\n=== 检查关系类型 ===")
        edge_query = f"""
        MATCH (n:Entity)-[r]->(m:Entity)
        WHERE n.group_id = $graph_id
        RETURN DISTINCT type(r) AS relationship_type
        LIMIT 20
        """

        async def async_edge_query():
            edge_result = await graphiti.driver.execute_query(edge_query, {"graph_id": graph_id})
            return edge_result

        edge_result = run_async(async_edge_query())

        print(f"找到{len(edge_result.records)} 种关系类型:")
        for i, record in enumerate(edge_result.records, 1):
            rel_type = record.get("relationship_type", "unknown")
            print(f"  {i}. {rel_type}")

    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
