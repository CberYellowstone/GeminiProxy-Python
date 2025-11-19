
import { ApiError } from '../errors/ApiError';
import {
  CreateFilePayload,
  DeleteFilePayload,
  GetFilePayload,
  UpdateFilePayload,
} from '../types/files';
import { GOOGLE_API_URL } from "./geminiExecutor";
import { parseMimeType } from './utils/mimeTypeParser';

// In-memory store to track expected file sizes for active upload sessions
// Key: upload_url, Value: total_expected_bytes
const uploadSessionRegistry = new Map<string, number>();

/**
 * Initiates a resumable upload with the Google AI API.
 * @param payload - The payload from the backend command.
 * @returns An object containing the Google-provided upload URL.
 */
export async function initiateResumableUpload(
  payload: CreateFilePayload,
): Promise<{ upload_url: string }> {
  // Map snake_case keys to camelCase if necessary
  const metadata = payload.metadata as any;
  const fileData = metadata.file || {};
  
  const sizeBytes = fileData.sizeBytes || fileData.size_bytes;
  let mimeType = fileData.mimeType || fileData.mime_type;
  const displayName = fileData.displayName || fileData.display_name || fileData.name || '';

  // Fix for "Unsupported MIME type: application/octet-stream"
  if (!mimeType || mimeType === 'application/octet-stream') {
    console.warn(`MIME type is '${mimeType}'. Attempting to infer from filename '${displayName}'...`);
    const inferredType = parseMimeType(displayName, 'application/octet-stream');
    
    if (inferredType !== 'application/octet-stream') {
        mimeType = inferredType;
        console.log(`Inferred MIME type: ${mimeType}`);
    } else {
        console.warn('Could not infer MIME type. Retaining application/octet-stream.');
    }
  }

  // Ensure URL points to the upload endpoint
  let endpoint = GOOGLE_API_URL;
  if (endpoint.includes('v1beta')) {
    endpoint = endpoint.replace('/v1beta', '/upload/v1beta');
  } else {
    endpoint = endpoint + '/upload/v1beta'; // Fallback
  }

  const response = await fetch(`${endpoint}/files`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Goog-Upload-Protocol': 'resumable',
      'X-Goog-Upload-Command': 'start',
      'X-Goog-Upload-Header-Content-Length': String(sizeBytes),
      'X-Goog-Upload-Header-Content-Type': mimeType,
    },
    body: JSON.stringify({ ...metadata, file: { ...fileData, mimeType } }),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ error: { message: response.statusText } }));
    throw new ApiError(`Failed to initiate upload: ${error.error?.message || response.statusText}`, response.status, error);
  }

  const uploadUrl = response.headers.get('x-goog-upload-url');
  if (!uploadUrl) {
    throw new ApiError('Could not get upload URL from Google API response.', 500, null);
  }

  // REGISTER SESSION SIZE
  // This allows us to catch truncation errors in uploadChunk later
  if (sizeBytes) {
    uploadSessionRegistry.set(uploadUrl, parseInt(String(sizeBytes), 10));
    console.log(`[GeminiUpload] Session started. Expected size: ${sizeBytes} bytes.`);
  }

  return { upload_url: uploadUrl };
}

export async function createMetadataOnlyFile(
  payload: CreateFilePayload,
): Promise<any> {
  const metadata = payload.metadata || {};
  const response = await fetch(`${GOOGLE_API_URL}/files`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(metadata),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ error: { message: response.statusText } }));
    throw new ApiError(`Failed to create metadata-only file: ${error.error?.message || response.statusText}`, response.status, error);
  }

  return await response.json();
}

/**
 * Uploads a file chunk to the Google AI API.
 * @param payload - The payload from the backend command.
 * @param backendUrl - The base URL of the backend, used if chunk_download_url is relative.
 * @returns The response from the Google API.
 */
