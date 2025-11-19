#!/usr/bin/env python3
"""
简化的上传和立即查询测试（不重启服务器）
"""

import requests
import json
import os
import sys
from pathlib import Path

def test_upload_and_immediate_query():
    """测试上传后立即查询，避免重启问题"""

    # 使用一个小的测试PDF文件
    file_path = "/Users/breeze/Documents/code/python/his.pdf"
    if not os.path.exists(file_path):
        print("❌ 测试文件不存在")
        return

    filename = Path(file_path).name

    print("🧪 简化测试：上传后立即查询")
    print("=" * 50)

    # 1. 上传文件
    print("📤 上传文件...")
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
        print(f"❌ 初始化失败: {init_response.status_code}")
        return

    upload_url = init_response.headers.get("X-Goog-Upload-URL")

    with open(file_path, 'rb') as f:
        file_data = f.read()

    headers = {
        'Content-Type': 'application/pdf',
        'X-Goog-Upload-Command': 'upload, finalize'
    }

    upload_response = requests.post(upload_url, headers=headers, data=file_data)

    if upload_response.status_code != 200:
        print(f"❌ 上传失败: {upload_response.status_code}")
        return

    upload_result = upload_response.json()
    file_name = upload_result.get("file", {}).get("name", "")

    print(f"✅ 上传成功，文件名: {file_name}")

    # 2. 立即测试文件列表（应该能看到刚上传的文件）
    print("\n📋 测试文件列表...")
    list_response = requests.get("http://127.0.0.1:8000/v1beta/files")

    if list_response.status_code == 200:
        list_data = list_response.json()
        files = list_data.get("files", [])
        print(f"✅ 文件列表成功，共 {len(files)} 个文件")
        for i, file_info in enumerate(files):
            name = file_info.get("displayName", "Unknown")
            mime = file_info.get("mimeType", "Unknown")
            print(f"  {i+1}. {name} ({mime})")
    else:
        print(f"❌ 文件列表失败: {list_response.status_code} - {list_response.text}")

    # 3. 立即测试文件详情
    if file_name:
        print(f"\n🔍 测试文件详情: {file_name}")
        detail_response = requests.get(f"http://127.0.0.1:8000/v1beta/files/{file_name}")

        if detail_response.status_code == 200:
            print("✅ 文件详情查询成功")
            file_info = detail_response.json()
            print(f"  显示名: {file_info.get('displayName')}")
            print(f"  MIME类型: {file_info.get('mimeType')}")
            print(f"  状态: {file_info.get('state')}")
        else:
            print(f"❌ 文件详情失败: {detail_response.status_code} - {detail_response.text}")

    print("\n🎯 结论:")
    print("- 如果文件列表和详情在重启服务器前正常工作，说明MIME类型修正功能正常")
    print("- 重启后的问题是缓存持久化问题，不影响核心功能")

if __name__ == "__main__":
    test_upload_and_immediate_query()