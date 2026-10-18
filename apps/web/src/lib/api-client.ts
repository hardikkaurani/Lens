import {
  isCaptureDetail,
  type CaptureCreatePayload,
  type CaptureDetail,
  type CaptureListResponse,
  type GitHubActivityListResponse,
  type GitHubActivityStatusResponse,
  type GitHubActivitySyncResponse,
  type GitHubConnectionStatus,
  type GitHubDisconnectResponse,
  type GitHubRepoListResponse,
  type GitHubRepoSyncResponse,
  type GitHubRepository,
  type HealthResponse,
  type SearchResponse,
  type UploadCaptureOptions,
} from "@/types/api";

/**
 * Standard API error class encapsulating HTTP status and user-safe diagnostic details.
 */
export class ApiClientError extends Error {
  readonly status: number;
  readonly detail: string;
  readonly isNetworkError: boolean;
  readonly isTimeout: boolean;

  constructor(
    status: number,
    detail: string,
    options?: { isNetworkError?: boolean; isTimeout?: boolean }
  ) {
    super(detail);
    this.name = "ApiClientError";
    this.status = status;
    this.detail = detail;
    this.isNetworkError = options?.isNetworkError ?? false;
    this.isTimeout = options?.isTimeout ?? false;
  }
}

/**
 * Resolve the API base URL from client-side public environment variable,
 * falling back safely to local development port 8000.
 */
export function getApiBaseUrl(): string {
  const envUrl = process.env.NEXT_PUBLIC_API_BASE_URL;
  if (envUrl && envUrl.trim()) {
    return envUrl.trim().replace(/\/+$/, "");
  }
  return "http://localhost:8000";
}

/**
 * Extract a user-safe message from an API error response body.
 * Prevents leaking raw Python tracebacks, credentials, or internal details.
 */
function extractSafeErrorMessage(status: number, data: unknown): string {
  if (data && typeof data === "object") {
    const errorObj = data as Record<string, unknown>;
    if (typeof errorObj.detail === "string" && errorObj.detail.trim()) {
      // Don't leak raw internal python errors or DB tracebacks
      const detail = errorObj.detail.trim();
      if (!detail.includes("Traceback") && !detail.includes("postgresql://")) {
        return detail;
      }
    } else if (Array.isArray(errorObj.detail)) {
      // Pydantic 422 validation errors array
      const first = errorObj.detail[0] as Record<string, unknown> | undefined;
      if (first && typeof first.msg === "string") {
        const field = Array.isArray(first.loc) ? first.loc.slice(-1)[0] : "input";
        return `Validation failed on ${field}: ${first.msg}`;
      }
    }
  }

  switch (status) {
    case 400:
      return "The request was invalid. Please check your input.";
    case 404:
      return "The requested capture or resource was not found.";
    case 422:
      return "Validation failed. Please verify that all required fields are correct.";
    case 500:
      return "A server error occurred. Please try again later.";
    case 503:
      return "The service is temporarily unavailable. Please try again in a few moments.";
    default:
      return `Request failed with status code ${status}.`;
  }
}

interface RequestOptions extends RequestInit {
  timeoutMs?: number;
}

/**
 * Core centralized request dispatcher with timeout, abort handling, and response parsing.
 */
async function request<T>(endpoint: string, options: RequestOptions = {}): Promise<T> {
  const baseUrl = getApiBaseUrl();
  const url = `${baseUrl}${endpoint.startsWith("/") ? endpoint : `/${endpoint}`}`;
  const timeoutMs = options.timeoutMs ?? 15000;

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  // Link caller signal if provided
  if (options.signal) {
    options.signal.addEventListener("abort", () => controller.abort());
  }

  try {
    const res = await fetch(url, {
      ...options,
      signal: controller.signal,
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        ...(options.headers || {}),
      },
    });

    clearTimeout(timeoutId);

    if (!res.ok) {
      let errorData: unknown = null;
      try {
        errorData = await res.json();
      } catch {
        // Not a JSON response
      }
      const message = extractSafeErrorMessage(res.status, errorData);
      throw new ApiClientError(res.status, message);
    }

    return (await res.json()) as T;
  } catch (err: unknown) {
    clearTimeout(timeoutId);

    if (err instanceof ApiClientError) {
      throw err;
    }

    if (err instanceof Error) {
      if (err.name === "AbortError") {
        throw new ApiClientError(
          0,
          "The request was aborted or timed out. Please try again.",
          { isTimeout: true }
        );
      }
      return Promise.reject(
        new ApiClientError(
          0,
          "Unable to connect to the LENS API service. Ensure the backend is running.",
          { isNetworkError: true }
        )
      );
    }

    throw new ApiClientError(0, "An unexpected error occurred while communicating with the server.");
  }
}

