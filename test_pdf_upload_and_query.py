#!/usr/bin/env python3
"""
完整的PDF文件上传和查询测试脚本

功能：
1. 上传指定的PDF文件
2. 获取上传的文件信息
3. 使用上传的文件进行内容生成查询
"""

import base64
import json
import requests
import os
import sys
from pathlib import Path


def upload_file(file_path: str) -> dict:
    """
    上传文件到后端

    Args:
        file_path: 要上传的文件路径

    Returns:
        上传成功的文件信息
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"文件不存在: {file_path}")

    filename = Path(file_path).name
    file_size = os.path.getsize(file_path)

    print(f"📁 准备上传文件: {filename}")
    print(f"📏 文件大小: {file_size} 字节")

    # 1. 第一步：初始化上传会话
    print("\n🔄 步骤1: 初始化上传会话...")
    init_payload = {
        "file": {
            "display_name": filename,
            "mime_type": "application/pdf"
        }
    }

    init_response = requests.post(
        "http://127.0.0.1:8000/upload/v1beta/files",
        json=init_payload
    )

    if init_response.status_code != 200:
        print(f"❌ 初始化失败: {init_response.status_code} - {init_response.text}")
        sys.exit(1)

    upload_url = init_response.headers.get("X-Goog-Upload-URL")
    session_id = upload_url.split('/')[-1] if upload_url else None

    print(f"✅ 上传会话已创建")
    print(f"📝 Session ID: {session_id}")
    print(f"🔗 上传URL: {upload_url}")

    # 2. 第二步：上传文件内容
    print(f"\n📤 步骤2: 上传文件内容...")

    with open(file_path, 'rb') as f:
        file_data = f.read()

    headers = {
        'Content-Type': 'application/pdf',
        'X-Goog-Upload-Command': 'upload, finalize'
    }

    upload_response = requests.post(
        upload_url,
        headers=headers,
        data=file_data
    )

    if upload_response.status_code != 200:
        print(f"❌ 上传失败: {upload_response.status_code} - {upload_response.text}")
        sys.exit(1)

    try:
        file_info = upload_response.json()
        print(f"✅ 文件上传成功!")
        print(f"📄 文件信息: {json.dumps(file_info, indent=2, ensure_ascii=False)}")
        return file_info
    except json.JSONDecodeError:
        print(f"❌ 响应解析失败: {upload_response.text}")
        sys.exit(1)


def list_files() -> list:
    """
    列出所有已上传的文件

    Returns:
        文件列表
    """
    print("\n📋 获取文件列表...")

    try:
        response = requests.get("http://127.0.0.1:8000/v1beta/files")

        if response.status_code != 200:
            print(f"❌ 获取文件列表失败: {response.status_code} - {response.text}")
            return []

        data = response.json()
        files = data.get("files", [])

        print(f"✅ 成功获取文件列表，共 {len(files)} 个文件:")

        if files:
            for i, file_info in enumerate(files, 1):
                name = file_info.get("displayName", "Unknown")
                mime_type = file_info.get("mimeType", "Unknown")
                size = file_info.get("sizeBytes", "Unknown")
                print(f"  {i}. {name} ({mime_type}, {size} 字节)")

        return files
    except Exception as e:
        print(f"❌ 获取文件列表时发生错误: {str(e)}")
        return []


def query_with_file(file_name: str, question: str):
    """
    使用上传的文件进行查询

    Args:
        file_name: 文件名
        question: 要询问的问题
    """
    print(f"\n❓ 使用文件 '{file_name}' 询问问题:")
    print(f"📝 问题: {question}")

    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "text": f"基于上传的文件 {file_name}，请回答：{question}。请用中文回答。"
                    }
                ]
            }
        ]
    }

    try:
        response = requests.post(
            f"http://127.0.0.1:8000/v1beta/models/gemini-2.5-pro:generateContent",
            json=payload
        )

        if response.status_code != 200:
            print(f"❌ 查询失败: {response.status_code} - {response.text}")
            return

        result = response.json()

        # 提取生成的文本内容
        candidates = result.get("candidates", [])
        if candidates:
            content = candidates[0].get("content", {}).get("parts", [])
            if content and len(content) > 0:
                text = content[0].get("text", "")
                print(f"\n✅ 回答内容:")
                print("-" * 50)
                print(text)
                print("-" * 50)
            else:
                print("❌ 没有找到回答内容")
        else:
            print("❌ 没有生成回答")

    except Exception as e:
        print(f"❌ 查询时发生错误: {str(e)}")


def get_file_details(file_name: str):
    """
    获取特定文件的详细信息

    Args:
        file_name: 文件名
    """
    print(f"\n🔍 获取文件 '{file_name}' 的详细信息...")

    try:
        response = requests.get(f"http://127.0.0.1:8000/v1beta/files/{file_name}")

        if response.status_code != 200:
            print(f"❌ 获取文件详情失败: {response.status_code} - {response.text}")
            return

        file_info = response.json()
        print(f"✅ 文件详细信息:")
        print("-" * 50)
        print(json.dumps(file_info, indent=2, ensure_ascii=False))
        print("-" * 50)

        return file_info
    except Exception as e:
        print(f"❌ 获取文件详情时发生错误: {str(e)}")
        return None


def main():
    """主函数"""
    print("=" * 60)
    print("🧪 PDF文件上传和查询测试")
    print("=" * 60)

    # 检查后端服务是否可用
    try:
        response = requests.get("http://127.0.0.1:8000/health", timeout=5)
    except requests.exceptions.RequestException:
        print("❌ 无法连接到后端服务，请确保后端服务器正在运行")
        sys.exit(1)

    # 文件路径
    file_path = "/Users/breeze/Documents/code/python/his.pdf"

    # 1. 上传文件
    uploaded_file = upload_file(file_path)
    file_name = uploaded_file.get("file", {}).get("name", "")

    if file_name:
        # 2. 获取文件详情
        get_file_details(file_name)

        # 3. 列出所有文件
        list_files()

        # 4. 查询文件内容
        query_with_file(file_name, "这本书第一章是什么内容？请详细总结主要观点")

        print(f"\n🎉 测试完成！文件 '{file_name}' 已成功上传并可进行查询")
    else:
        print("❌ 无法获取上传的文件名")


if __name__ == "__main__":
    main()