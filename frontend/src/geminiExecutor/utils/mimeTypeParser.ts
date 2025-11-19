
export function parseMimeType(filename: string, defaultType: string = 'application/octet-stream'): string {
  if (!filename) return defaultType;
  
  const ext = filename.split('.').pop()?.toLowerCase();
  switch (ext) {
    // Text / Code
    case 'txt': return 'text/plain';
    case 'md': return 'text/markdown';
    case 'html': return 'text/html';
    case 'js': return 'text/javascript';
    case 'ts': return 'text/javascript';
    case 'py': return 'text/x-python';
    case 'java': return 'text/x-java';
    case 'c': return 'text/x-c';
    case 'cpp': return 'text/x-c++';
    case 'css': return 'text/css';
    case 'json': return 'application/json';
    case 'csv': return 'text/csv';
    case 'xml': return 'text/xml';
    case 'sh': return 'text/x-shellscript';
    
    // Images
    case 'png': return 'image/png';
    case 'jpg': case 'jpeg': return 'image/jpeg';
    case 'webp': return 'image/webp';
    case 'gif': return 'image/gif';
    case 'bmp': return 'image/bmp';
    case 'tiff': return 'image/tiff';

    // Documents
    case 'pdf': return 'application/pdf';
    case 'rtf': return 'text/rtf';

    // Audio
    case 'mp3': return 'audio/mp3';
    case 'wav': return 'audio/wav';
    case 'aac': return 'audio/aac';
    case 'ogg': return 'audio/ogg';
    case 'flac': return 'audio/flac';

    // Video
    case 'mp4': return 'video/mp4';
    case 'mpeg': return 'video/mpeg';
    case 'mov': return 'video/mov';
    case 'avi': return 'video/avi';
    case 'webm': return 'video/webm';
    case 'mkv': return 'video/x-matroska';

    default: return defaultType;
  }
}
