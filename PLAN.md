# 方案 B (最终版): 基于后端存储的异步复制与全局容错方案

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

### 3.2. 后续文件使用 (无故障)

1.  **接收请求**: 收到一个包含 `file.name` 的请求。
2.  **识别文件**: 通过反向映射，由 `file.name` 找到 `sha256`。
3.  **选择客户端**: **轮询**选择一个客户端，例如 `Client-B`。
4.  **检查状态**: 查询元数据，检查 `replication_map` 中 `Client-B` 的状态。
    *   **Case 1: `synced`**: `Client-B` 已同步。后端从 map 中获取其对应的 `file.name`，**改写**用户请求中的 `file.name`，然后将请求发给 `Client-B`。更新 `last_accessed_at`。
    *   **Case 2: `pending_replication`**: `Client-B` 未同步。
        *   **即时回退**: 查找 `replication_map` 中任意一个 `synced` 的客户端 (e.g., `Client-A`)，将请求**立即**转发给 `Client-A` 处理，保证用户无延迟。
        *   **异步复制**: **同时**，在后台启动一个任务，指挥 `Client-B` 从后端下载并上传文件，成功后将其状态更新为 `synced`。

### 3.3. 故障恢复：Gemini 文件过期

1.  **检测**: `Client-X` 尝试使用一个 `file.name`，但 Gemini 返回“文件不存在”错误。
2.  **全局重置**: 后端捕获此错误，找到对应的 `sha256`，然后**清空**其 `replication_map` 和相关的反向映射条目。
3.  **同步重建**: 为了服务当前用户，系统**同步地**轮询选择一个新客户端 `Client-Y`，指挥其重新上传文件，获取**全新的 `file.name`** 和过期时间。
4.  **状态更新**: 更新 `replication_map`、`gemini_file_expiration` 和反向映射。
5.  **服务用户**: 改写用户请求，使用新的 `file.name`，发给 `Client-Y` 处理。第一个“踩雷”的用户会经历一次上传延迟。
6.  **恢复正常**: 系统状态被纠正，后续请求将触发正常的异步复制流程。

## 4. 流程图

```mermaid
graph TD
    subgraph "方案 B 完整流程"
        direction LR
        A[用户上传文件] --> B{后端: 计算sha256, 存本地};
        B --> C{轮询选Client-A, 同步上传};
        C --> D{记录元数据/Replication Map};

        E[用户使用文件] --> F{轮询选Client-B};
        F --> G{检查Replication Map};
        G -->|B已同步| H[改写请求, 直发B];
        G -->|B未同步| I[主线程: 立即转给A处理];
        G -->|B未同步| J[后台: 异步复制到B];
        
        K[Client-X报告文件过期] --> L{后端: 全局重置};
        L --> M{清空Replication Map};
        M --> N[同步为当前用户重新上传];
        N --> O[更新元数据, 服务当前用户];
    end