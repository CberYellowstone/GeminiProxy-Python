#!/usr/bin/env python3
"""
测试新的Base64文件上传功能
"""

import base64
import json
import os
import requests
import tempfile
import time


def create_test_file():
    """创建一个测试文件"""
    content = b"Hello, World! This is a test file for Base64 upload functionality."

    # 创建临时文件
    with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.txt') as f:
        f.write(content)
        return f.name, len(content)


def test_base64_upload():
    """测试Base64文件上传流程"""
    print("开始测试Base64文件上传...")

    # 1. 创建测试文件
    test_file_path, file_size = create_test_file()
    filename = os.path.basename(test_file_path)

    try:
        # 2. 读取文件内容并编码为Base64
        with open(test_file_path, 'rb') as f:
            file_data = f.read()

        base64_data = base64.b64encode(file_data).decode('utf-8')
        print(f"文件大小: {file_size} 字节")
        print(f"Base64编码长度: {len(base64_data)} 字符")

        # 3. 第一步：初始化上传会话
        print("\n步骤1: 初始化上传会话...")
        init_payload = {
            "file": {
                "display_name": filename,
                "mime_type": "text/plain"
            }
        }

        init_response = requests.post(
            "http://127.0.0.1:8000/upload/v1beta/files",
            json=init_payload
        )

        if init_response.status_code != 200:
            print(f"初始化失败: {init_response.status_code} - {init_response.text}")
            return False

        upload_url = init_response.headers.get("X-Goog-Upload-URL")
        session_id = upload_url.split('/')[-1] if upload_url else None

        print(f"上传会话已创建，Session ID: {session_id}")
        print(f"上传URL: {upload_url}")

        # 4. 第二步：上传文件内容
        print("\n步骤2: 上传文件内容...")

        # 设置正确的Content-Type
        headers = {
            'Content-Type': 'text/plain',
            'X-Goog-Upload-Command': 'upload, finalize'
        }

        upload_response = requests.post(
            upload_url,
            headers=headers,
            data=file_data  # 直接发送原始文件数据
        )

        print(f"上传响应状态: {upload_response.status_code}")

        if upload_response.status_code == 200:
            result = upload_response.json()
            print("✅ 文件上传成功!")
            print(f"文件信息: {json.dumps(result, indent=2, ensure_ascii=False)}")
            return True
        else:
            print(f"❌ 上传失败: {upload_response.status_code} - {upload_response.text}")
            return False

    except Exception as e:
        print(f"❌ 测试过程中发生错误: {str(e)}")
        return False

    finally:
        # 清理测试文件
        if os.path.exists(test_file_path):
            os.unlink(test_file_path)
            print(f"\n🧹 已清理测试文件: {test_file_path}")


def test_file_list():
    """测试文件列表功能"""
    print("\n\n测试文件列表功能...")

    try:
        response = requests.get("http://127.0.0.1:8000/v1beta/files")

        if response.status_code == 200:
            result = response.json()
            files = result.get("files", [])
            print(f"✅ 成功获取文件列表，共 {len(files)} 个文件")

            if files:
                print("文件列表:")
                for i, file_info in enumerate(files, 1):
                    print(f"  {i}. {file_info.get('name', 'Unknown')} ({file_info.get('mimeType', 'Unknown')})")
            else:
                print("  (暂无文件)")

            return True
        else:
            print(f"❌ 获取文件列表失败: {response.status_code} - {response.text}")
            return False

    except Exception as e:
        print(f"❌ 测试文件列表时发生错误: {str(e)}")
        return False


if __name__ == "__main__":
    print("=" * 60)
    print("🧪 测试Base64文件上传功能")
    print("=" * 60)

    # 等待服务器启动
    print("等待服务器启动...")
    time.sleep(2)

    # 测试上传
    upload_success = test_base64_upload()

    # 测试列表
    list_success = test_file_list()

    # 总结
    print("\n" + "=" * 60)
    print("📊 测试结果总结")
    print("=" * 60)
    print(f"文件上传: {'✅ 成功' if upload_success else '❌ 失败'}")
    print(f"文件列表: {'✅ 成功' if list_success else '❌ 失败'}")

    if upload_success and list_success:
        print("\n🎉 所有测试通过! Base64文件上传功能正常工作。")
    else:
        print("\n⚠️  部分测试失败，请检查后端日志。")