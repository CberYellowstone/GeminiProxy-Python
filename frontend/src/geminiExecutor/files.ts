import { ApiError } from '../errors/ApiError';
import {
  DeleteFilePayload,
  GetFilePayload,
  InitiateResumableUploadPayload,
  UploadChunkPayload,
} from '../types/files';
const GOOGLE_API_URL = "https://generativelanguage.googleapis.com/v1beta";

/**
 * Initiates a resumable upload with the Google AI API.
 * @param payload - The payload from the backend command.
 * @returns An object containing the Google-provided upload URL.
 */
export async function initiateResumableUpload(
  payload: InitiateResumableUploadPayload,
): Promise<{ upload_url: string }> {
  const response = await fetch(`${GOOGLE_API_URL.replace('/v1beta', '/upload/v1beta')}/files`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Goog-Upload-Protocol': 'resumable',
      'X-Goog-Upload-Command': 'start',
      'X-Goog-Upload-Header-Content-Length': payload.metadata.file.sizeBytes,
      'X-Goog-Upload-Header-Content-Type': payload.metadata.file.mimeType,
    },
    body: JSON.stringify(payload.metadata),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ error: { message: response.statusText } }));
    throw new ApiError(`Failed to initiate upload: ${error.error?.message || response.statusText}`, response.status, error);
  }

  const uploadUrl = response.headers.get('x-goog-upload-url');
  if (!uploadUrl) {
    throw new ApiError('Could not get upload URL from Google API response.', 500, null);
  }

  return { upload_url: uploadUrl };
}

/**
 * Uploads a file chunk to the Google AI API.
 * @param payload - The payload from the backend command.
 * @returns The response from the Google API.
 */
export async function uploadChunk(payload: UploadChunkPayload): Promise<any> {
  let chunkBlob: Blob;
  // 1. Download the chunk from our backend
  try {
    const chunkResponse = await fetch(payload.chunk_download_url);
    if (!chunkResponse.ok) {
      const error = await chunkResponse.json().catch(() => ({ error: { message: chunkResponse.statusText } }));
      throw new ApiError(`Failed to download chunk from backend: ${error.error?.message || chunkResponse.statusText}`, chunkResponse.status, error);
    }
    chunkBlob = await chunkResponse.blob();
  } catch (error) {
    console.error("Error downloading chunk from backend:", error);
    throw new Error("Failed to download chunk from backend");
  }

  // 2. Upload the chunk to the real Google upload URL
  try {
    const uploadResponse = await fetch(payload.upload_url, {
      method: 'POST',
      headers: {
        'X-Goog-Upload-Command': payload.upload_command,
        'X-Goog-Upload-Offset': String(payload.upload_offset),
        'Content-Length': String(payload.content_length),
      },
      body: chunkBlob,
    });

    if (!uploadResponse.ok) {
      const error = await uploadResponse.json().catch(() => ({ error: { message: uploadResponse.statusText } }));
      throw new ApiError(`Chunk upload failed: ${error.error?.message || uploadResponse.statusText}`, uploadResponse.status, error);
    }

    // 3. Return the response with headers and body
    const uploadStatus = uploadResponse.headers.get('x-goog-upload-status');
    const headers: Record<string, string> = {};

    // Convert headers to plain object
    uploadResponse.headers.forEach((value, key) => {
      headers[key] = value;
    });

    if (uploadStatus === 'final' || payload.upload_command === 'upload, finalize') {
      // The last chunk response contains the final File object.
      const responseBody = await uploadResponse.json();
      return {
        status: uploadResponse.status,
        headers: headers,
        body: responseBody
      };
    }

    // For intermediate chunks, return status, headers and body
    const responseBody = await uploadResponse.text();
    return {
      status: uploadResponse.status,
      headers: headers,
      body: responseBody || '{}'
    };
  } catch (error) {
    console.error("Error uploading chunk to Gemini:", error);
    throw new Error("Failed to upload chunk to Gemini");
  }
}

/**
 * Gets file metadata from the Google AI API.
 * @param payload - The payload from the backend command.
 * @returns The file metadata.
 */
export async function getFile(payload: GetFilePayload): Promise<any> {
  const response = await fetch(`${GOOGLE_API_URL}/${payload.file_name}`);

  if (!response.ok) {
    const error = await response.json().catch(() => ({ error: { message: response.statusText } }));
    throw new ApiError(`Failed to get file: ${error.error?.message || response.statusText}`, response.status, error);
  }

  return await response.json();
}

/**
 * Deletes a file from the Google AI API.
 * @param payload - The payload from the backend command.
 */
export async function deleteFile(payload: DeleteFilePayload): Promise<void> {
  const response = await fetch(`${GOOGLE_API_URL}/${payload.file_name}`, {
    method: 'DELETE',
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ error: { message: response.statusText } }));
    throw new ApiError(`Failed to delete file: ${error.error?.message || response.statusText}`, response.status, error);
  }
}