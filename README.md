# Gemini API Python Proxy

## 1. Introduction

This project is a complete refactoring of the original Go-based Gemini API proxy. It provides a high-fidelity, fully-featured proxy server that allows third-party tools (like LobeChat, OneAPI, etc.) to use Google's Gemini API for free by leveraging the execution environment of Google AI Studio.

The core principle remains the same: hijacking the `fetch` function in an AI Studio environment. However, this version is rebuilt with a more robust and maintainable architecture using Python/FastAPI for the backend and React for the frontend.

## 2. Architecture

The system is designed with a clear separation of concerns:

-   **Backend (Python/FastAPI):** Acts as a high-performance API gateway. It simulates the entire Gemini REST API, handles client requests, manages a pool of frontend executors, performs load balancing, and formats responses.
-   **Frontend (React/Vite):** A lightweight execution client that runs in a browser tab on Google AI Studio. It listens for tasks from the backend via WebSocket, executes them using the `@google/generative-ai` SDK, and streams the results back.

For a detailed breakdown, see [`docs/REFACTOR_PLAN.md`](./docs/REFACTOR_PLAN.md).

## 3. Features

-   **Full Gemini API Compatibility:** Simulates all key endpoints, including `generateContent`, `streamGenerateContent`, `embedContent`, `files` API, and `cachedContents`.
-   **High Availability:** Supports multiple frontend clients, with automatic health checks and round-robin load balancing.
-   **Transparent Proxy:** Requires no changes to the configuration of third-party tools.
-   **No API Key Required:** Inherits the core advantage of the original project.

## 4. Local Development Setup

### 4.1. Prerequisites

-   Python 3.8+
-   Node.js 18+ and npm

### 4.2. Backend Setup

1.  **Navigate to the backend directory:**
    ```bash
    cd backend
    ```

2.  **Create a virtual environment:**
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows, use `venv\Scripts\activate`
    ```

3.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Run the backend server:**
    ```bash
    uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
    ```
    The backend server will be running at `http://localhost:8000`.

### 4.3. Frontend Setup

1.  **Navigate to the frontend directory:**
    ```bash
    cd frontend
    ```

2.  **Install dependencies:**
    ```bash
    npm install
    ```

3.  **Run the frontend development server:**
    ```bash
    npm run dev
    ```
    The frontend will be available at `http://localhost:5173` (or another port if 5173 is in use).

### 4.4. Running the System

1.  Start the backend server as described above.
2.  Open one or more browser tabs and navigate to the frontend's URL (`http://localhost:5173`). These tabs must be running in the **Google AI Studio** environment to work correctly.
3.  Each opened tab will register itself as a client to the backend.
4.  Configure your third-party AI tool to point to the backend server's address (`http://localhost:8000`) as the Gemini API endpoint.
5.  Make API calls from your tool. The backend will automatically load-balance requests across all connected frontend clients.