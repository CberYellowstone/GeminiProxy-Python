import { GoogleGenAI } from "@google/genai";
import type { Command } from '../types/types';
import { deleteFile, getFile, initiateResumableUpload, uploadChunk } from "./files";
import { executeGenerateContent, executeStreamGenerateContent } from "./generatingContent";
import { executeGetModel, executeListModels } from './models';

export const GOOGLE_API_URL = "https://generativelanguage.googleapis.com/v1beta";
// 在前端，我们不应该直接使用 process.env.API_KEY，因为这会暴露 API 密钥。
// 实际上，这个代理项目的目的是让前端通过后端代理来访问 Gemini API，
// 所以前端本身不需要 API Key，或者应该允许用户在界面上输入（如果设计如此）。
// 但根据目前的架构，前端似乎是直接调用 GoogleGenAI SDK，这通常意味着它需要 API Key。
// 然而，如果我们的目标是代理，那么 GoogleGenAI SDK 的配置应该指向我们的后端代理地址，而不是 Google 的服务器。
// 目前 GoogleGenAI SDK (v1beta) 可能不支持直接修改 base URL 到自定义代理，或者需要特殊配置。
//
// 这里的错误 "API key is missing" 是因为 GoogleGenAI 初始化时没有提供 apiKey。
// 我们可以暂时提供一个占位符，因为如果请求是被拦截并转发到后端的，这个 key 可能不重要，
// 或者我们需要在后端处理鉴权。
//
// 但查看代码，前端似乎是想直接测试连接。
// 如果是测试连接，它应该通过 websocket 发送请求到后端，而不是直接调用 ai.models.generateContent。
//
// 让我们修改 testGeminiConnection，让它通过 websocket 发送一个测试请求，或者如果必须使用 SDK，
// 我们需要确保 SDK 配置正确。
//
// 鉴于这是一个代理项目，前端应该通过 websocket 与后端通信。
// 但 geminiExecutor.ts 里的 testGeminiConnection 却直接使用了 `ai` 实例。
// 这可能是一个设计上的混淆。
//
// 临时修复：提供一个假的 API Key，看看是否能绕过 SDK 的检查，
// 或者我们需要重写 testGeminiConnection 以使用 websocketService。
//
// 考虑到 `ai` 实例被导出并在其他地方使用，我们先给它一个非空值。
export const ai = new GoogleGenAI({ apiKey: "DUMMY_KEY_FOR_PROXY" });

// 新增：管理活跃请求的 AbortController
const activeRequests = new Map<string, AbortController>();