/**
 * LENS API Client functions
 */
export const apiClient = {
  /**
   * Fetch paginated captures ordered newest first.
   */
  async listCaptures(params: { limit?: number; offset?: number; signal?: AbortSignal } = {}): Promise<CaptureListResponse> {
    const limit = params.limit ?? 20;
    const offset = params.offset ?? 0;
    return request<CaptureListResponse>(`/captures?limit=${limit}&offset=${offset}`, {
      method: "GET",
      signal: params.signal,
    });
  },

  /**
   * Retrieve a single capture detail by UUID.
   */
  async getCapture(id: string, params: { signal?: AbortSignal } = {}): Promise<CaptureDetail> {
    const cleanId = encodeURIComponent(id.trim());
    return request<CaptureDetail>(`/captures/${cleanId}`, {
      method: "GET",
      signal: params.signal,
    });
  },

  /**
   * Ingest a new text or URL capture.
   */
  async createCapture(payload: CaptureCreatePayload, params: { signal?: AbortSignal } = {}): Promise<CaptureDetail> {
    return request<CaptureDetail>("/captures", {
      method: "POST",
      body: JSON.stringify(payload),
      signal: params.signal,
    });
  },

  /**
   * Upload a binary PDF capture with real upload progress tracking via XMLHttpRequest.
   * Sends multipart/form-data directly to POST /captures/upload.
   * Does NOT automatically retry to prevent duplicate captures.
   */
  async uploadCapture(
    file: File,
    options: UploadCaptureOptions = {}
  ): Promise<CaptureDetail> {
    const baseUrl = getApiBaseUrl();
    const url = `${baseUrl}/captures/upload`;
    const timeoutMs = options.timeoutMs ?? 60000;

    const formData = new FormData();
    formData.append("file", file, file.name);
    if (options.title && options.title.trim()) {
      formData.append("title", options.title.trim());
    }

    return new Promise<CaptureDetail>((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", url);
      xhr.timeout = timeoutMs;
      xhr.responseType = "json";

      // Report upload progress if handler provided
      if (xhr.upload && options.onProgress) {
        xhr.upload.onprogress = (event) => {
          if (event.lengthComputable && event.total > 0) {
            const percentage = Math.min(
              100,
              Math.max(0, Math.round((event.loaded / event.total) * 100))
            );
            options.onProgress?.({
              loaded: event.loaded,
              total: event.total,
              percentage,
            });
          }
        };
      }

      // Handle caller cancellation
      const onAbort = () => {
        xhr.abort();
      };
      if (options.signal) {
        if (options.signal.aborted) {
          return reject(
            new ApiClientError(0, "The request was aborted.", { isTimeout: false })
          );
        }
        options.signal.addEventListener("abort", onAbort, { once: true });
      }

      const cleanup = () => {
        if (options.signal) {
          options.signal.removeEventListener("abort", onAbort);
        }
      };

      xhr.onload = () => {
        cleanup();
        const status = xhr.status;
        let data = xhr.response;
        if (typeof data === "string") {
          try {
            data = JSON.parse(data);
          } catch {
            // Keep raw or null
          }
        }

        if (status >= 200 && status < 300) {
          if (isCaptureDetail(data)) {
            resolve(data);
          } else {
            reject(
              new ApiClientError(
                status,
                "Received malformed capture response from server."
              )
            );
          }
        } else {
          const message = extractSafeErrorMessage(status, data);
          reject(new ApiClientError(status, message));
        }
      };

      xhr.onerror = () => {
        cleanup();
        reject(
          new ApiClientError(
            0,
            "Unable to connect to the LENS API service. Ensure the backend is running.",
            { isNetworkError: true }
          )
        );
      };

      xhr.ontimeout = () => {
        cleanup();
        reject(
          new ApiClientError(
            0,
            "File upload timed out. The file may be too large or the network is slow.",
            { isTimeout: true }
          )
        );
      };

      xhr.onabort = () => {
        cleanup();
        reject(
          new ApiClientError(0, "The upload was cancelled or aborted.", {
            isTimeout: false,
          })
        );
      };

      // Browser automatically sets multipart boundary
      xhr.send(formData);
    });
  },

  /**
   * Perform hybrid search across captured content and titles.
   */
  async search(params: { q: string; limit?: number; signal?: AbortSignal }): Promise<SearchResponse> {
    const query = encodeURIComponent(params.q.trim());
    const limit = params.limit ?? 10;
    return request<SearchResponse>(`/search?q=${query}&limit=${limit}`, {
      method: "GET",
      signal: params.signal,
    });
  },

  /**
   * Check system health and service status.
   */
  async getHealth(params: { signal?: AbortSignal } = {}): Promise<HealthResponse> {
    return request<HealthResponse>("/health", {
      method: "GET",
      signal: params.signal,
    });
  },

  /**
   * Retrieve connection status for GitHub OAuth integration.
   */
  async getGitHubStatus(params: { signal?: AbortSignal } = {}): Promise<GitHubConnectionStatus> {
    return request<GitHubConnectionStatus>("/integrations/github", {
      method: "GET",
      signal: params.signal,
    });
  },

  /**
   * Disconnect and remove stored GitHub integration credentials.
   */
  async disconnectGitHub(params: { signal?: AbortSignal } = {}): Promise<GitHubDisconnectResponse> {
    return request<GitHubDisconnectResponse>("/integrations/github", {
      method: "DELETE",
      signal: params.signal,
    });
  },

  /**
   * Return server-side OAuth connect URL for initiating GitHub authorization.
   */
  getGitHubConnectUrl(): string {
    return `${getApiBaseUrl()}/integrations/github/connect`;
  },

  /**
   * Retrieve discovered GitHub repositories for the connected account.
   */
  async getGitHubRepositories(params: {
    limit?: number;
    offset?: number;
    search?: string;
    signal?: AbortSignal;
  } = {}): Promise<GitHubRepoListResponse> {
    const query = new URLSearchParams();
    if (params.limit !== undefined) query.set("limit", String(params.limit));
    if (params.offset !== undefined) query.set("offset", String(params.offset));
    if (params.search && params.search.trim()) query.set("search", params.search.trim());

    const queryString = query.toString();
    const endpoint = `/integrations/github/repositories${queryString ? `?${queryString}` : ""}`;
    return request<GitHubRepoListResponse>(endpoint, {
      method: "GET",
      signal: params.signal,
    });
  },

  /**
   * Trigger discovery and synchronization of GitHub repositories.
   */
  async syncGitHubRepositories(params: { signal?: AbortSignal } = {}): Promise<GitHubRepoSyncResponse> {
    return request<GitHubRepoSyncResponse>("/integrations/github/repositories/sync", {
      method: "POST",
      signal: params.signal,
    });
  },

  /**
   * Update repository selection preference for future indexing.
   */
  async updateGitHubRepositorySelection(
    repositoryId: string,
    isSelected: boolean,
    params: { signal?: AbortSignal } = {}
  ): Promise<GitHubRepository> {
    return request<GitHubRepository>(`/integrations/github/repositories/${encodeURIComponent(repositoryId)}/selection`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_selected: isSelected }),
      signal: params.signal,
    });
  },

  /**
   * Trigger activity ingestion for selected repositories.
   */
  async syncGitHubActivities(params: {
    repository_ids?: string[];
    async_sync?: boolean;
    signal?: AbortSignal;
  } = {}): Promise<GitHubActivitySyncResponse> {
    const query = new URLSearchParams();
    if (params.async_sync) query.set("async_sync", "true");
    const qs = query.toString();
    const endpoint = `/integrations/github/activities/sync${qs ? `?${qs}` : ""}`;
    const payload = params.repository_ids ? { repository_ids: params.repository_ids } : undefined;

    return request<GitHubActivitySyncResponse>(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: payload ? JSON.stringify(payload) : undefined,
      signal: params.signal,
    });
  },

  /**
   * Retrieve ingested GitHub activities with optional filtering and pagination.
   */
  async getGitHubActivities(params: {
    repository_id?: string;
    activity_type?: string;
    limit?: number;
    offset?: number;
    signal?: AbortSignal;
  } = {}): Promise<GitHubActivityListResponse> {
    const query = new URLSearchParams();
    if (params.repository_id) query.set("repository_id", params.repository_id);
    if (params.activity_type) query.set("activity_type", params.activity_type);
    if (params.limit !== undefined) query.set("limit", String(params.limit));
    if (params.offset !== undefined) query.set("offset", String(params.offset));

    const qs = query.toString();
    const endpoint = `/integrations/github/activities${qs ? `?${qs}` : ""}`;
    return request<GitHubActivityListResponse>(endpoint, {
      method: "GET",
      signal: params.signal,
    });
  },

  /**
   * Retrieve aggregate activity sync state across selected repositories.
   */
  async getGitHubActivityStatus(params: { signal?: AbortSignal } = {}): Promise<GitHubActivityStatusResponse> {
    return request<GitHubActivityStatusResponse>("/integrations/github/activities/status", {
      method: "GET",
      signal: params.signal,
    });
  },
};

