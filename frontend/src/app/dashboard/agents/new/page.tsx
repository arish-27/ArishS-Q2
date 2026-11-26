'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { api } from '@/lib/api';
import { Bot, ArrowLeft, Loader2, Sparkles, Sliders, Mic, Volume2 } from 'lucide-react';

export default function CreateAgentPage() {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Form State
  const [name, setName] = useState('');
  const [slug, setSlug] = useState('');
  const [description, setDescription] = useState('');
  const [personality, setPersonality] = useState('helpful, friendly, concise');
  const [systemPrompt, setSystemPrompt] = useState(
    'You are a helpful, conversational voice assistant. Answer naturally and keep replies concise for real-time speech.'
  );

  const [llmProvider, setLlmProvider] = useState('gemini');
  const [llmModel, setLlmModel] = useState('gemini-3.5-flash-lite');
  const [temperature, setTemperature] = useState(0.7);

  const [sttProvider, setSttProvider] = useState('faster-whisper');
  const [sttLanguage, setSttLanguage] = useState('en');

  const [ttsProvider, setTtsProvider] = useState('edge-tts');
  const [ttsVoice, setTtsVoice] = useState('en-US-GuyNeural');

  const personalities = [
    { label: 'Customer Support', value: 'empathetic, patient, highly articulate and professional' },
    { label: 'Sales & Outreach', value: 'enthusiastic, persuasive, clear, and proactive' },
    { label: 'Technical Assistant', value: 'precise, logical, concise, and structured' },
    { label: 'Casual Companion', value: 'warm, humorous, engaging, and friendly' },
  ];

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);

    try {
      const agent = await api.createAgent({
        name,
        slug: slug.trim() ? slug.trim() : undefined,
        description,
        personality,
        system_prompt: systemPrompt,
        llm_provider: llmProvider,
        llm_model: llmModel,
        temperature,
        stt_provider: sttProvider,
        stt_language: sttLanguage,
        tts_provider: ttsProvider,
        tts_voice: ttsVoice,
      });
      router.push(`/dashboard/agents/${agent.id}`);
    } catch (err: any) {
      setError(err.message || 'Failed to create agent');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center gap-4">
        <Link
          href="/dashboard/agents"
          className="p-2 rounded-lg bg-slate-900 border border-slate-800 text-slate-400 hover:text-white transition"
        >
          <ArrowLeft className="w-5 h-5" />
        </Link>
        <div>
          <h1 className="text-2xl font-bold text-white tracking-tight">Create Voice Agent</h1>
          <p className="text-slate-400 text-sm">Configure voice model, personality, and intelligence pipeline.</p>
        </div>
      </div>

      {error && (
        <div className="p-4 rounded-xl bg-red-500/10 border border-red-500/30 text-red-400 text-sm">
          {error}
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-6">
        {/* Section 1: Identity & Personality */}
        <div className="p-6 rounded-2xl bg-slate-900/60 border border-slate-800 space-y-4">
          <div className="flex items-center gap-2 text-white font-semibold text-base border-b border-slate-800/80 pb-3">
            <Bot className="w-5 h-5 text-emerald-400" />
            Agent Identity & Personality
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-2">
                Agent Name *
              </label>
              <input
                type="text"
                required
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Acme Support Specialist"
                className="w-full px-4 py-2.5 bg-slate-950 border border-slate-800 rounded-lg text-white placeholder-slate-600 focus:outline-none focus:border-emerald-500 text-sm transition"
              />
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-2">
                Custom Slug (Optional)
              </label>
              <input
                type="text"
                value={slug}
                onChange={(e) => setSlug(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, ''))}
                placeholder="e.g. acme-support"
                className="w-full px-4 py-2.5 bg-slate-950 border border-slate-800 rounded-lg text-white placeholder-slate-600 focus:outline-none focus:border-emerald-500 text-sm transition"
              />
              <p className="text-[11px] text-slate-500 mt-1">Leave empty to generate automatically from name.</p>
            </div>
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-2">
              Brief Description
            </label>
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What does this agent do?"
              className="w-full px-4 py-2.5 bg-slate-950 border border-slate-800 rounded-lg text-white placeholder-slate-600 focus:outline-none focus:border-emerald-500 text-sm transition"
            />
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-2">
              Personality Presets
            </label>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-2">
              {personalities.map((p) => (
                <button
                  type="button"
                  key={p.label}
                  onClick={() => setPersonality(p.value)}
                  className={`p-2.5 rounded-lg border text-xs text-left transition ${
                    personality === p.value
                      ? 'border-emerald-500 bg-emerald-500/10 text-emerald-300'
                      : 'border-slate-800 bg-slate-950/60 text-slate-400 hover:border-slate-700'
                  }`}
                >
                  <span className="font-semibold block text-slate-200">{p.label}</span>
                </button>
              ))}
            </div>
            <input
              type="text"
              value={personality}
              onChange={(e) => setPersonality(e.target.value)}
              placeholder="Custom personality traits..."
              className="w-full px-4 py-2 bg-slate-950 border border-slate-800 rounded-lg text-white placeholder-slate-600 focus:outline-none focus:border-emerald-500 text-xs transition"
            />
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-2">
              System Prompt *
            </label>
            <textarea
              rows={4}
              required
              value={systemPrompt}
              onChange={(e) => setSystemPrompt(e.target.value)}
              className="w-full p-4 bg-slate-950 border border-slate-800 rounded-lg text-white placeholder-slate-600 focus:outline-none focus:border-emerald-500 text-sm font-mono transition"
            />
          </div>
        </div>

        {/* Section 2: LLM Configuration */}
        <div className="p-6 rounded-2xl bg-slate-900/60 border border-slate-800 space-y-4">
          <div className="flex items-center gap-2 text-white font-semibold text-base border-b border-slate-800/80 pb-3">
            <Sliders className="w-5 h-5 text-sky-400" />
            LLM Orchestration Settings
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-2">
                LLM Provider
              </label>
              <select
                value={llmProvider}
                onChange={(e) => {
                  setLlmProvider(e.target.value);
                  setLlmModel(e.target.value === 'gemini' ? 'gemini-3.5-flash-lite' : 'gpt-6-luna');
                }}
                className="w-full px-4 py-2.5 bg-slate-950 border border-slate-800 rounded-lg text-white focus:outline-none focus:border-emerald-500 text-sm transition"
              >
                <option value="gemini">Google Gemini (Recommended for low latency)</option>
                <option value="openai">OpenAI</option>
              </select>
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-2">
                Model Name
              </label>
              <select
                value={llmModel}
                onChange={(e) => setLlmModel(e.target.value)}
                className="w-full px-4 py-2.5 bg-slate-950 border border-slate-800 rounded-lg text-white focus:outline-none focus:border-emerald-500 text-sm transition"
              >
                {llmProvider === 'gemini' ? (
                  <>
                    <option value="gemini-4-hydrogen">gemini-4-hydrogen (Fast agentic daily driver)</option>
                    <option value="gemini-4-neon">gemini-4-neon (Frontier balanced)</option>
                    <option value="gemini-4-carbon">gemini-4-carbon (Highest reasoning)</option>
                    <option value="gemini-3.8-flash">gemini-3.8-flash (High-speed multimodal)</option>
                    <option value="gemini-3.5-flash-lite">gemini-3.5-flash-lite (Lowest cost & latency)</option>
                  </>
                ) : (
                  <>
                    <option value="gpt-6-luna">gpt-6-luna (Fast & cost-efficient)</option>
                    <option value="gpt-6.1-terra">gpt-6.1-terra (Fast reasoning & workflows)</option>
                    <option value="gpt-6.2-sol">gpt-6.2-sol (Balanced everyday workhorse)</option>
                    <option value="gpt-6.2-astra">gpt-6.2-astra (Flagship frontier reasoning)</option>
                  </>
                )}
              </select>
            </div>
          </div>

          <div>
            <div className="flex justify-between text-xs font-semibold text-slate-300 uppercase tracking-wider mb-2">
              <span>Temperature</span>
              <span className="text-emerald-400 font-mono">{temperature}</span>
            </div>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={temperature}
              onChange={(e) => setTemperature(parseFloat(e.target.value))}
              className="w-full accent-emerald-500"
            />
            <div className="flex justify-between text-[10px] text-slate-500 mt-1">
              <span>0.0 (Deterministic / Exact)</span>
              <span>1.0 (Creative / Expressive)</span>
            </div>
          </div>
        </div>

        {/* Section 3: Speech (STT & TTS) */}
        <div className="p-6 rounded-2xl bg-slate-900/60 border border-slate-800 space-y-4">
          <div className="flex items-center gap-2 text-white font-semibold text-base border-b border-slate-800/80 pb-3">
            <Volume2 className="w-5 h-5 text-purple-400" />
            Speech Pipeline (STT & TTS)
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-2">
                STT Provider
              </label>
              <select
                value={sttProvider}
                onChange={(e) => setSttProvider(e.target.value)}
                className="w-full px-4 py-2.5 bg-slate-950 border border-slate-800 rounded-lg text-white focus:outline-none focus:border-emerald-500 text-sm transition"
              >
                <option value="faster-whisper">faster-whisper (Local CTranslate2)</option>
                <option value="deepgram">Deepgram Nova-2 (Cloud)</option>
              </select>
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-2">
                Speech Language
              </label>
              <select
                value={sttLanguage}
                onChange={(e) => setSttLanguage(e.target.value)}
                className="w-full px-4 py-2.5 bg-slate-950 border border-slate-800 rounded-lg text-white focus:outline-none focus:border-emerald-500 text-sm transition"
              >
                <option value="en">English (en)</option>
                <option value="es">Spanish (es)</option>
                <option value="fr">French (fr)</option>
                <option value="de">German (de)</option>
                <option value="hi">Hindi (hi)</option>
              </select>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-2">
                TTS Provider
              </label>
              <select
                value={ttsProvider}
                onChange={(e) => setTtsProvider(e.target.value)}
                className="w-full px-4 py-2.5 bg-slate-950 border border-slate-800 rounded-lg text-white focus:outline-none focus:border-emerald-500 text-sm transition"
              >
                <option value="edge-tts">Edge-TTS (Free Neural Voices)</option>
                <option value="piper">Piper (Local Ultra-Low Latency)</option>
                <option value="elevenlabs">ElevenLabs (Expressive)</option>
                <option value="openai">OpenAI TTS</option>
              </select>
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-2">
                Voice Selection
              </label>
              <select
                value={ttsVoice}
                onChange={(e) => setTtsVoice(e.target.value)}
                className="w-full px-4 py-2.5 bg-slate-950 border border-slate-800 rounded-lg text-white focus:outline-none focus:border-emerald-500 text-sm transition"
              >
                <option value="en-US-GuyNeural">en-US-GuyNeural (Male, Natural)</option>
                <option value="en-US-JennyNeural">en-US-JennyNeural (Female, Friendly)</option>
                <option value="en-GB-SoniaNeural">en-GB-SoniaNeural (British Female)</option>
                <option value="en-AU-NatNeural">en-AU-NatNeural (Australian Male)</option>
              </select>
            </div>
          </div>
        </div>

        {/* Action Button */}
        <div className="flex justify-end gap-4">
          <Link
            href="/dashboard/agents"
            className="px-5 py-2.5 rounded-xl border border-slate-800 text-slate-300 hover:bg-slate-900 transition text-sm font-medium"
          >
            Cancel
          </Link>
          <button
            type="submit"
            disabled={loading}
            className="px-6 py-2.5 rounded-xl bg-emerald-500 hover:bg-emerald-600 text-slate-950 font-semibold text-sm transition flex items-center gap-2 shadow-lg shadow-emerald-500/20 disabled:opacity-50"
          >
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <><Sparkles className="w-4 h-4" /> Save & Launch Agent</>}
          </button>
        </div>
      </form>
    </div>
  );
}
