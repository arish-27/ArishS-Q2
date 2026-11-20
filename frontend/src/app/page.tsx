export default function Home() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center p-8 bg-gradient-to-b from-slate-950 via-slate-900 to-slate-950 text-white">
      <div className="z-10 max-w-4xl w-full items-center justify-between text-sm flex flex-col gap-6 text-center">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-emerald-500/30 bg-emerald-500/10 text-emerald-400 text-xs font-medium">
          <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
          Phase 0 Scaffolding Active
        </div>
        <h1 className="text-4xl sm:text-6xl font-extrabold tracking-tight bg-clip-text text-transparent bg-gradient-to-r from-white via-slate-200 to-slate-400">
          AI Voice Agent Platform
        </h1>
        <p className="text-slate-400 text-base sm:text-lg max-w-2xl leading-relaxed">
          Full-duplex real-time voice agents powered by local STT (faster-whisper), server-side VAD, streaming LLM, low-latency TTS, RAG with pgvector, and sensitive tool calling.
        </p>

        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-4 w-full mt-6 text-left">
          <div className="p-4 rounded-xl border border-slate-800 bg-slate-900/60 shadow-lg">
            <h3 className="font-semibold text-emerald-400 text-sm">STT Pipeline</h3>
            <p className="text-xs text-slate-400 mt-1">Streaming audio ingestion with faster-whisper and VAD chunking.</p>
          </div>
          <div className="p-4 rounded-xl border border-slate-800 bg-slate-900/60 shadow-lg">
            <h3 className="font-semibold text-sky-400 text-sm">LLM Orchestration</h3>
            <p className="text-xs text-slate-400 mt-1">Multi-turn context trimming, Gemini/OpenAI streaming, prompt injection.</p>
          </div>
          <div className="p-4 rounded-xl border border-slate-800 bg-slate-900/60 shadow-lg">
            <h3 className="font-semibold text-purple-400 text-sm">TTS & Barge-in</h3>
            <p className="text-xs text-slate-400 mt-1">Sentence-level audio streaming and instant user interruption handling.</p>
          </div>
          <div className="p-4 rounded-xl border border-slate-800 bg-slate-900/60 shadow-lg">
            <h3 className="font-semibold text-amber-400 text-sm">RAG & Tools</h3>
            <p className="text-xs text-slate-400 mt-1">PostgreSQL pgvector similarity search and JSON-schema function calls.</p>
          </div>
        </div>

        <div className="flex gap-4 mt-8">
          <a
            href="http://localhost:8000/docs"
            target="_blank"
            rel="noopener noreferrer"
            className="px-6 py-2.5 rounded-lg bg-emerald-500 hover:bg-emerald-600 text-slate-950 font-semibold transition text-sm shadow-md shadow-emerald-500/20"
          >
            Backend Swagger API Docs
          </a>
          <a
            href="http://localhost:8000/api/v1/health"
            target="_blank"
            rel="noopener noreferrer"
            className="px-6 py-2.5 rounded-lg border border-slate-700 hover:bg-slate-800 text-slate-300 font-medium transition text-sm"
          >
            Backend Health Check
          </a>
        </div>
      </div>
    </main>
  );
}
