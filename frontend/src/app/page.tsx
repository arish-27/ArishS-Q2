'use client';

import { useEffect } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { api } from '@/lib/api';
import { Bot, Mic, Zap, ShieldCheck, Layers, Wrench, ArrowRight } from 'lucide-react';

export default function Home() {
  const router = useRouter();

  useEffect(() => {
    if (api.getToken()) {
      router.replace('/dashboard');
    }
  }, [router]);

  return (
    <div className="min-h-screen flex flex-col bg-slate-950 text-white">
      {/* Header */}
      <header className="border-b border-slate-800/80 bg-slate-950/80 backdrop-blur sticky top-0 z-20">
        <div className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between">
          <Link href="/" className="flex items-center gap-2.5 font-bold text-lg tracking-tight">
            <div className="w-8 h-8 rounded-lg bg-emerald-500/15 border border-emerald-500/30 flex items-center justify-center text-emerald-400">
              <Bot className="w-5 h-5" />
            </div>
            <span>VoiceAgent Studio</span>
          </Link>
          <div className="flex items-center gap-3">
            <Link
              href="/login"
              className="px-4 py-2 rounded-lg text-sm font-medium text-slate-300 hover:text-white transition"
            >
              Login
            </Link>
            <Link
              href="/register"
              className="px-4 py-2 rounded-lg bg-emerald-500 hover:bg-emerald-600 text-slate-950 font-semibold text-sm transition"
            >
              Get Started
            </Link>
          </div>
        </div>
      </header>

      {/* Hero */}
      <main className="flex-1">
        <section className="max-w-5xl mx-auto px-6 py-20 text-center space-y-6">
          <h1 className="text-4xl sm:text-6xl font-extrabold tracking-tight bg-clip-text text-transparent bg-gradient-to-r from-white via-slate-200 to-slate-400">
            Build & Deploy Real-Time AI Voice Agents
          </h1>
          <p className="text-slate-400 text-base sm:text-lg max-w-2xl mx-auto leading-relaxed">
            Full-duplex voice pipelines built from first principles: Silero VAD with barge-in, local faster-whisper STT, streaming Gemini & OpenAI LLMs, sentence-level TTS, pgvector RAG, and function calling.
          </p>
          <div className="flex flex-wrap items-center justify-center gap-4 pt-2">
            <Link
              href="/register"
              className="inline-flex items-center gap-2 px-6 py-3 rounded-xl bg-emerald-500 hover:bg-emerald-600 text-slate-950 font-semibold text-sm transition shadow-lg shadow-emerald-500/20"
            >
              Get Started <ArrowRight className="w-4 h-4" />
            </Link>
            <Link
              href="/login"
              className="px-6 py-3 rounded-xl border border-slate-700 hover:bg-slate-800 text-slate-200 font-semibold text-sm transition"
            >
              Login
            </Link>
          </div>
        </section>

        {/* Features */}
        <section className="max-w-6xl mx-auto px-6 pb-20">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
            <div className="p-5 rounded-2xl border border-slate-800 bg-slate-900/50 space-y-2">
              <Mic className="w-5 h-5 text-emerald-400" />
              <h3 className="font-semibold text-white text-sm">Real-Time Voice & Barge-in</h3>
              <p className="text-xs text-slate-400 leading-relaxed">
                16kHz PCM16 WebSocket streaming, hysteresis VAD, instant interruption, and gapless playback.
              </p>
            </div>
            <div className="p-5 rounded-2xl border border-slate-800 bg-slate-900/50 space-y-2">
              <Zap className="w-5 h-5 text-sky-400" />
              <h3 className="font-semibold text-white text-sm">Streaming LLM & TTS</h3>
              <p className="text-xs text-slate-400 leading-relaxed">
                Persistent Gemini/OpenAI streaming, clause-level TTS synthesis, and per-stage latency telemetry.
              </p>
            </div>
            <div className="p-5 rounded-2xl border border-slate-800 bg-slate-900/50 space-y-2">
              <Layers className="w-5 h-5 text-purple-400" />
              <h3 className="font-semibold text-white text-sm">pgvector RAG</h3>
              <p className="text-xs text-slate-400 leading-relaxed">
                Upload PDF, DOCX, and TXT files with HNSW cosine indexing and live source citations.
              </p>
            </div>
            <div className="p-5 rounded-2xl border border-slate-800 bg-slate-900/50 space-y-2">
              <Wrench className="w-5 h-5 text-amber-400" />
              <h3 className="font-semibold text-white text-sm">Tools & Public Links</h3>
              <p className="text-xs text-slate-400 leading-relaxed">
                JSON-schema tools, SSRF-safe webhooks, sensitive confirmation gates, and shareable /a/slug pages.
              </p>
            </div>
          </div>
        </section>
      </main>

      {/* Footer */}
      <footer className="border-t border-slate-800/80 py-6 px-6 text-xs text-slate-500">
        <div className="max-w-6xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <ShieldCheck className="w-4 h-4 text-emerald-500" />
            <span>AI Voice Agent Platform — Encrypted API Key Vault & Per-Tenant Isolation</span>
          </div>
          <div className="flex items-center gap-4">
            <Link href="/login" className="hover:text-slate-300">Login</Link>
            <Link href="/register" className="hover:text-slate-300">Register</Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
