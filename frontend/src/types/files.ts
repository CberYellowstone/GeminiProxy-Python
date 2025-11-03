/**
 * Base interface for all file-related commands.
 */
interface BaseFileCommand<T extends string, P> {
  id: string;
  type: T;
  payload: P;
}

/**
 * Command to initiate a resumable upload.
 * Corresponds to the 'initiate_resumable_upload' command from the backend.
 */
export interface InitiateResumableUploadPayload {
  metadata: {
    file: {
      displayName: string;
      mimeType: string;
      sizeBytes: string;
    };
  };
}
export type InitiateResumableUploadCommand = BaseFileCommand<'initiate_resumable_upload', InitiateResumableUploadPayload>;

/**
 * Command to upload a chunk of a file.
 * Corresponds to the 'upload_chunk' command from the backend.
 */
export interface UploadChunkPayload {
  upload_url: string;
  chunk_download_url: string;
  upload_command: "upload" | "upload, finalize";
  upload_offset: number;
  content_length: number;
}
export type UploadChunkCommand = BaseFileCommand<'upload_chunk', UploadChunkPayload>;

/**
 * Command to get the metadata of a file.
 * Corresponds to the 'get_file' command from the backend.
 */
export interface GetFilePayload {
  file_name: string;
}
export type GetFileCommand = BaseFileCommand<'get_file', GetFilePayload>;

/**
 * Command to delete a file.
 * Corresponds to the 'delete_file' command from the backend.
 */
export interface DeleteFilePayload {
  file_name: string;
}
export type DeleteFileCommand = BaseFileCommand<'delete_file', DeleteFilePayload>;

/**
 * A union type for all possible file-related commands.
 */
export type FileCommand = 
  | InitiateResumableUploadCommand
  | UploadChunkCommand
  | GetFileCommand
  | DeleteFileCommand;