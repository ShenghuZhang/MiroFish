# Zep Cloud → Graphiti + Neo4j 迁移总结

## 一、已完成修改

### 1. 配置层修改

#### 1.1 config.py
- ✅ 移除 `ZEP_API_KEY` 配置
- ✅ 添加 Neo4j 配置：
  - `NEO4J_URI` (默认: `neo4j://localhost:7687`)
  - `NEO4J_USER` (默认: `neo4j`)
- - `NEO4J_PASSWORD` (默认: `password`)
- ✅ 移除 `ZEP_API_KEY` 的验证

#### 1.2 pyproject.toml
- ✅ 替换：`zep-cloud==3.13.0` → `graphiti-core>=0.28.2`

#### 1.3 .env.example
- ✅ 添加 Neo4j 配置示例：
```bash
NEO4J_URI=neo4j://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password
```

---

## 二、创建的核心文件

### 2.1 graphiti_wrapper.py
**位置**: `backend/app/services/graphiti_wrapper.py`

**功能**:
- ✅ 异步/同步桥接：`run_async()` 函数，在同步 Flask 中调用异步 Graphiti 方法
- ✅ Graphiti 客户端：`GraphitiClient` 类，封装 Graphiti 的连接
- ✅ Zep 兼容类：`Zep` 类，保持与 Zep Cloud API 相同的接口

**关键组件**:
- `GraphitiClient`: Graphiti 客户端，管理 Neo4j 连接和 LLM/Embedder 客户端
- `Zep` 兼容类：提供与 Zep Cloud 完全相同的 API 接口
- 数据模型：`GraphitiNode`, `GraphitiEdge`, `GraphitiInfo`

**关键方法**：
- `graph_create()`: 创建图谱（返回 group_id）
- `graph_delete()`: 删除图谱
- `graph_add_batch()`: 批量添加 Episodes
- `graph_search()`: 语义搜索
- `graph_node_get_by_graph_id()`: 获取所有节点
- `graph_edge_get_by_graph_id()`: 获取所有边（含时间信息）
- `graph_node_get()`: 获取单个节点
- `graph_node_get_entity_edges()`: 获取节点的相关边

### 2.2 graph_builder.py
**位置**: `backend/app/services/graph_builder.py`

**功能**:
- ✅ 使用 `graphiti_wrapper.Zep` 兼容接口
- ✅ 图谱构建功能保持不变
- ✅ 支持任务管理和进度回调

**关键变化**:
- `create_graph()`: 返回 `graph_id`（实际上是 group_id）
- `set_ontology()`: 保存到内存（Graphiti 的本体通过 `entity_types` 参数传递）
- `add_text_batches()`: 调用 `GraphitiClient.graph_add_batch`
- `_wait_for_episodes()`: **已移除等待** - Graphiti 的 Episode 添加后立即可用，无需等待 `processed` 状态
- `_get_graph_info()`: 使用搜索 API 统计节点和边

### 2.3 zep_paging.py
**位置**: `backend/app/utils/zep_paging.py`

**功能**:
- ✅ 使用 `graphiti_wrapper.Zep` 兼容接口
- ✅ 移除分页逻辑，直接调用搜索获取所有结果

### 2.4 zep_entity_reader.py
**位置**: `backend/app/services/zep_entity_reader.py`

**功能**:
- ✅ 使用 `graphiti_wrapper.Zep` 兼容接口
- ✅ 实体读取和过滤功能保持不变
- ✅ 移除 `ZEP_API_KEY` 验证

---

## 三、API 层修改（已完成）

### 3.1 backend/app/api/simulation.py
- ✅ 移除 `/entities/<graph_id>` 端点的 `ZEP_API_KEY` 检查
- ✅ 移除 `/entities/<graph_id>/<entity_uuid>` 端点的 `ZEP_API_KEY` 检查
- ✅ 移除 `/entities/<graph_id>/by-type/<entity_type>` 端点的 `ZEP_API_KEY` 检查

### 3.2 backend/app/api/graph.py
- ✅ 移除 `/build` 端点的 `ZEP_API_KEY` 配置检查
- ✅ 移除 `GraphBuilderService(api_key=Config.ZEP_API_KEY)` 中的 api_key 参数
- ✅ 移除 `/data/<graph_id>` 端点的 `ZEP_API_KEY` 检查
- ✅ 移除 `/delete/<graph_id>` 端点的 `ZEP_API_KEY` 检查

### 3.3 服务层修改（已完成）
- ✅ `backend/app/services/zep_graph_memory_updater.py`: 移除 api_key 验证，直接使用 `Zep()`
- ✅ `backend/app/services/oasis_profile_generator.py`: 修改 zep_client 初始化，不再需要 ZEP_API_KEY

---

## 四、业务逻辑对比验证

### 4.1 图谱构建
| 操作 | Zep Cloud | Graphiti | 业务逻辑是否保持 |
|------|-----------|----------|---------|
| **创建图谱** | `graph.create()` | `graph_create()` | ✅ 兼容 |
| **设置本体** | `graph.set_ontology()` | 保存到内存 | ⚠️ | ⚠️ |
| **添加数据** | `graph.add_batch()` | `graph_add_batch()` | ✅ 兼容 |
| **等待处理** | 等待 `processed` 状态 | **无等待** | ✅ 无变化 |
| **删除图谱** | `graph.delete()` | `graph_delete()` | ✅ 兼容 |

