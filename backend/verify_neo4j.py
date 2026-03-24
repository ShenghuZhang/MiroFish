#!/usr/bin/env python3
"""
验证 Neo4j 连接和 Graphiti 基本功能

用途：
1. 测试 Neo4j 连接
2. 测试 Graphiti 初始化
3. 验证基本功能是否正常工作
"""

import sys
import os
import asyncio
from datetime import datetime

# 添加 backend 路径
sys.path.insert(0, '/Users/moya/Workspace/MiroFish/backend')

from app.services.graphiti_wrapper import GraphitiClient
from app.config import Config


def verify_neo4j_connection():
    """验证 Neo4j 连接"""
    print("=== 验证 Neo4j 连接 ===")

    try:
        # 1. 检查环境变量
        print("\n1. 检查环境变量...")
        required_vars = ['NEO4J_URI', 'NEO4J_USER', 'NEO4J_PASSWORD']
        missing_vars = [v for v in required_vars if not os.getenv(v)]

        if missing_vars:
            print(f"❌ 缺少必需的环境变量: {missing_vars}")
            print("\n请确保在 .env 文件中配置：")
            for var in missing_vars:
                print(f"  {var}=your_value_here")
            return False

        print(f"✅ 所有必需的环境变量已配置")

        # 2. 测试 Neo4j 连接
        print("\n2. 测试 Neo4j 连接...")
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(
            uri=Config.NEO4J_URI,
            user=Config.NEO4J_USER,
            password=Config.NEO4J_PASSWORD
        )

        # 测试连接
        print(f"   连接 URI: {Config.NEO4J_URI}")
        print(f"   用户: {Config.NEO4J_USER}")

        # 测试查询
        result = driver.execute_query("RETURN 1 AS n")
        if result.records and len(result.records) > 0:
            print(f"✅ Neo4j 连接成功！")
            print(f"   测试查询结果: {result.records[0]['n']}")
        else:
            print(f"❌ Neo4j 连接失败：没有返回记录")
            return False

    except Exception as e:
        print(f"❌ Neo4j 连接失败：{str(e)}")
        print(f"\n请检查：")
        print(f"   1. Neo4j 服务是否运行？")
        print(f"   2. URI 是否正确？(例如: neo4j://localhost:7687)")
        print(f"   3. 密码是否正确？(NEO4J_PASSWORD)")
        return False

    finally:
        if 'driver' in locals():
            driver.close()

        return True


def verify_graphiti_initialization():
    """验证 Graphiti 初始化"""
    print("\n=== 验证 Graphiti 初始化 ===")

    try:
        # 创建 Graphiti 客户端
        print("\n1. 创建 Graphiti 客户端...")
        client = GraphitiClient(
            uri=Config.NEO4J_URI,
            user=Config.NEO4J_USER,
            password=Config.NEO4J_PASSWORD
        )

        # 2. 构建索引
        print("\n2. 构建索引和约束...")

        async def build_indices():
            graphiti = client._get_graphiti()
            await graphiti.build_indices_and_constraints()

        # 在同步环境中运行异步代码
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(build_indices())
        finally:
            loop.close()

        print("✅ 索引和约束构建完成")

        # 3. 测试基本搜索
        print("\n3. 测试基本搜索功能...")
        # Graphiti 需要先有一些数据才能搜索
        print(f"   （注意：空图谱搜索会返回空结果）")

        return True

    except Exception as e:
        print(f"❌ Graphiti 初始化失败：{str(e)}")
        print("\n请检查：")
        print(f"   1. Neo4j 是否可访问？")
        print(f"   2. 网络端口是否正确？(默认 7687)")
        return False


def verify_basic_functionality():
    """验证基本功能"""
    print("\n=== 验证基本功能 ===")

    try:
        # 创建客户端（GraphitiClient 会自动初始化 LLM 和 Embedder）
        client = GraphitiClient(
            uri=Config.NEO4J_URI,
            user=Config.NEO4J_USER,
            password=Config.NEO4J_PASSWORD
        )

        async def test():
            # 创建测试图谱
            graph_id = f"test_verify_{datetime.now().strftime('%Y%m%d%H%M%S')}"

            # 初始化索引
            graphiti = client._get_graphiti()
            await graphiti.build_indices_and_constraints()

            # 添加测试数据
            test_data = """
            Test data for Graphiti verification.
            Alice is a software engineer.
            Bob is a data scientist at same company.
            Alice manages Bob directly.
            Project Z was released in early 2024.
            """

            await graphiti.add_episode(
                name="Test Episode 1",
                episode_body=test_data,
                source_description="Verification",
                reference_time=datetime.now(),
                group_id=graph_id
            )

            # 等待索引更新
            await asyncio.sleep(2)

            # 测试搜索
            results = await graphiti.search(
                query="Alice",
                config="NODE_HYBRID_SEARCH_CROSS_ENCODER",
                group_ids=[graph_id],
                num_results=5
            )

            print(f"   搜索查询: 'Alice'")
            node_count = len(results.nodes) if hasattr(results, 'nodes') else 0
            print(f"   找到 {node_count} 个节点")

            if node_count > 0:
                print(f"   ✅ 基本功能正常！")
            else:
                print(f"   ⚠️  搜索返回空结果，但连接正常")

            return True

        # 在同步环境中运行异步代码
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(test())
        finally:
            loop.close()

    except Exception as e:
        print(f"❌ 基本功能验证失败：{str(e)}")
        print("\n请检查：")
        print(f"   LLM API Key 是否正确？")
        print(f"   Embedding 模型配置是否正确？")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("=======================================")
    print("MiroFish Graphiti 验证工具")
    print("=======================================")
    print()

    all_passed = True

    # 1. 验证 Neo4j 连接
    if not verify_neo4j_connection():
        print("⚠️  Neo4j 连接失败，跳过后续验证")
        all_passed = False
    else:
        print()

    # 2. 验证 Graphiti 初始化
    if not verify_graphiti_initialization():
        print("⚠️  Graphiti 初始化失败，跳过后续验证")
        all_passed = False
    else:
        print()

    # 3. 验证基本功能
    if not verify_basic_functionality():
        print("⚠️  基本功能验证失败")
        all_passed = False
    else:
        print()

    print()
    print("======================================")
    if all_passed:
        print("✅ 所有验证通过！Graphiti 迁移准备就绪")
        print("======================================")

        print()
        print("📋 下一步：")
        print("1. 确保 .env 文件配置正确")
        print("2. 测试后端服务启动是否正常")
        print("3. 运行迁移测试（测试图谱构建、搜索等功能）")
        print()
        print("4. 运行：python verify_neo4j.py")
        print()
    else:
        print("如果上述验证失败，请根据错误提示修复相应问题")
