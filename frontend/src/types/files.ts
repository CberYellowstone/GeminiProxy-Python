/**
 * Base interface for all file-related commands.
 */
interface BaseFileCommand<T extends string, P> {
  id: string;
  type: T;
  payload: P;
}

/**
 * Command to create a file.
 * Corresponds to the 'createFile' or 'initiate_resumable_upload' command from the backend.
 */
export interface CreateFilePayload {
  metadata: {
    file: {
      displayName: string;
      mimeType: string;
      sizeBytes: string;
    };
  };
}
export type CreateFileCommand = BaseFileCommand<'createFile' | 'initiate_resumable_upload', CreateFilePayload>;

/**
 * Command to upload a chunk of a file.
 * Corresponds to the 'updateFile' or 'upload_chunk' command from the backend.
 */
export interface UpdateFilePayload {
  upload_url: string;
  chunk_download_url?: string;
  data_base64?: string;
  upload_command: "upload" | "upload, finalize";
  upload_offset: number;
  content_length: number;
}
export type UpdateFileCommand = BaseFileCommand<'updateFile' | 'upload_chunk' | 'upload_file_chunk', UpdateFilePayload>;

/**
 * Command to get the metadata of a file.
 * Corresponds to the 'getFile' or 'get_file' command from the backend.
 */
export interface GetFilePayload {
  file_name: string;
}
export type GetFileCommand = BaseFileCommand<'getFile' | 'get_file', GetFilePayload>;

/**
 * Command to delete a file.
 * Corresponds to the 'deleteFile' or 'delete_file' command from the backend.
 */
export interface DeleteFilePayload {
  file_name: string;
}
export type DeleteFileCommand = BaseFileCommand<'deleteFile' | 'delete_file', DeleteFilePayload>;

/**
 * A union type for all possible file-related commands.
 */
export type FileCommand = 
  | CreateFileCommand
  | UpdateFileCommand
  | GetFileCommand
  | DeleteFileCommand;