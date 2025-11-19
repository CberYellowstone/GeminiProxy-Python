#!/usr/bin/env python3
"""
Utility script to upload a file through the proxy API and optionally trigger one
of the debug endpoints for simulating Gemini-side expiration or deletion.
"""

from __future__ import annotations

import argparse
import hashlib
import mimetypes
import os
from pathlib import Path
from pprint import pprint
from typing import Any, Dict, Optional

import requests

DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_FILE_PATH = "/Users/breeze/Documents/1111.pdf"
REQUEST_TIMEOUT = 30


def build_url(base: str, path: str) -> str:
    """Join the base URL with a leading-slash path."""
    return f"{base.rstrip('/')}{path}"


def initiate_upload_session(base_url: str, *, display_name: str, mime_type: str, size_bytes: int) -> str:
    """Calls POST /upload/v1beta/files and returns the upload URL."""
    payload = {
        "file": {
            "displayName": display_name,
            "mimeType": mime_type,
            "sizeBytes": str(size_bytes),
        }
    }
    resp = requests.post(
        build_url(base_url, "/upload/v1beta/files"),
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    upload_url = resp.headers.get("X-Goog-Upload-URL")
    if not upload_url:
        raise RuntimeError("Upload session did not provide X-Goog-Upload-URL header")
    return upload_url


def upload_file(upload_url: str, *, file_bytes: bytes, file_path: Path, mime_type: str) -> Dict[str, Any]:
    """Uploads the actual file bytes to the resumable endpoint."""
    headers = {
        "Content-Type": mime_type,
        "Content-Length": str(len(file_bytes)),
        "Content-Disposition": f'attachment; filename="{file_path.name}"',
    }
    resp = requests.post(upload_url, data=file_bytes, headers=headers, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    try:
        payload = resp.json()
    except ValueError as exc:
        raise RuntimeError(f"Upload response is not JSON: {resp.text}") from exc
    if "file" not in payload:
        raise RuntimeError(f"Unexpected upload response payload: {payload}")
    return payload["file"]


def trigger_mock_expire(base_url: str, sha256_hex: str) -> dict:
    """Hit the /v1beta/debug/mock-expire endpoint to backdate gemini_file_expiration."""
    resp = requests.post(
        build_url(base_url, "/v1beta/debug/mock-expire"),
        json={"sha": sha256_hex},
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def trigger_remote_delete(base_url: str, sha256_hex: str, client_id: Optional[str]) -> dict:
    """Hit the /v1beta/debug/delete-remote endpoint."""
    payload: Dict[str, Any] = {"sha": sha256_hex}
    if client_id:
        payload["clientId"] = client_id
    resp = requests.post(
        build_url(base_url, "/v1beta/debug/delete-remote"),
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def invoke_via_genai_sdk(
    base_url: str,
    *,
    model_name: str,
    file_info: Dict[str, Any],
    prompt: str,
    timeout: int,
) -> None:
    """Use google-generativeai SDK to send a generateContent request through the proxy."""
    try:
        import google.generativeai as genai
    except ImportError as exc:
        raise SystemExit("google-generativeai is required. Install via `pip install google-generativeai`.") from exc

    api_endpoint = build_url(base_url, "/api")
    api_key = os.environ.get("GOOGLE_API_KEY", "local-debug-key")
    genai.configure(
        api_key=api_key,
        client_options={"api_endpoint": api_endpoint},
    )

    model = genai.GenerativeModel(model_name, transport="rest")

    file_uri = file_info.get("name")
    if not file_uri:
        raise SystemExit("Uploaded file response does not include a 'name'; cannot reference it in SDK call.")

    mime_type = file_info.get("mimeType") or "application/octet-stream"
    contents = [
        {
            "role": "user",
            "parts": [{"text": prompt}],
        },
        {
            "role": "user",
            "parts": [
                {
                    "file_data": {
                        "file_uri": file_uri,
                        "mime_type": mime_type,
                    }
                }
            ],
        },
    ]

    print(
        f"Invoking google-generativeai SDK -> model={model_name}, file_uri={file_uri}, prompt='{prompt}'",
    )
    response = model.generate_content(
        contents=contents,
        request_options={"timeout": timeout},
    )
    print("SDK response:")
    if hasattr(response, "to_dict"):
        pprint(response.to_dict())
    else:
        pprint(response)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Upload a file and exercise debug file endpoints.")
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help="FastAPI base URL (default: %(default)s)",
    )
    parser.add_argument(
        "--file",
        default=DEFAULT_FILE_PATH,
        help="Path to the file that will be uploaded first (default: %(default)s)",
    )
    parser.add_argument(
        "--action",
        choices=["expire", "delete-remote", "both", "none"],
        default="delete-remote",
        help="Which debug action to trigger after upload (default: %(default)s)",
    )
    parser.add_argument(
        "--client-id",
        help="Optional client ID to use for delete-remote action.",
    )
    parser.add_argument(
        "--invoke-sdk",
        action="store_true",
        help="After debug action, call the proxy via google-generativeai SDK referencing the uploaded file.",
    )
    parser.add_argument(
        "--model",
        default="gemini-1.5-flash-latest",
        help="Model name for the SDK request (default: %(default)s)",
    )
    parser.add_argument(
        "--prompt",
        default="读取附件，并告诉我它的字节大小。",
        help="Prompt text to send to the model when --invoke-sdk is set.",
    )
    parser.add_argument(
        "--sdk-timeout",
        type=int,
        default=60,
        help="Timeout (seconds) for the SDK generateContent request.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    base_url = args.base_url.rstrip("/")
    file_path = Path(args.file).expanduser()
    if not file_path.is_file():
        raise SystemExit(f"File not found: {file_path}")

    file_bytes = file_path.read_bytes()
    size_bytes = len(file_bytes)
    sha256_hex = hashlib.sha256(file_bytes).hexdigest()
    mime_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"

    print(f"Uploading {file_path} ({size_bytes} bytes, sha256={sha256_hex}) via {base_url}")
    upload_url = initiate_upload_session(
        base_url,
        display_name=file_path.name,
        mime_type=mime_type,
        size_bytes=size_bytes,
    )
    print(f"Upload URL: {upload_url}")

    file_info = upload_file(upload_url, file_bytes=file_bytes, file_path=file_path, mime_type=mime_type)
    print("Upload completed. Gemini file metadata:")
    for key, value in file_info.items():
        print(f"  - {key}: {value}")

    if args.action in {"expire", "both"}:
        response = trigger_mock_expire(base_url, sha256_hex)
        print(f"mock-expire response: {response}")

    if args.action in {"delete-remote", "both"}:
        response = trigger_remote_delete(base_url, sha256_hex, args.client_id)
        print(f"delete-remote response: {response}")

    if args.action == "none":
        print("No debug action requested; exiting.")
    elif args.invoke_sdk:
        invoke_via_genai_sdk(
            base_url,
            model_name=args.model,
            file_info=file_info,
            prompt=args.prompt,
            timeout=args.sdk_timeout,
        )
    else:
        print(
            "Debug action completed. Trigger a normal request that references this file to observe "
            "the backend handling (TTL cleanup or remote 404 rebuild)."
        )


if __name__ == "__main__":
    main()
