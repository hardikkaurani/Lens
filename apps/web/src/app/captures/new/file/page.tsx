"use client";

import React from "react";
import Link from "next/link";
import { FileCaptureForm } from "@/components/FileCaptureForm";

export default function NewFileCapturePage() {
  return (
    <div className="space-y-6 max-w-2xl">
      {/* Header */}
      <div className="pb-4 border-b border-white/10 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white">Upload PDF Document</h1>
          <p className="text-sm text-slate-400 mt-1">
            Upload a local PDF file to extract, chunk, and embed its text into your personal search index.
          </p>
        </div>
        <Link href="/captures" className="lens-button-secondary text-xs">
          Cancel
        </Link>
      </div>

      {/* Navigation link to other capture modes */}
      <div className="flex items-center gap-2 text-xs text-slate-400">
        <span>Capture mode:</span>
        <span className="font-semibold text-indigo-300">PDF Document</span>
        <span className="text-slate-600">•</span>
        <Link href="/captures/new" className="text-slate-400 hover:text-white underline">
          Switch to URL or Text capture
        </Link>
      </div>

      {/* Focused File Capture Form */}
      <FileCaptureForm />
    </div>
  );
}
