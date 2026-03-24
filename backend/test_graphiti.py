#!/usr/bin/env python3
"""
测试 Graphiti + Neo4j 集成
验证迁移是否正常工作
"""

import sys
sys.path.append("/Users/moya/Workspace/MiroFish/backend")

from app.services.graphiti_wrapper import Zep, GraphitiClient, run_async
from app.config import Config


def test_graphiti_basic():
    """测试 Graphiti 基本操作"""
    print("=== 测试 Graphiti 基本操作 ===")

    try:
        # 1. 创建 Graphiti 客户端
        client = GraphitiClient(
            uri=Config.NEO4J_URI,
            user=Config.NEO4J_USER,
            password=Config.NEO4J_PASSWORD
        )

        # 2. 构建索引
        print("✓ 构建索引和约束...") 
        run_async(client._get_graphiti().build_indices_and_constraints())
        print("✓ 索引和约束构建完成")

        # 3. 创建一个测试图谱
        test_graph_id = "test_graphiti_" + Config.NEO4J_USER

        print(f"✓ 创建测试图谱: {test_graph_id}")
        client.graph_create(
            graph_id=test_graph_id,
            name="测试图谱",
            description="Graphiti测试图谱"
        )

        # 4. 添加一些测试数据
        test_content = """
        Alice is a software engineer who works at OpenAI. Bob is a data scientist at the same company.
        Alice manages Bob directly, who reports to her.
        Alice created Project Z in 2023.
        Project Z was released in early 2024 and became very popular.
        In 2025, Project Z won the Technical Excellence Award.
        """

        print(f"✓ 添加测试内容...")
        result = client.graph_add(
            graph_id=test_graph_id,
            data=test_content,
            type="text"
        )

        print(f"✓ 创建了 {len(result.nodes)} 个节点, {len(result.edges)} 条边")
        print(f"   - 节点示例: {result.nodes[0].name if result.nodes else '无节点'}")
        print(f"   - 边示例: {result.edges[0].fact if result.edges else '无边'}")

        # 5. 搜索测试
        print(f"\n✓ 测试语义搜索...")
        search_results = client.graph_search(
            graph_id=test_graph_id,
            query="Alice and Bob relationship",
            limit=5
        )

        print(f"✓ 搜索完成，找到 {search_results.get('total_count', 0)} 条相关信息")

        # 清理测试图谱
        print(f"\n✓ 删除测试图谱...")
        client.graph_delete(test_graph_id)
        print("✓ 测试图谱已删除")

        return True

    except Exception as e:
        print(f"❌ 测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def test_graphiti_wrapper():
    """测试 Zep 兼容层"""
    print("\n=== 测试 Zep 兼容层 ===")

    try:
        # 使用 Zep 兼容接口
        zep = Zep()  # api_key 已废弃，使用 Neo4j 配置

        # 测试 graph_create
        graph_id = zep.create_graph(
            name="测试兼容图谱",
            description="测试 Zep 兼容层"
        )
        print(f"✓ 通过 Zep 兼容接口创建图谱: {graph_id}")

        # 测试 graph_add
        result = zep.graph_add(
            graph_id=graph_id,
            data="John is a researcher.",
            type="text"
        )
        print(f"✓ 添加内容，返回 {len(result.nodes)} 个节点, {len(result.edges)} 条边")

        # 测试 graph_search
        search_result = zep.graph_search(
            graph_id=graph_id,
            query="John",
            limit=5,
            scope="edges"
        )
        print(f"✓ 搜索完成，找到 {search_result.get('total_count', 0)} 条相关信息")

        # 清理
        zep.graph_delete(graph_id)
        print("✓ 兼容层测试通过")

        return True

    except Exception as e:
        print(f"❌ 兼容层测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def test_imports():
    """测试导入是否正常"""
    print("\n=== 测试导入 ===")

    try:
        # 测试 graphiti_wrapper 导入
        from app.services.graphiti_wrapper import Zep, GraphitiClient, GraphitiNode, GraphitiEdge
        print("✓ 成功导入 graphiti_wrapper")

        # 测试 zep_paging 导入
        from app.utils.zep_paging import fetch_all_nodes, fetch_all_edges
        print("✓ 成功导入 zep_paging")

        # 测试 graph_builder 导入
        from app.services.graph_builder import GraphBuilderService
        print("✓ 成功导入 graph_builder")

        print("✓ 所有导入测试通过")
        return True

    except Exception as e:
        print(f"❌ 导入测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """主测试函数"""
    print("======================================")
    print("  Graphiti + Neo4j 集成测试")
    print("======================================\n")

    # 1. 测试导入
    if not test_imports():
        print("导入测试失败，终止测试")
        return

    # 2. 测试基础功能
    if not test_graphiti_basic():
        print("基础功能测试失败，终止测试")
        return

    # 3. 测试兼容层
    if not test_graphiti_wrapper():
        print("兼容层测试失败，终止测试")
        return

    print("\n=== 所有测试通过 ===")
    print("迁移准备就绪！现在可以:")
    print("1. 确保 .env 文件中有 Neo4j 配置")
    print("2. 启动 backend 服务: python backend/run.py")
    print("3. 通过 API 测试图谱构建、搜索等功能")
    print()
    print("配置要求:")
    print(f"- NEO4J_URI: {Config.NEO4J_URI}")
    print(f"- NEO4J_USER: {Config.NEO4J_USER}")
    print(f"- NEO4J_PASSWORD: {Config.NEO4J_PASSWORD}")
    print()
    print("更多信息请查看迁移文档")


if __name__ == "__main__":
    main()
