'use client';

import { BarChart3, Sparkles, ArrowLeft } from 'lucide-react';
import Link from 'next/link';

export default function AnalyticsPage() {
  return (
    <div className="max-w-4xl mx-auto py-12 px-4 text-center space-y-6">
      <div className="w-16 h-16 rounded-2xl bg-purple-500/10 border border-purple-500/30 flex items-center justify-center text-purple-400 mx-auto">
        <BarChart3 className="w-8 h-8" />
      </div>

      <div className="space-y-2">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-purple-500/30 bg-purple-500/10 text-purple-400 text-xs font-semibold">
          <Sparkles className="w-3.5 h-3.5" />
          Scheduled for Phase 7
        </div>
        <h1 className="text-3xl font-extrabold text-white tracking-tight">Call Analytics & Latency Telemetry</h1>
        <p className="text-slate-400 text-sm max-w-lg mx-auto">
          Comprehensive observability across call sessions: duration, turn-by-turn transcripts, stage-by-stage latencies (STT, LLM TTFT, TTS TTFA), and error analysis.
        </p>
      </div>

      <div className="p-6 rounded-2xl bg-slate-900/50 border border-slate-800 max-w-md mx-auto text-left text-xs text-slate-400 space-y-2">
        <p className="font-semibold text-slate-300">Phase 7 Capabilities:</p>
        <ul className="list-disc list-inside space-y-1 text-slate-400">
          <li>Call volume & duration tracking charts</li>
          <li>Latency histograms (VAD, STT, LLM, TTS)</li>
          <li>Turn-level audio duration & transcript inspector</li>
          <li>Automated 20 Q&A RAG evaluation harness</li>
        </ul>
      </div>

      <Link
        href="/dashboard/agents"
        className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 text-sm font-semibold transition"
      >
        <ArrowLeft className="w-4 h-4" />
        Back to Agents
      </Link>
    </div>
  );
}
