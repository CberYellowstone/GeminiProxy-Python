"""
日志方向标识快速参考

使用方法：
from app.core.log_utils import format_request_log, format_response_log

# 接收外部API调用
logging.info(
    format_request_log('caller_to_backend', request_id, "详细信息")
)

# 返回给外部API调用者
logging.info(
    format_response_log('backend_to_caller', request_id, "详细信息")
)

# 发送请求到浏览器前端
logging.info(
    format_request_log('backend_to_browser', request_id, "详细信息")
)

# 接收浏览器前端响应
logging.info(
    format_response_log('browser_to_backend', request_id, "详细信息")
)

方向说明：
┌─────────────────────────────────────────────────────────────┐
│                                                               │
│  外部调用者 ──①──> 后端 ──③──> 浏览器前端                      │
│  (Caller)    ◀──②── (Backend) ◀──④── (Browser)                │
│                                                               │
│  ① 调用者→后端: caller_to_backend     (黄色 ◀)                │
│  ② 后端→调用者: backend_to_caller     (黄色 ▶)                │
│  ③ 后端→浏览器: backend_to_browser    (青色 ▶)                │
│  ④ 浏览器→后端: browser_to_backend    (青色 ◀)                │
│                                                               │
└─────────────────────────────────────────────────────────────┘

典型请求流程：
1. 用户调用API → 后端 (caller_to_backend)
2. 后端转发请求 → 浏览器 (backend_to_browser)
3. 浏览器执行并返回 → 后端 (browser_to_backend)
4. 后端处理并返回 → 用户 (backend_to_caller)
"""
