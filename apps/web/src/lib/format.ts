import type { ProcessingStatus, SourceType } from "@/types/api";

/**
 * Returns user-facing status labels adhering to the Stage 8 UX specification.
 */
export function formatProcessingStatus(status: ProcessingStatus): string {
  switch (status) {
    case "pending":
      return "Waiting to process";
    case "processing":
      return "Processing";
    case "completed":
      return "Ready";
    case "failed":
      return "Processing failed";
    default:
      return status;
  }
}

/**
 * Returns human-readable label for capture source type.
 */
export function formatSourceType(sourceType: SourceType | string): string {
  switch (sourceType) {
    case "url":
      return "Web Page";
    case "text":
      return "Note / Text";
    case "github":
      return "GitHub";
    case "pull_request":
      return "Pull Request";
    case "issue":
      return "Issue";
    case "commit":
      return "Commit";
    case "review":
      return "Review";
    case "pdf":
      return "PDF Document";
    case "image":
      return "Image";
    case "file":
      return "File";
    default:
      return sourceType.toUpperCase();
  }
}

/**
 * Format ISO datetime string to localized date and time.
 */
export function formatDate(isoString: string | null | undefined): string {
  if (!isoString) return "N/A";
  try {
    const d = new Date(isoString);
    if (isNaN(d.getTime())) return isoString;
    return d.toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return isoString;
  }
}

/**
 * Format score as percentage with 1 decimal.
 */
export function formatScorePercentage(score: number | null | undefined): string {
  if (score === null || score === undefined || isNaN(score)) {
    return "N/A";
  }
  return `${(Math.max(0, Math.min(1, score)) * 100).toFixed(0)}%`;
}

/**
 * Format raw byte size to human-readable string (e.g. 512 B, 1.4 KB, 3.2 MB).
 */
export function formatFileSize(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined || isNaN(bytes) || bytes < 0) {
    return "N/A";
  }
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  const normalizedIndex = Math.min(i, sizes.length - 1);
  return `${(bytes / Math.pow(k, normalizedIndex)).toFixed(normalizedIndex === 0 ? 0 : 1)} ${sizes[normalizedIndex]}`;
}
