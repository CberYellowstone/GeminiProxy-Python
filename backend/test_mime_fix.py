#!/usr/bin/env python3
"""
MIME 类型修正功能测试脚本

用于验证上传和生成阶段的 MIME 类型修正是否能正确工作。
"""

import sys
import os
import asyncio

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.core.mime_utils import MimeUtils

def test_mime_inference():
    """测试 MIME 类型推断功能"""
    print("=== MIME 类型推断测试 ===")

    test_cases = [
        # (文件名, 期望的 MIME 类型)
        ("document.pdf", "application/pdf"),
        ("image.jpg", "image/jpeg"),
        ("photo.jpeg", "image/jpeg"),
        ("picture.png", "image/png"),
        ("audio.mp3", "audio/mpeg"),
        ("video.mp4", "video/mp4"),
        ("text.txt", "text/plain"),
        ("code.py", "text/x-python"),
        ("data.json", "application/json"),
        ("archive.zip", "application/zip"),
        ("unknown.xyz", "application/octet-stream"),
        ("", "application/octet-stream"),
    ]

    for filename, expected in test_cases:
        result = MimeUtils.infer_mime_type(filename)
        status = "✓" if result == expected else "✗"
        print(f"{status} {filename:15} -> {result} (期望: {expected})")

def test_mime_correction():
    """测试 MIME 类型修正判断"""
    print("\n=== MIME 类型修正判断测试 ===")

    test_cases = [
        # (当前 MIME, 文件名, 是否应该修正)
        ("application/octet-stream", "image.jpg", True),
        ("text/plain", "photo.jpg", True),  # 图片不应该标记为文本
        ("application/octet-stream", "document.pdf", True),
        ("text/plain", "data.pdf", True),   # PDF 不应该标记为文本
        ("application/octet-stream", "text.txt", True),
        ("text/plain", "text.txt", False), # 文本文件已经是正确的
        ("image/jpeg", "image.jpg", False), # 已经正确
        ("application/pdf", "document.pdf", False), # 已经正确
        ("application/octet-stream", "unknown.xyz", False), # 无法推断，保持原样
    ]

    for current_mime, filename, should_correct in test_cases:
        should_correct_result = MimeUtils.should_correct_mime_type(current_mime, filename)
        status = "✓" if should_correct_result == should_correct else "✗"
        expected_str = "应该修正" if should_correct else "不应该修正"
        result_str = "会修正" if should_correct_result else "不会修正"
        print(f"{status} {current_mime:25} + {filename:15} -> {result_str} (期望: {expected_str})")

def test_get_corrected_mime():
    """测试获取修正后的 MIME 类型"""
    print("\n=== MIME 类型修正测试 ===")

    test_cases = [
        # (当前 MIME, 文件名, 期望的修正后 MIME)
        ("application/octet-stream", "image.jpg", "image/jpeg"),
        ("text/plain", "photo.jpg", "image/jpeg"),
        ("application/octet-stream", "document.pdf", "application/pdf"),
        ("application/octet-stream", "text.txt", "text/plain"),
        ("image/jpeg", "image.jpg", "image/jpeg"),  # 已经正确，不修改
        ("text/plain", "text.txt", "text/plain"),   # 已经正确，不修改
        ("application/octet-stream", "unknown.xyz", "application/octet-stream"),  # 无法推断，保持原样
    ]

    for current_mime, filename, expected in test_cases:
        corrected = MimeUtils.get_corrected_mime_type(current_mime, filename)
        status = "✓" if corrected == expected else "✗"
        print(f"{status} {current_mime:25} + {filename:15} -> {corrected} (期望: {expected})")

def test_file_type_detection():
    """测试文件类型检测功能"""
    print("\n=== 文件类型检测测试 ===")

    test_cases = [
        ("image/jpeg", "image", "图片文件"),
        ("text/plain", "text", "文本文件"),
        ("application/json", "text", "JSON 文本文件"),
        ("audio/mpeg", "audio", "音频文件"),
        ("video/mp4", "video", "视频文件"),
        ("application/octet-stream", "unknown", "未知类型"),
    ]

    for mime_type, expected_type, description in test_cases:
        is_image = MimeUtils.is_image_file(mime_type)
        is_text = MimeUtils.is_text_file(mime_type)
        is_audio = MimeUtils.is_audio_file(mime_type)
        is_video = MimeUtils.is_video_file(mime_type)

        type_matches = (
            (expected_type == "image" and is_image) or
            (expected_type == "text" and is_text) or
            (expected_type == "audio" and is_audio) or
            (expected_type == "video" and is_video) or
            (expected_type == "unknown" and not any([is_image, is_text, is_audio, is_video]))
        )

        status = "✓" if type_matches else "✗"
        print(f"{status} {mime_type:25} -> {description} (检测: 图像={is_image}, 文本={is_text}, 音频={is_audio}, 视频={is_video})")

def main():
    """运行所有测试"""
    print("MIME 类型修正功能测试")
    print("=" * 50)

    test_mime_inference()
    test_mime_correction()
    test_get_corrected_mime()
    test_file_type_detection()

    print("\n" + "=" * 50)
    print("测试完成！")
    print("\n预期效果:")
    print("1. 上传时 application/octet-stream 会被智能修正为正确的 MIME 类型")
    print("2. 生成时错误的 MIME 类型会被动态修正")
    print("3. 这应该能解决因 MIME 类型不匹配导致的 500 错误")

if __name__ == "__main__":
    main()