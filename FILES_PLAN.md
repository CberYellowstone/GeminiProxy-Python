# 方案 B (最终版): 基于后端存储的统一调度与自愈方案

## 1. 核心哲学

本方案旨在**彻底解决**文件上传的有状态性与多 WebSocket 客户端负载均衡之间的矛盾。其核心哲学是**复制与同步**：通过在后端持久化文件内容，确保任何一个客户端都有能力处理任何文件的请求，从而实现完美的轮询负载均衡和强大的故障恢复能力。

## 2. 关键组件与数据结构

### 2.1. 后端文件存储 (File Cache)

*   **功能**: 作为文件内容的唯一可信来源 (Single Source of Truth)。
*   **实现**:
    *   在服务器本地创建一个可配置的缓存目录 (e.g., `file_cache`)。
    *   文件内容以其 `sha256` 值为文件名进行存储，并采用二级目录分散存储 (e.g., `file_cache/d2/9a/...`)。
    *   **必须**实现一个后台清理任务，采用 **TTL + LRU** 策略管理缓存，防止无限增长。

### 2.2. 核心元数据管理器 (在 `FileManager` 中实现)

*   **功能**: 方案的大脑，维护所有文件的状态信息。
*   **实现**: 一个以 `sha256` 为 key 的内存字典，存储以下结构：

```python
# 伪代码
"sha256_hash_string": {
  "local_path": "/path/to/file_cache/...",  # 本地存储路径
  "metadata": { ... },                      # 文件原始元数据
  "created_at": "...",                      # 首次缓存时间
  "last_accessed_at": "...",                # 最近访问时间 (用于LRU)
  "gemini_file_expiration": "...",          # Gemini端理论过期时间 (用于TTL)
  "replication_map": {                      # 复制状态地图
    "client_id_A": { "name": "files/abc-123", "status": "synced" },
    "client_id_B": { "status": "pending_replication" },
    "client_id_C": { "name": "files/jkl-789", "status": "expired" }
  }
}
```

*   **反向映射**: 还需要一个 `file.name -> sha256` 的反向映射字典，用于在处理后续请求时快速定位文件内容。

## 3. 核心工作流程

### 3.1. 首次文件上传

1.  **接收与存储**: 客户端上传文件。代理后端接收到**完整的**文件流。
2.  **计算与保存**: 计算文件流的 `sha256`，并将其保存到本地 `file_cache` 目录。
3.  **创建元数据**: 在元数据管理器中创建新的条目，记录 `local_path`, `last_accessed_at` 等信息。
4.  **同步上传**: 通过**轮询**选择一个健康的 `Client-A`。**同步地、阻塞地**指挥 `Client-A` 从后端下载并上传文件到 Gemini。
5.  **记录状态**: `Client-A` 成功后，返回 `file.name` 和 `expiration_time`。后端更新元数据，记录 `gemini_file_expiration`，并在 `replication_map` 中标记 `Client-A` 为 `synced`。同时更新反向映射。
6.  **返回响应**: 将 `file.name` 返回给最终用户。

### 3.2. 统一会话调度：乐观轮询与自愈回退

为了简化逻辑并增强鲁棒性，所有涉及文件使用的请求（无论是单个文件、多个文件还是无文件）均遵循此统一的调度策略。**单文件请求被视为多文件请求的一个特例（N=1）**。

1.  **解析文件**: 接收到请求后，首先遍历 `payload`，解析出此次会话所需的**所有**文件的 `sha256` 列表 (`required_sha256s`)。此列表可能为空。

2.  **乐观选择 (Optimistic Pick)**: 使用标准的轮询算法 (`get_next_client()`) 选择一个**初始客户端 (Initial-Client)**。