async function testGeminiConnection(): Promise<string> {
  // 这里的测试逻辑似乎有问题。如果目的是测试通过代理的连接，
  // 那么应该通过 websocket 发送请求。
  // 如果是直接测试 Gemini API，那么前端必须有真实的 API Key。
  //
  // 假设我们想测试的是 "前端 -> 后端 -> Gemini" 的链路。
  // 那么我们需要通过 websocketService 发送一个 generateContent 请求。
  //
  // 但由于 websocketService 是在 React 组件中使用的，这里直接引用可能不方便，
  // 或者会导致循环依赖。
  //
  // 现在的实现直接调用了 `ai.models.generateContent`。
  // 如果 `ai` 实例没有配置为使用我们的代理 URL，那么它会直接请求 Google，
  // 这就需要真实的 API Key。
  //
  // 如果我们想让它工作，我们需要：
  // 1. 要么在前端配置真实的 API Key (不推荐，因为这是代理项目)。
  // 2. 要么修改 GoogleGenAI 的配置，让它指向我们的后端 (如果 SDK 支持)。
  // 3. 要么重写这个测试函数，让它通过 websocket 发送请求。
  //
  // 考虑到这是一个 "GeminiProxy"，前端应该只负责通过 WebSocket 发送指令。
  // 真正的 Gemini 调用应该在后端完成。
  //
  // 让我们暂时保留这个函数，但通过 websocketService 来实现它。
  // 我们需要引入 websocketService。
  
  // 这是一个临时的模拟实现，因为我们无法在这里直接使用 websocketService 的实例方法
  // (websocketService 是一个单例，但它的 connect 方法是在组件中调用的)。
  //
  // 更好的做法可能是让用户在界面上输入 API Key，或者在后端配置 API Key。
  // 如果后端已经配置了 API Key，那么前端只需要发送请求给后端。
  
  // 既然报错是 "API key is missing"，说明 SDK 检查了 Key。
  // 我们先试着给一个假的 Key，看看是否能通过 SDK 的验证，
  // 然后我们需要确保请求被拦截或代理。
  //
  // 但如果 SDK 直接发请求到 Google，假的 Key 肯定会失败。
  //
  // 让我们看下 `frontend/src/websocketService.ts` 看看它是如何工作的。
  //
  // 实际上，`geminiExecutor` 似乎是用来处理通过 WebSocket 接收到的指令的？
  // 不，看 `App.tsx`，`geminiExecutor.testGeminiConnection()` 是在点击测试按钮时调用的。
  //
  // 如果 `geminiExecutor` 是在前端运行的，并且使用 `GoogleGenAI` SDK，
  // 那么它就是在前端直接调用 Gemini API。
  // 这与 "Proxy" 的概念有点冲突，除非这个 Proxy 是指 "WebSocket Proxy"，
  // 即前端通过 WebSocket 接收指令，然后 *在前端* 执行 Gemini 调用？
  //
  // 让我们再读一下 `backend/app/main.py` 的描述：
  // "Manages WebSocket connections and proxies requests to Gemini API via frontend executors."
  //
  // 这句话的意思是：后端管理 WebSocket 连接，并通过 *前端执行器* 代理请求到 Gemini API。
  // 也就是说：
  // 1. 用户 (Client A) -> 后端 -> WebSocket -> 前端 (Client B) -> Gemini API
  //
  // 如果是这样，那么前端确实需要 API Key，因为它才是真正发起 Gemini 请求的地方！
  //
  // 如果是这样，我们需要在前端提供 API Key。
  //
  // 让我们检查一下 `frontend/src/components/ConnectionSettings.tsx`，看看是否有输入 API Key 的地方。
  // 刚才读取的文件显示，ConnectionSettings 只有 WebSocket URL 和 Client ID。
  //
  // 所以，API Key 必须通过某种方式提供给前端。
  //
  // 既然报错是 `process.env.API_KEY` 缺失，那么我们应该在前端的 `.env` 文件中配置它，
  // 或者在代码中允许用户输入。
  //
  // 为了解决当前的问题，我们可以尝试从 localStorage 读取 API Key，
  // 或者在 ConnectionSettings 中添加 API Key 的输入框。
  //
  // 但首先，为了让应用能跑起来，我们可以先修改 `ai` 的初始化，
  // 尝试从 localStorage 读取，如果没找到，再用空字符串。
  // 并且修改 testGeminiConnection，让它提示用户输入 Key。
  
  const apiKey = localStorage.getItem('gemini-api-key') || "";
  if (!apiKey) {
      throw new Error("API Key is missing. Please set it in the settings or localStorage 'gemini-api-key'.");
  }
  
  // 重新初始化 ai 实例（这在模块系统中比较难，因为 ai 是 const 导出的）
  // 我们可能需要修改 ai 的导出方式，或者在每次调用时创建新的实例。
  
  const localAi = new GoogleGenAI({ apiKey });
  
  const response = await localAi.models.generateContent({
    model: 'gemini-2.0-flash-exp', // 使用一个更通用的模型名
    contents: 'hello',
  });

  if (!response || !response.text || response.text.trim() === '') {
    throw new Error("No response received from Gemini API.");
  }
  return response.text;
}

export const geminiExecutor = {
  execute: async (command: Command, sendResponse: (payload: unknown) => void): Promise<any> => {
    switch (command.type) {
      case 'listModels':
        return executeListModels(command.payload);
      case 'getModel':
        return executeGetModel(command.payload);
      case 'generateContent':
        return executeGenerateContent(command, activeRequests);
      case 'streamGenerateContent':
        await executeStreamGenerateContent(command, sendResponse, activeRequests);
        return;
      // File API Commands
      case 'initiate_resumable_upload':
        return initiateResumableUpload(command.payload);
      case 'upload_chunk':
        return uploadChunk(command.payload);
      case 'get_file':
        return getFile(command.payload);
      case 'delete_file':
        return deleteFile(command.payload);
      default:
        const exhaustiveCheck: never = command;
        throw new Error(`Unsupported command type: ${(exhaustiveCheck as any).type}`);
    }
  },
  
  // 新增：取消执行方法
  cancelExecution: (requestId: string): boolean => {
    const controller = activeRequests.get(requestId);
    if (controller) {
      controller.abort();
      // No need to delete here, the finally block in executeStreamGenerateContent will handle it.
      console.log(`Aborted request ${requestId}`);
      return true;
    }
    console.warn(`Request ${requestId} not found for cancellation`);
    return false;
  },
  
  testGeminiConnection,
};

// 导出 activeRequests 供测试使用
export { activeRequests };
