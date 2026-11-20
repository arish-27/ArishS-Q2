'use client';

import { Wrench, Sparkles, ArrowLeft } from 'lucide-react';
import Link from 'next/link';

export default function ToolsPage() {
  return (
    <div className="max-w-4xl mx-auto py-12 px-4 text-center space-y-6">
      <div className="w-16 h-16 rounded-2xl bg-amber-500/10 border border-amber-500/30 flex items-center justify-center text-amber-400 mx-auto">
        <Wrench className="w-8 h-8" />
      </div>

      <div className="space-y-2">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-amber-500/30 bg-amber-500/10 text-amber-400 text-xs font-semibold">
          <Sparkles className="w-3.5 h-3.5" />
          Scheduled for Phase 5
        </div>
        <h1 className="text-3xl font-extrabold text-white tracking-tight">Function Calling Tools & Webhooks</h1>
        <p className="text-slate-400 text-sm max-w-lg mx-auto">
          Equip voice agents with external tools, HTTP webhooks, and function schemas. Includes sensitive action confirmation before execution.
        </p>
      </div>

      <div className="p-6 rounded-2xl bg-slate-900/50 border border-slate-800 max-w-md mx-auto text-left text-xs text-slate-400 space-y-2">
        <p className="font-semibold text-slate-300">Phase 5 Capabilities:</p>
        <ul className="list-disc list-inside space-y-1 text-slate-400">
          <li>JSON Schema tool definition editor</li>
          <li>Built-in tools: Weather, Appointment Booking, Email Mock</li>
          <li>Outbound HTTP Webhook connector with auth headers</li>
          <li>Sensitive tool verbal & UI confirmation gate</li>
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
