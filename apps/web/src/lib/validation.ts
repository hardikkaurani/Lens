/**
 * Client-side file validation utilities for LENS Web Workspace.
 *
 * NOTE: Client validation serves as a user experience optimization
 * to catch mistakes early. The server-side API remains authoritative.
 */

// Maximum file upload limit matching backend Settings.MAX_UPLOAD_SIZE_BYTES (10 MB)
export const MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024;
export const MAX_FILE_SIZE_MB = 10;
export const ACCEPTED_FILE_TYPES = ["application/pdf"];
export const ACCEPTED_EXTENSIONS = [".pdf"];

export interface FileValidationResult {
  valid: boolean;
  error: string | null;
}

/**
 * Validates a selected file before uploading to POST /captures/upload.
 * Checks for presence, non-zero byte size, maximum size limit, extension, and MIME type.
 */
export function validatePdfFile(file: File | null | undefined): FileValidationResult {
  if (!file) {
    return { valid: false, error: "Please select a PDF file to upload." };
  }

  // 1. Reject empty files
  if (file.size === 0) {
    return {
      valid: false,
      error: "The selected file is empty (0 bytes). Please select a valid PDF document.",
    };
  }

  // 2. Reject files exceeding max size limit
  if (file.size > MAX_FILE_SIZE_BYTES) {
    const sizeMb = (file.size / (1024 * 1024)).toFixed(1);
    return {
      valid: false,
      error: `File size (${sizeMb} MB) exceeds maximum allowed limit of ${MAX_FILE_SIZE_MB} MB.`,
    };
  }

  // 3. Validate file extension
  const fileName = (file.name || "").toLowerCase().trim();
  if (!fileName.endsWith(".pdf")) {
    return {
      valid: false,
      error: "Only PDF documents (.pdf) are supported in this stage.",
    };
  }

  // 4. Validate MIME type if reported by browser
  if (file.type && file.type.trim()) {
    const mime = file.type.toLowerCase().trim();
    if (mime !== "application/pdf") {
      return {
        valid: false,
        error: "Unsupported file type. Only PDF documents (application/pdf) are supported in this stage.",
      };
    }
  }

  return { valid: true, error: null };
}
