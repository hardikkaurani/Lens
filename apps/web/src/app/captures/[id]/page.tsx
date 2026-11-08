"use client";

import React, { use } from "react";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { CaptureDetailContent } from "@/components/CaptureDetailContent";

interface PageProps {
  params: Promise<{ id: string }>;
}

export default function CaptureDetailPage({ params }: PageProps) {
  const { id } = use(params);
  return (
    <ProtectedRoute>
      <CaptureDetailContent id={id} />
    </ProtectedRoute>
  );
}