export async function uploadChunk(payload: UpdateFilePayload, backendUrl?: string): Promise<any> {
  let chunkBlob: Blob;
  
  // 1. Acquire the chunk data (either from Base64 payload or via download)
  if (payload.data_base64) {
    try {
      // Sanitize base64: remove all whitespace which might confuse the decoder
      const cleanBase64 = payload.data_base64.replace(/\s/g, '');
      
      // OPTIMIZATION: Use native fetch to convert Base64 to Blob.
      // This avoids creating huge strings and looping in JS, which is critical for 50MB+ files.
      const res = await fetch(`data:application/octet-stream;base64,${cleanBase64}`);
      chunkBlob = await res.blob();
      
    } catch (e) {
      console.error("Failed to decode base64 chunk data", e);
      throw new Error("Failed to decode base64 chunk data provided in WebSocket message.");
    }
  } else if (payload.chunk_download_url) {
    let downloadUrl = payload.chunk_download_url;
    
    // Robustly handle relative URLs
    if (downloadUrl && backendUrl && !/^https?:\/\//i.test(downloadUrl)) {
      const base = backendUrl.replace(/\/+$/, '');
      const path = downloadUrl.replace(/^\/+/, '');
      downloadUrl = `${base}/${path}`;
    }

    try {
      console.debug(`Attempting to download chunk from: ${downloadUrl}`);
      const chunkResponse = await fetch(downloadUrl, {
          method: 'GET',
          headers: { 
              // Some backends require auth headers even for chunk downloads, 
              // but usually this is a public/temporary link or handled by cookies.
          },
          referrerPolicy: 'no-referrer',
          credentials: 'omit',
          mode: 'cors'
      });

      if (!chunkResponse.ok) {
        const error = await chunkResponse.json().catch(() => ({ error: { message: chunkResponse.statusText } }));
        throw new ApiError(`Failed to download chunk from backend: ${error.error?.message || chunkResponse.statusText}`, chunkResponse.status, error);
      }
      chunkBlob = await chunkResponse.blob();
    } catch (error) {
      console.error("Error downloading chunk from backend:", error);
      const msg = error instanceof Error ? error.message : String(error);
      throw new Error(`Failed to download chunk from backend (${downloadUrl}): ${msg}. Try using data_base64.`);
    }
  } else {
    throw new Error("No chunk data provided (missing both data_base64 and chunk_download_url in payload).");
  }

  // --- CRITICAL DATA INTEGRITY CHECKS ---
  
  // Check 1: Chunk Size Mismatch
  // This usually happens if the backend sends incorrect content_length header or truncates data
  if (chunkBlob.size !== payload.content_length) {
    const msg = `[GeminiUpload] Data integrity error: Blob size ${chunkBlob.size} != declared ${payload.content_length}.`;
    console.error(msg);
    throw new Error(`Upload data length mismatch. Backend sent ${payload.content_length} bytes description, but actual data was ${chunkBlob.size} bytes.`);
  }

  // Check 2: Truncated File Detection (The "500 Error" Prevention)
  // If backend says "finalize" (finish), we MUST verify we have uploaded the full file.
  const expectedTotalSize = uploadSessionRegistry.get(payload.upload_url);
  const currentUploadEnd = payload.upload_offset + payload.content_length;

  if (expectedTotalSize !== undefined && payload.upload_command.includes('finalize')) {
      // Allow for small off-by-one errors if any, but usually it must be exact.
      if (currentUploadEnd < expectedTotalSize) {
          const missing = expectedTotalSize - currentUploadEnd;
          const errMsg = `CRITICAL UPLOAD ERROR: Backend attempted to finalize upload, but the file is truncated! Expected ${expectedTotalSize} bytes, but only sent ${currentUploadEnd} bytes. Missing ${missing} bytes. This will cause a 500 error in Gemini.`;
          console.error(errMsg);
          throw new Error(errMsg); // Fail fast to warn user
      }
      // Cleanup registry if successful
      uploadSessionRegistry.delete(payload.upload_url);
  }

  // 2. Upload the chunk to Gemini
  try {
    const uploadResponse = await fetch(payload.upload_url, {
      method: 'POST',
      headers: {
        'X-Goog-Upload-Command': payload.upload_command,
        'X-Goog-Upload-Offset': String(payload.upload_offset),
        // Do NOT set Content-Length manually, browser does it
      },
      body: chunkBlob,
    });

    if (!uploadResponse.ok) {
      const error = await uploadResponse.json().catch(() => ({ error: { message: uploadResponse.statusText } }));
      throw new ApiError(`Chunk upload failed: ${error.error?.message || uploadResponse.statusText}`, uploadResponse.status, error);
    }

    const uploadStatus = uploadResponse.headers.get('x-goog-upload-status');
    const headers: Record<string, string> = {};
    uploadResponse.headers.forEach((value, key) => headers[key] = value);

    if (uploadStatus === 'final' || payload.upload_command.includes('finalize')) {
      const responseBody = await uploadResponse.json();
      return { status: uploadResponse.status, headers: headers, body: responseBody };
    }

    return { status: uploadResponse.status, headers: headers, body: '{}' };
  } catch (error) {
    console.error("Error uploading chunk to Gemini:", error);
    throw error;
  }
}

/**
 * Gets file metadata from the Google AI API.
 * @param payload - The payload from the backend command.
 * @returns The file metadata.
 */
export async function getFile(payload: GetFilePayload): Promise<any> {
  // Robustly clean the file name to prevent path issues
  // Replaces "files/files/abc" or "/files/abc" with just "abc"
  let cleanFileName = payload.file_name;
  // Remove all leading 'files/' occurrences
  while (cleanFileName.startsWith('files/') || cleanFileName.startsWith('/files/')) {
    cleanFileName = cleanFileName.replace(/^(\/?files\/)+/, '');
  }
  
  const response = await fetch(`${GOOGLE_API_URL}/files/${cleanFileName}`, {
      headers: { 'Content-Type': 'application/json' }
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ error: { message: response.statusText } }));
    throw new ApiError(`Failed to get file: ${error.error?.message || response.statusText}`, response.status, error);
  }
  return await response.json();
}

/**
 * Deletes a file from the Google AI API.
 * @param payload - The payload from the backend command.
 * @returns The response from the Google API.
 */
export async function deleteFile(payload: DeleteFilePayload): Promise<any> {
  let cleanFileName = payload.file_name;
  while (cleanFileName.startsWith('files/') || cleanFileName.startsWith('/files/')) {
    cleanFileName = cleanFileName.replace(/^(\/?files\/)+/, '');
  }
  
  const response = await fetch(`${GOOGLE_API_URL}/files/${cleanFileName}`, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' }
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ error: { message: response.statusText } }));
    throw new ApiError(`Failed to delete file: ${error.error?.message || response.statusText}`, response.status, error);
  }
  return await response.json();
}
