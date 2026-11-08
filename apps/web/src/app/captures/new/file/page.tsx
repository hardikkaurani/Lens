"use client";

import React from "react";
import Link from "next/link";
import { FileCaptureForm } from "@/components/FileCaptureForm";
import { ProtectedRoute } from "@/components/ProtectedRoute";

export default function NewFileCapturePage() {
  return (
    <ProtectedRoute>
      <div className="space-y-8 max-w-2xl mx-auto">
        {/* Header */}
        <div className="pb-6 border-b border-[#E5E7EB] flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-normal tracking-tight text-[#000000]">Upload PDF Document</h1>
            <p className="text-sm text-[#5B6472] mt-1.5 leading-normal">
              Upload a local PDF file to extract, chunk, and embed its text into your personal search index.
            </p>
          </div>
          <Link href="/captures" className="lens-button-secondary text-xs h-9 px-4">
            Cancel
          </Link>
        </div>

        {/* Navigation link to other capture modes */}
        <div className="flex items-center gap-2 text-xs text-[#5B6472]">
          <span>Capture mode:</span>
          <span className="font-semibold text-[#2075CC]">PDF Document</span>
          <span className="text-[#E5E7EB]">•</span>
          <Link href="/captures/new" className="text-[#115AA4] hover:text-[#2075CC] hover:underline">
            Switch to URL or Text capture
          </Link>
        </div>

        {/* Focused File Capture Form */}
        <FileCaptureForm />
      </div>
    </ProtectedRoute>
  );
}
