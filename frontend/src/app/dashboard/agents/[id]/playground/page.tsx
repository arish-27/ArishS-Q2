'use client';

import { useParams } from 'next/navigation';
import Link from 'next/link';
import { Mic, Sparkles, MessageSquare, ArrowLeft } from 'lucide-react';

export default function PlaygroundComingSoonPage() {
  const params = useParams();
  const agentId = params.id as string;

  return (
    <div className="max-w-4xl mx-auto py-12 px-4 text-center space-y-6">
      <div className="w-16 h-16 rounded-2xl bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center text-emerald-400 mx-auto">
        <Mic className="w-8 h-8" />
      </div>

      <div className="space-y-2">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-emerald-500/30 bg-emerald-500/10 text-emerald-400 text-xs font-semibold">
          <Sparkles className="w-3.5 h-3.5" />
          Full Voice Duplex in Phase 3
        </div>
        <h1 className="text-3xl font-extrabold text-white tracking-tight">Real-Time Voice Playground</h1>
        <p className="text-slate-400 text-sm max-w-lg mx-auto">
          The two-way Web Audio mic streaming, Silero VAD, and Edge-TTS playback interface will launch in Phase 3.
        </p>
      </div>

      <div className="p-6 rounded-2xl bg-slate-900/50 border border-slate-800 max-w-md mx-auto text-left text-xs text-slate-400 space-y-3">
        <p className="font-semibold text-emerald-400">Available Now in Phase 2:</p>
        <p className="text-slate-300">
          You can test this agent's streaming LLM responses, context window trimming, and first-token latency right now on the agent's <strong>Text Chat</strong> tab.
        </p>
      </div>

      <div className="flex justify-center gap-4">
        <Link
          href={`/dashboard/agents/${agentId}`}
          className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-emerald-500 hover:bg-emerald-600 text-slate-950 font-semibold text-sm transition"
        >
          <MessageSquare className="w-4 h-4" />
          Open Agent Text Chat
        </Link>
        <Link
          href="/dashboard/agents"
          className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 text-sm font-semibold transition"
        >
          <ArrowLeft className="w-4 h-4" />
          All Agents
        </Link>
      </div>
    </div>
  );
}
