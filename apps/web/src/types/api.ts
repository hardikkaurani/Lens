/**
 * Domain types matching the LENS FastAPI backend contract.
 * Backend schemas:
 * - app/captures/schemas.py (CaptureResponse, CaptureDetailResponse, CaptureListResponse, CaptureCreate)
 * - app/search/schemas.py (SearchResponse, SearchResultCapture, SearchResultChunk)
 */

export type SourceType = "url" | "text" | "image" | "pdf" | "file" | "github";

export type ProcessingStatus = "pending" | "processing" | "completed" | "failed";

export interface Capture {
  id: string;
  source_type: SourceType;
  processing_status: ProcessingStatus;
  processing_error: string | null;
  processed_at: string | null;
  title: string | null;
  original_url: string | null;
  content: string | null;
  mime_type: string | null;
  source_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface ContentChunk {
  id: string;
  chunk_index: number;
  content: string;
  created_at: string;
}

export interface CaptureDetail extends Capture {
  metadata?: Record<string, unknown> | null;
  chunks?: ContentChunk[];
}

export interface PdfSourceMetadata {
  bucket?: string;
  object_key?: string;
  original_filename?: string;
  byte_size?: number;
  sha256?: string;
  mime_type?: string;
}

export interface UploadProgress {
  loaded: number;
  total: number;
  percentage: number;
}

export interface UploadCaptureOptions {
  title?: string;
  onProgress?: (progress: UploadProgress) => void;
  signal?: AbortSignal;
  timeoutMs?: number;
}

export function isCaptureDetail(data: unknown): data is CaptureDetail {
  if (!data || typeof data !== "object") return false;
  const c = data as Record<string, unknown>;
  return (
    typeof c.id === "string" &&
    typeof c.source_type === "string" &&
    typeof c.processing_status === "string"
  );
}

export interface CaptureListResponse {
  items: Capture[];
  limit: number;
  offset: number;
  total: number;
}

export interface CaptureCreatePayload {
  source_type: "url" | "text";
  original_url?: string;
  title?: string;
  content?: string;
  mime_type?: string;
  source_id?: string;
  metadata?: Record<string, unknown>;
}

export interface SearchResultChunk {
  chunk_id: string;
  chunk_index: number;
  content_excerpt: string;
  score: number;
  lexical_score: number | null;
  semantic_score: number | null;
}

export interface SearchResultCapture {
  capture_id: string;
  title: string | null;
  original_url: string | null;
  source_type: string;
  best_score: number;
  best_lexical_score: number | null;
  best_semantic_score: number | null;
  matching_chunks: SearchResultChunk[];
}

export interface SearchResponse {
  query: string;
  total: number;
  limit: number;
  degraded: boolean;
  results: SearchResultCapture[];
}

export interface HealthResponse {
  status: string;
  api?: string;
  database?: string;
  redis?: string;
}
