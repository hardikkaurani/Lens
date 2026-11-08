"use client";

import React, { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { apiClient, ApiClientError } from "@/lib/api-client";
import { ErrorMessage } from "@/components/ErrorMessage";
import { FileCaptureForm } from "@/components/FileCaptureForm";
import { ProtectedRoute } from "@/components/ProtectedRoute";

type CaptureTypeTab = "url" | "text" | "file";

export default function NewCapturePage() {
  const router = useRouter();
  const [activeTab, setActiveTab] = useState<CaptureTypeTab>("url");

  // Form fields
  const [url, setUrl] = useState("");
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");

  // States
  const [submitting, setSubmitting] = useState(false);
  const [clientError, setClientError] = useState<string | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);

  const validateUrlForm = (): boolean => {
    setClientError(null);
    const trimmedUrl = url.trim();
    if (!trimmedUrl) {
      setClientError("URL is required.");
      return false;
    }
    try {
      const parsed = new URL(trimmedUrl);
      if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
        setClientError("Only HTTP and HTTPS URLs are supported.");
        return false;
      }
    } catch {
      setClientError("Please enter a valid absolute URL (e.g. https://example.com/article).");
      return false;
    }

    if (title.length > 512) {
      setClientError("Title must be 512 characters or fewer.");
      return false;
    }

    return true;
  };

  const validateTextForm = (): boolean => {
    setClientError(null);
    const trimmedContent = content.trim();
    if (!trimmedContent) {
      setClientError("Text content is required and cannot be empty.");
      return false;
    }

    if (trimmedContent.length > 1_000_000) {
      setClientError("Content exceeds the maximum permitted size (1,000,000 characters).");
      return false;
    }

    if (title.length > 512) {
      setClientError("Title must be 512 characters or fewer.");
      return false;
    }

    return true;
  };

  const handleSubmit = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    setClientError(null);
    setApiError(null);

    const isValid = activeTab === "url" ? validateUrlForm() : validateTextForm();
    if (!isValid) return;

    setSubmitting(true);

    try {
      const payload =
        activeTab === "url"
          ? {
              source_type: "url" as const,
              original_url: url.trim(),
              title: title.trim() || undefined,
            }
          : {
              source_type: "text" as const,
              content: content.trim(),
              title: title.trim() || undefined,
            };

      const created = await apiClient.createCapture(payload);
      router.push(`/captures/${created.id}`);
    } catch (err: unknown) {
      setSubmitting(false);
      if (err instanceof ApiClientError) {
        setApiError(err.detail);
      } else {
        setApiError("Could not create capture. Please check your connection and try again.");
      }
    }
  };

  return (
    <ProtectedRoute>
      <div className="space-y-8 max-w-2xl mx-auto">
        {/* Header */}
        <div className="pb-6 border-b border-[#E5E7EB] flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-normal tracking-tight text-[#000000]">New Capture</h1>
            <p className="text-sm text-[#5B6472] mt-1.5 leading-normal">
              Save a web article or record a text note into your knowledge base.
            </p>
          </div>
          <Link href="/captures" className="lens-button-secondary text-xs h-9 px-4">
            Cancel
          </Link>
        </div>

        {/* Tabs: Editorial line styling */}
        <div className="flex border-b border-[#E5E7EB] gap-4">
          <button
            type="button"
            onClick={() => {
              setActiveTab("url");
              setClientError(null);
              setApiError(null);
            }}
            className={`pb-3 px-2 text-sm font-medium transition-colors flex items-center gap-2 border-b-2 -mb-[1px] cursor-pointer ${
              activeTab === "url"
                ? "border-[#2075CC] text-[#2075CC] font-semibold"
                : "border-transparent text-[#5B6472] hover:text-[#000000]"
            }`}
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
            </svg>
            <span>Web URL</span>
          </button>
          <button
            type="button"
            onClick={() => {
              setActiveTab("text");
              setClientError(null);
              setApiError(null);
            }}
            className={`pb-3 px-2 text-sm font-medium transition-colors flex items-center gap-2 border-b-2 -mb-[1px] cursor-pointer ${
              activeTab === "text"
                ? "border-[#2075CC] text-[#2075CC] font-semibold"
                : "border-transparent text-[#5B6472] hover:text-[#000000]"
            }`}
            data-testid="tab-text"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            <span>Text / Note</span>
          </button>
          <button
            type="button"
            onClick={() => {
              setActiveTab("file");
              setClientError(null);
              setApiError(null);
            }}
            className={`pb-3 px-2 text-sm font-medium transition-colors flex items-center gap-2 border-b-2 -mb-[1px] cursor-pointer ${
              activeTab === "file"
                ? "border-[#2075CC] text-[#2075CC] font-semibold"
                : "border-transparent text-[#5B6472] hover:text-[#000000]"
            }`}
            data-testid="tab-file"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z" />
            </svg>
            <span>PDF Document</span>
          </button>
        </div>

        {activeTab === "file" ? (
          <FileCaptureForm />
        ) : (
          <div className="space-y-6">
            {/* Error Banners */}
            {clientError && (
              <div role="alert" className="p-3.5 rounded-[4px] bg-[#FFFBEB] border border-[#FDE68A] text-[#B45309] text-xs">
                {clientError}
              </div>
            )}
            {apiError && <ErrorMessage message={apiError} onRetry={handleSubmit} />}

            {/* Form Card */}
            <form onSubmit={handleSubmit} className="lens-card p-8 space-y-6 bg-white border border-[#E5E7EB] rounded-[8px]" noValidate>
              {activeTab === "url" ? (
                <>
                  <div className="space-y-2">
                    <label htmlFor="url-input" className="block text-xs font-medium uppercase tracking-wider text-[#5B6472]">
                      Webpage URL <span className="text-[#C62828]">*</span>
                    </label>
                    <input
                      id="url-input"
                      type="url"
                      value={url}
                      onChange={(e) => setUrl(e.target.value)}
                      placeholder="https://example.com/article"
                      className="lens-input"
                      required
                      autoFocus
                      disabled={submitting}
                    />
                    <p className="text-[11px] text-[#5B6472]">
                      LENS will asynchronously fetch, parse readable text, chunk, and embed this page.
                    </p>
                  </div>

                  <div className="space-y-2">
                    <label htmlFor="url-title-input" className="block text-xs font-medium uppercase tracking-wider text-[#5B6472]">
                      Optional Title
                    </label>
                    <input
                      id="url-title-input"
                      type="text"
                      value={title}
                      onChange={(e) => setTitle(e.target.value)}
                      placeholder="Leave blank to extract automatically from the webpage"
                      className="lens-input"
                      maxLength={512}
                      disabled={submitting}
                    />
                  </div>
                </>
              ) : (
                <>
                  <div className="space-y-2">
                    <label htmlFor="text-title-input" className="block text-xs font-medium uppercase tracking-wider text-[#5B6472]">
                      Title <span className="text-[#5B6472]">(Optional)</span>
                    </label>
                    <input
                      id="text-title-input"
                      type="text"
                      value={title}
                      onChange={(e) => setTitle(e.target.value)}
                      placeholder="E.g. System Design Notes"
                      className="lens-input"
                      maxLength={512}
                      autoFocus
                      disabled={submitting}
                    />
                  </div>

                  <div className="space-y-2">
                    <label htmlFor="text-content-input" className="block text-xs font-medium uppercase tracking-wider text-[#5B6472]">
                      Content <span className="text-[#C62828]">*</span>
                    </label>
                    <textarea
                      id="text-content-input"
                      rows={8}
                      value={content}
                      onChange={(e) => setContent(e.target.value)}
                      placeholder="Paste or write thoughts, code snippets, documentation notes..."
                      className="lens-input font-mono text-xs leading-relaxed"
                      required
                      disabled={submitting}
                    />
                    <div className="flex justify-between text-[11px] text-[#5B6472]">
                      <span>Markdown & plain text supported.</span>
                      <span>{content.length.toLocaleString()} characters</span>
                    </div>
                  </div>
                </>
              )}

              <div className="pt-4 border-t border-[#E5E7EB] flex items-center justify-end gap-3">
                <Link href="/captures" className="lens-button-secondary text-xs h-10 px-5">
                  Cancel
                </Link>
                <button
                  type="submit"
                  disabled={submitting}
                  className="lens-button-primary h-10 px-6 text-xs"
                  data-testid="submit-capture-btn"
                >
                  {submitting ? (
                    <>
                      <svg className="w-4 h-4 animate-spin text-white" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                      </svg>
                      <span>Saving capture...</span>
                    </>
                  ) : (
                    <span>Create Capture</span>
                  )}
                </button>
              </div>
            </form>
          </div>
        )}
      </div>
    </ProtectedRoute>
  );
}