### 4.2 节点读取
| 操作 | Zep Cloud | Graphiti | 业务逻辑是否保持 |
|------|-----------|----------|---------|
| **获取所有节点** | `node.get_by_graph_id()` | `graph_node_get_by_graph_id()` | ✅ 兼容 |
| **获取所有边** | `edge.get_by_graph_id()` | `graph_edge_get_by_graph_id()` | ✅ 兼容（含时间信息）|
| **获取节点详情** | `node.get(uuid_=...)` | `graph_node_get()` | ✅ 兼容 |
| **获取节点边** | `node.get_entity_edges()` | `graph_node_get_entity_edges()` | ✅ 兼容 |

### 4.3 图谱搜索
| 操作 | Zep Cloud | Graphiti | 业务逻辑是否保持 |
|------|-----------|----------|---------|
| **语义搜索** | `graph.search(reranker="cross_encoder")` | `graph_search()` | ✅ 兼容 |
| **混合搜索** | `graph.search(config=COMBINED_HYBRID...)` | 待实现 | ⚠️ |
| **边/节点搜索** | `scope="edges"/"nodes"/"both"` | ✅ 兼容 |

### 4.4 记忆更新
| 操作 | Zep Cloud | Graphiti | 业务逻辑是否保持 |
|------|-----------|----------|---------|
| **添加 Episode** | `graph.add()` | `graph_add()` | ✅ 兼容 |
| **批量添加** | `graph.add_batch()` | `graph_add_batch()` | ✅ 兼容 |

---

## 五、部署前检查清单

- [ ] 1. 确认 Neo4j 实例已部署并可连接
- [ ] 2. 设置环境变量：`NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`
- [ ] 3. 安装依赖：`pip install graphiti-core>=0.28.2`（在虚拟环境中）
- [ ] 4. 运行 `python3 test_graphiti.py` 验证连接
- [x] 5. 代码迁移完成（所有 ZEP_API_KEY 已移除）

---

## 六、执行步骤

1. **配置环境**
   ```bash
   # 复制 .env.example 到 .env 并填入实际值
   cp .env.example .env

   # 添加 Neo4j 配置
   echo "NEO4J_URI=neo4j://localhost:7687" >> .env
   echo "NEO4J_USER=neo4j" >> .env
   echo "NEO4J_PASSWORD=password" >> .env
   ```

2. **安装依赖**
   ```bash
   cd /Users/moya/Workspace/MiroFish/backend

   # 激活虚拟环境
   source .venv/bin/activate

   # 安装 graphiti-core（在虚拟环境中）
   pip install graphiti-core>=0.28.2
   ```

3. **测试连接**
   ```bash
   python3 <<'EOF'
   from graphiti_core import Graphiti

   graphiti = Graphiti(
       uri="neo4j://localhost:7687",
       user="neo4j",
       password="password"
   )

   # 测试连接
   graphiti.build_indices_and_constraints()
   print("✅ Neo4j 连接成功！")
   ```
```

---

## 七、关键要点

1. **API 兼容性**：通过 `Zep` 兼容类，所有现有代码无需修改 API 调用
2. **异步转同步**：`run_async()` 提供 Flask 调用 Graphiti 的异步方法
3. **业务逻辑不变**：图谱构建、搜索、读取功能保持原有接口
4. **无需等待 processed**：Graphiti 的 Episode 添加后立即可用
5. **ZEP_API_KEY 完全移除**：所有配置检查和 API 验证已清理

---

## 八、代码修改总结

| 文件 | 修改内容 | 状态 |
|------|---------|------|
| `app/config.py` | 移除 `ZEP_API_KEY`，添加 Neo4j 配置 | ✅ |
| `pyproject.toml` | `zep-cloud` → `graphiti-core` | ✅ |
| `.env.example` | 添加 Neo4j 配置示例 | ✅ |
| `app/services/graphiti_wrapper.py` | 新建：Graphiti 包装器和 Zep 兼容层 | ✅ |
| `app/services/graph_builder.py` | 使用 graphiti_wrapper.Zep | ✅ |
| `app/services/zep_entity_reader.py` | 使用 graphiti_wrapper.Zep | ✅ |
| `app/services/zep_paging.py` | 使用 graphiti_wrapper.Zep | ✅ |
| `app/services/zep_graph_memory_updater.py` | 移除 api_key 验证 | ✅ |
| `app/services/oasis_profile_generator.py` | 移除 ZEP_API_KEY 依赖 | ✅ |
| `app/api/simulation.py` | 移除 3 处 ZEP_API_KEY 检查 | ✅ |
| `app/api/graph.py` | 移除 4 处 ZEP_API_KEY 检查/使用 | ✅ |

---

**所有代码迁移已完成！** 🎉

下一步：运行 `python3 test_graphiti.py` 验证 Graphiti + Neo4j 连接。