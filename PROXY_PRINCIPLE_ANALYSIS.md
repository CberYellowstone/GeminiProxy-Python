# Gemini API 免费代理项目原理解析报告

## 目录

1. [核心原理与总体架构](#一核心原理与总体架构)
2. [后端分析 (aistudio-build-proxy)](#二后端分析-aistudio-build-proxy)
3. [前端分析 (proxy-gemini-chat-ui-autorun)](#三前端分析-proxy-gemini-chat-ui-autorun)
4. [数据流图与时序图](#四数据流图与时序图)
5. [技术要点总结](#五技术要点总结)

---

## 一、核心原理与总体架构

该项目的核心在于巧妙地利用了 **Google AI Studio Build 页面的 `fetch` 函数劫持（Hook）机制**。

### 1.1 核心原理

```mermaid
graph TB
    A[AI Studio Build 页面] --> B[iframe 环境]
    B --> C[JavaScript fetch 函数]
    C --> D[被 Google 劫持]
    D --> E[内部代理服务]
    E --> F[Gemini API]
    
    style D fill:#ff9999
    style E fill:#99ff99
```

当在 Google AI Studio 的 Build 页面中运行网页应用时：

1. **环境特殊性**: 页面运行在特殊的 `iframe` 环境中
2. **函数劫持**: 浏览器的 `fetch` 函数被 Google 的脚本自动劫持
3. **请求代理**: 对 `generativelanguage.googleapis.com` 的请求被内部代理处理
4. **免费调用**: **无需 API Key** 即可访问 Gemini API

### 1.2 总体架构

```mermaid
graph LR
    A[第三方AI工具<br/>LobeChat/OneAPI] --> B[本地Go代理后端<br/>127.0.0.1:5345]
    B --> C[WebSocket连接]
    C --> D[AI Studio前端页面<br/>React应用]
    D --> E[Google内部代理]
    E --> F[Gemini API]
    
    F --> E
    E --> D
    D --> C
    C --> B
    B --> A
    
    style B fill:#ffcc99
    style D fill:#99ccff
    style E fill:#99ff99
```

### 1.3 数据流路径

```
[第三方AI工具] 
    ↓ HTTP请求
[本地Go代理后端] 
    ↓ WebSocket消息
[AI Studio前端页面] 
    ↓ 被劫持的fetch
[Google内部代理] 
    ↓ 内部调用
[Gemini API]
```

---

## 二、后端分析 (aistudio-build-proxy)

后端是用 Go 语言编写的 HTTP 和 WebSocket 服务器，承担"翻译官"和"调度员"的角色。

### 2.1 服务架构

```mermaid
graph TB
    subgraph "Go 后端服务 (main.go)"
        A[HTTP服务器 :5345]
        B[WebSocket处理器 /v1/ws]
        C[API代理处理器 /]
        D[连接池管理器]
        E[健康检查器]
        F[负载均衡器]
    end
    
    A --> B
    A --> C
    C --> D
    C --> F
    D --> E
    
    style A fill:#ffcc99
    style D fill:#ccffcc
    style F fill:#ffccff
```

### 2.2 关键组件

#### 2.2.1 启动与路由

```go
// main.go:801
server := &http.Server{
    Addr:    ":5345",  // 监听本地5345端口
    Handler: mux,
}
```

**关键路由设置:**
- `/v1/ws` - WebSocket连接处理 ([main.go:790](aistudio-build-proxy/main.go#L790))
- `/` - API请求代理处理 ([main.go:798](aistudio-build-proxy/main.go#L798))

#### 2.2.2 连接池管理

```mermaid
graph LR
    A[ConnectionPool] --> B[Client1<br/>Chrome窗口1]
    A --> C[Client2<br/>Chrome窗口2]
    A --> D[Client3<br/>Chrome配置文件2]
    
    B --> E[UserConnection<br/>WebSocket连接]
    C --> F[UserConnection<br/>WebSocket连接]
    D --> G[UserConnection<br/>WebSocket连接]
    
    style A fill:#ffcc99
    style E fill:#ccffcc
    style F fill:#ccffcc
    style G fill:#ccffcc
```

**连接池特性:**
- 支持多个前端同时连接
- 基于 `clientID` 的连接管理
- 自动替换断开的连接

#### 2.2.3 负载均衡机制

```mermaid
sequenceDiagram
    participant C as 客户端请求
    participant LB as 负载均衡器
    participant C1 as 前端客户端1
    participant C2 as 前端客户端2
    participant C3 as 前端客户端3
    
    C->>LB: API请求1
    LB->>C1: 转发到客户端1
    C->>LB: API请求2
    LB->>C2: 转发到客户端2 (轮询)
    C->>LB: API请求3
    LB->>C3: 转发到客户端3 (轮询)
    C->>LB: API请求4
    LB->>C1: 转发到客户端1 (循环)
```

**轮询算法实现:**
```go
// main.go:101
var nextClientIndex uint32

// main.go:437 - 轮询选择客户端
startIdx := atomic.AddUint32(&nextClientIndex, 1) - 1
clientID := clientList[(startIdx+uint32(i))%uint32(len(clientList))]
```

### 2.3 请求处理流程

```mermaid
flowchart TD
    A[收到HTTP请求] --> B[中间件处理链]
    B --> C[CORS + 认证 + 日志]
    C --> D[客户端选择中间件]
    D --> E[获取健康客户端列表]
    E --> F{有可用客户端?}
    F -->|否| G[返回503错误]
    F -->|是| H[轮询选择客户端]
    H --> I[打包HTTP请求为WebSocket消息]
    I --> J[发送到前端客户端]
    J --> K[等待响应]
    K --> L[处理WebSocket响应]
    L --> M[返回给原始客户端]
    
    style F fill:#ffcc99
    style I fill:#ccffcc
    style L fill:#ffccff
```

### 2.4 健康检查机制

```mermaid
graph TB
    A[健康检查定时器<br/>每60秒] --> B[遍历所有客户端]
    B --> C[发送健康检查请求]
    C --> D[等待响应]
    D --> E{响应正常?}
    E -->|是| F[标记为健康]
    E -->|否| G[标记为不健康]
    E -->|超时| G
    
    F --> H[IsHealthy = true]
    G --> I[IsHealthy = false]
    
    style E fill:#ffcc99
    style F fill:#99ff99
    style G fill:#ff9999
```

---

## 三、前端分析 (proxy-gemini-chat-ui-autorun)

前端是运行在 AI Studio 环境中的 React 应用，作为"执行代理"。

### 3.1 应用架构

```mermaid
graph TB
    subgraph "React 前端应用"
        A[App.tsx<br/>主应用组件]
        B[webSocketService.ts<br/>WebSocket服务]
        C[geminiService.ts<br/>Gemini API服务]
        D[UI组件层]
    end
    
    A --> B
    A --> C
    A --> D
    B --> E[本地Go后端<br/>WebSocket连接]
    C --> F[直接API调用<br/>通过劫持的fetch]
    
    style B fill:#ffcc99
    style C fill:#ccffcc
    style F fill:#ff9999
```

### 3.2 WebSocket 连接流程

```mermaid
sequenceDiagram
    participant F as 前端React应用
    participant W as webSocketService
    participant G as Go后端
    
    F->>W: 应用启动
    W->>W: 读取localStorage配置
    W->>G: 建立WebSocket连接
    G->>W: 连接确认
    W->>F: 更新连接状态
    
    Note over F,G: 连接建立完成
    
    G->>W: HTTP请求消息
    W->>W: 解析请求信息
    W->>W: 执行fetch调用
    Note over W: fetch被AI Studio劫持
    W->>G: 返回响应数据
```

### 3.3 关键执行逻辑

#### 3.3.1 fetch 劫持的核心机制

```mermaid
graph LR
    A[WebSocket收到请求] --> B[解析请求参数]
    B --> C[构造fetch调用]
    C --> D[浏览器原生fetch]
    D --> E[AI Studio劫持]
    E --> F[Google内部代理]
    F --> G[Gemini API]
    
    style E fill:#ff9999
    style F fill:#99ff99
```

#### 3.3.2 响应处理分类

```mermaid
flowchart TD
    A[fetch响应] --> B{响应类型}
    B -->|一次性响应| C[读取完整内容]
    B -->|流式响应| D[获取ReadableStream]
    
    C --> E[发送http_response消息]
    
    D --> F[逐块读取数据]
    F --> G[发送stream_start]
    G --> H[发送stream_chunk...]
    H --> I[发送stream_end]
    
    style B fill:#ffcc99
    style D fill:#ccffcc
```

### 3.4 消息类型定义

```typescript
// types.ts 中定义的关键消息类型
interface WSMessage {
  id: string;
  type: 'http_request' | 'http_response' | 'stream_start' | 'stream_chunk' | 'stream_end' | 'error';
  payload: any;
}
```

---

## 四、数据流图与时序图

### 4.1 完整请求流程时序图

```mermaid
sequenceDiagram
    participant AI as 第三方AI工具
    participant GO as Go后端代理
    participant WS as WebSocket连接
    participant FE as 前端React应用
    participant AS as AI Studio环境
    participant GM as Gemini API
    
    AI->>GO: HTTP POST /v1beta/models/gemini:generateContent
    GO->>GO: 解析请求，选择健康客户端
    GO->>WS: 发送WSMessage{type:"http_request"}
    WS->>FE: WebSocket消息传递
    FE->>FE: 解析请求参数
    FE->>AS: 调用fetch(gemini-api-url)
    AS->>AS: 劫持fetch调用
    AS->>GM: 通过内部代理调用
    GM->>AS: 返回API响应
    AS->>FE: 返回劫持后的响应
    FE->>FE: 处理响应数据
    FE->>WS: 发送响应消息
    WS->>GO: WebSocket响应传递
    GO->>AI: HTTP响应返回
```

### 4.2 负载均衡场景

```mermaid
graph TB
    subgraph "用户打开多个AI Studio页面"
        A[Chrome窗口1<br/>前端客户端1]
        B[Chrome窗口2<br/>前端客户端2]
        C[Chrome配置文件2<br/>前端客户端3]
    end
    
    subgraph "Go后端"
        D[连接池管理器]
        E[负载均衡器]
    end
    
    subgraph "外部请求"
        F[请求1]
        G[请求2]
        H[请求3]
        I[请求4]
    end
    
    A --> D
    B --> D
    C --> D
    
    F --> E
    G --> E
    H --> E
    I --> E
    
    E -->|轮询| A
    E -->|轮询| B
    E -->|轮询| C
    E -->|轮询| A
    
    style D fill:#ffcc99
    style E fill:#ccffcc
```

### 4.3 错误处理与重试机制

```mermaid
flowchart TD
    A[请求进入] --> B[选择客户端1]
    B --> C{发送成功?}
    C -->|成功| D[等待响应]
    C -->|失败| E[标记客户端1不健康]
    E --> F[选择客户端2]
    F --> G{发送成功?}
    G -->|成功| D
    G -->|失败| H[继续尝试下一个客户端]
    H --> I{还有客户端?}
    I -->|是| J[选择下一个客户端]
    I -->|否| K[返回502错误]
    J --> G
    D --> L[处理响应]
    
    style C fill:#ffcc99
    style G fill:#ffcc99
    style I fill:#ffcc99
```

---

## 五、技术要点总结

### 5.1 核心技术栈

| 组件 | 技术栈 | 关键特性 |
|------|--------|----------|
| 后端代理 | Go + Gorilla WebSocket + Prometheus | 高并发、健康检查、负载均衡 |
| 前端应用 | React + TypeScript + Vite | 现代化构建、类型安全 |
| 通信协议 | WebSocket + HTTP | 双向实时通信 |
| 部署环境 | AI Studio Build 页面 | 特殊的iframe环境 |

### 5.2 关键设计模式

```mermaid
graph LR
    A[代理模式<br/>Proxy Pattern] --> B[Go后端作为HTTP代理]
    C[观察者模式<br/>Observer Pattern] --> D[WebSocket事件监听]
    E[负载均衡模式<br/>Load Balancer] --> F[轮询算法分发请求]
    G[健康检查模式<br/>Health Check] --> H[定时检测客户端状态]
    
    style A fill:#ffcc99
    style C fill:#ccffcc
    style E fill:#ffccff
    style G fill:#fff2cc
```

### 5.3 核心优势

1. **免费使用**: 绕过API Key限制，实现免费调用
2. **负载均衡**: 支持多客户端连接，自动分发请求
3. **高可用性**: 健康检查机制确保服务稳定
4. **易于部署**: Go二进制文件 + Web页面，部署简单
5. **透明代理**: 对第三方应用完全透明

### 5.4 潜在限制

1. **依赖AI Studio**: 必须在Google AI Studio环境中运行前端
2. **网络要求**: 需要稳定的WebSocket连接
3. **浏览器限制**: 前端必须保持浏览器窗口打开
4. **并发限制**: 受AI Studio页面并发限制影响

### 5.5 安全考虑

```mermaid
graph TB
    A[安全机制] --> B[JWT Token认证]
    A --> C[CORS跨域控制]
    A --> D[请求来源验证]
    A --> E[连接状态监控]
    
    B --> F[防止未授权连接]
    C --> G[限制跨域访问]
    D --> H[验证WebSocket来源]
    E --> I[实时监控连接健康]
    
    style A fill:#ff9999
```

---

## 结论

这个项目展现了一个精巧的"中间人"架构设计：

- **分离关注点**: 将复杂的HTTP服务逻辑放在功能完备的Go后端，将执行逻辑简化为纯粹的指令执行者
- **利用环境特性**: 巧妙利用AI Studio的fetch劫持机制，实现免API Key调用
- **高可用设计**: 通过连接池、负载均衡和健康检查，确保服务的稳定性和扩展性

这种设计不仅技术上具有创新性，也为类似的API代理场景提供了有价值的参考架构。