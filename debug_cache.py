#!/usr/bin/env python3
"""
调试文件缓存状态的脚本
"""

import sys
import os
import json
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backend'))

from app.core.file_manager import file_manager
from app.schemas.gemini_files import File

def debug_cache_state():
    """调试缓存状态"""
    print("=== 文件缓存状态调试 ===")

    print(f"元数据存储条目数: {len(file_manager.metadata_store)}")
    print(f"反向映射条目数: {len(file_manager.reverse_mapping)}")

    print("\n=== 元数据存储内容 ===")
    for sha256, entry in file_manager.metadata_store.items():
        print(f"SHA256: {sha256[:8]}...")
        print(f"  原始文件名: {entry.original_filename}")
        print(f"  MIME类型: {entry.mime_type}")
        print(f"  大小: {entry.size_bytes}")
        print(f"  复制映射: {len(entry.replication_map)} 个客户端")

        for client_id, data in entry.replication_map.items():
            print(f"    客户端 {client_id}:")
            print(f"      状态: {data.get('status', 'unknown')}")
            print(f"      数据键: {list(data.keys())}")

            # 检查是否包含完整的文件数据
            if "name" in data:
                print(f"      文件名: {data.get('name')}")
                try:
                    # 尝试验证数据
                    file_obj = File.model_validate(data)
                    print(f"      ✓ File.model_validate 成功")
                except Exception as e:
                    print(f"      ✗ File.model_validate 失败: {e}")

            print("    ---")
        print()

    print("=== 反向映射内容 ===")
    for file_name, sha256 in file_manager.reverse_mapping.items():
        print(f"{file_name} -> {sha256[:8]}...")

    print("\n=== 尝试文件列表操作 ===")
    try:
        from app.api.v1beta.files import list_files
        from app.schemas.gemini_files import ListFilesPayload

        # 创建默认参数
        params = ListFilesPayload()
        result = list_files(params)
        print("✓ 文件列表操作成功")
        print(f"  返回文件数: {len(result.files)}")
        for i, file_obj in enumerate(result.files):
            print(f"    {i+1}. {file_obj.displayName} ({file_obj.mimeType})")
    except Exception as e:
        print(f"✗ 文件列表操作失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    debug_cache_state()