3.  **检查命中**: 检查 `Initial-Client` 是否拥有 `required_sha256s` 中的所有文件。
    *   **完美命中 (Perfect Hit)**: 如果 `Initial-Client` 已拥有全部文件：
        1.  **改写 Payload**: 遍历 `payload`，将其中每个文件的引用（`fileName` 或 `fileUri`）都更新为 `Initial-Client` 在 `replication_map` 中对应的 `name`。
        2.  **发送请求**: 将改写后的 `payload` 直接发送给 `Initial-Client`。
        3.  **更新访问时间**: 更新所有相关文件元数据的 `last_accessed_at` 时间戳。
    *   **未命中 (Miss)**: 如果 `Initial-Client` 缺少至少一个文件，则触发**回退与自愈**机制：
        *   **A. 主线程 - 立即服务用户 (Serve User Now)**:
            1.  **寻找最优**: 立即对**所有**活跃的客户端进行一次全局扫描。对每个客户端，计算它缺失 `required_sha256s` 中文件的数量。缺失文件数量**最少**的客户端即为**最佳客户端 (Best-Client)**。如果存在多个最佳客户端，则从中随机选择一个。
            2.  **同步补全**: 获取 `Best-Client` 缺失的文件列表 (`files_to_replicate`)。如果此列表不为空，则**同步地、并发地**为 `Best-Client` 复制这些缺失的文件（例如使用 `asyncio.gather`）。此操作必须阻塞并等待全部成功，以保证当前用户请求可用。
            3.  **转发请求**: 改写 `payload` 以匹配 `Best-Client` 的文件版本（包括刚刚同步补全的），并将请求转发给它处理。
        *   **B. 后台线程 - 系统自我修复 (Self-Heal in Background)**:
            1.  **触发异步复制**: **与此同时**，为最初被选中的 `Initial-Client` 启动一个**后台异步任务**。
            2.  **执行复制**: 该任务会指挥 `Initial-Client` 去复制它最初缺失的**所有**文件。此过程不影响当前用户请求的响应。

### 3.3. 故障恢复：Gemini 文件过期

1.  **检测**: `Client-X` 尝试使用一个 `file.name`，但 Gemini 返回“文件不存在”错误。
2.  **全局重置**: 后端捕获此错误，找到对应的 `sha256`，然后**清空**其 `replication_map` 和相关的反向映射条目。
3.  **同步重建**: 为了服务当前用户，系统**同步地**轮询选择一个新客户端 `Client-Y`，指挥其重新上传文件，获取**全新的 `file.name`** 和过期时间。
4.  **状态更新**: 更新 `replication_map`、`gemini_file_expiration` 和反向映射。
5.  **服务用户**: 改写用户请求，使用新的 `file.name`，发给 `Client-Y` 处理。第一个“踩雷”的用户会经历一次上传延迟。
6.  **恢复正常**: 系统状态被纠正，后续请求将遵循 3.2 中的统一调度流程。

## 4. 统一流程图

```mermaid
graph TD
    subgraph "方案 B: 统一调度与自愈模型"
        direction TB

        A[用户请求] --> B{请求类型?};

        B -- 文件上传 --> C[首次文件上传流程];
        C --> D{1. 计算sha256, 存本地};
        D --> E{2. 轮询选Client, 同步上传};
        E --> F[3. 更新元数据];
        F --> G[4. 返回响应];

        B -- 文件使用/会话 --> H[统一会话调度流程];
        H --> I{1. 解析全部文件sha256};
        I --> J{2. 轮询选择 Initial-Client};
        J --> K{3. Initial-Client 是否拥有全部文件?};
        
        K -- 是/完美命中 --> L[4a. 改写Payload, 直发Initial-Client];
        L --> Z[结束];

        K -- 否/未命中 --> M[4b. 主线程: 立即服务];
        M --> N[5. 全局扫描找到Best-Client];
        N --> O{6. 同步为Best-Client补全文件};
        O --> P[7. 改写Payload, 转发给Best-Client];
        P --> Z;

        K -- 否/未命中 --> Q[后台: 自我修复];
        Q --> R[为Initial-Client异步复制缺失文件];

        P -- 发生文件不存在错误 --> S[故障恢复流程];
        S --> T{1. 全局重置Replication Map};
        T --> U{2. 同步为当前用户重新上传};
        U --> P;
    end