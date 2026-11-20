'use client';

import { useEffect, useState } from 'react';
import { useRouter, useParams } from 'next/navigation';
import Link from 'next/link';
import { api } from '@/lib/api';
import { Agent } from '@/types';
import {
  Bot,
  ArrowLeft,
  Loader2,
  Sparkles,
  Sliders,
  Volume2,
  Globe,
  Copy,
  Check,
  ExternalLink,
  Trash2,
  Save
} from 'lucide-react';

export default function EditAgentPage() {
  const router = useRouter();
  const params = useParams();
  const agentId = params.id as string;

  const [agent, setAgent] = useState<Agent | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  // Form Fields
  const [name, setName] = useState('');
  const [slug, setSlug] = useState('');
  const [description, setDescription] = useState('');
  const [personality, setPersonality] = useState('');
  const [systemPrompt, setSystemPrompt] = useState('');
  const [llmProvider, setLlmProvider] = useState('gemini');
  const [llmModel, setLlmModel] = useState('gemini-2.5-flash');
  const [temperature, setTemperature] = useState(0.7);
  const [sttProvider, setSttProvider] = useState('faster-whisper');
  const [sttLanguage, setSttLanguage] = useState('en');
  const [ttsProvider, setTtsProvider] = useState('edge-tts');
  const [ttsVoice, setTtsVoice] = useState('en-US-GuyNeural');
  const [isPublished, setIsPublished] = useState(false);

  useEffect(() => {
    async function loadAgent() {
      try {
        const data = await api.getAgent(agentId);
        setAgent(data);
        setName(data.name);
        setSlug(data.slug);
        setDescription(data.description || '');
        setPersonality(data.personality || '');
        setSystemPrompt(data.system_prompt);
        setLlmProvider(data.llm_provider);
        setLlmModel(data.llm_model);
        setTemperature(data.temperature);
        setSttProvider(data.stt_provider);
        setSttLanguage(data.stt_language);
        setTtsProvider(data.tts_provider);
        setTtsVoice(data.tts_voice);
        setIsPublished(data.is_published);
      } catch (err: any) {
        setError(err.message || 'Failed to load agent');
      } finally {
        setLoading(false);
      }
    }
    loadAgent();
  }, [agentId]);

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    setSuccess(null);

    try {
      const updated = await api.updateAgent(agentId, {
        name,
        slug: slug.trim(),
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
        is_published: isPublished,
      });
      setAgent(updated);
      setSuccess('Agent changes saved successfully!');
      setTimeout(() => setSuccess(null), 3000);
    } catch (err: any) {
      setError(err.message || 'Failed to update agent');
    } finally {
      setSaving(false);
    }
  };

  const handleTogglePublish = async () => {
    try {
      const newStatus = !isPublished;
      const updated = await api.publishAgent(agentId, {
        is_published: newStatus,
        slug: slug.trim(),
      });
      setIsPublished(newStatus);
      setAgent(updated);
      setSuccess(`Agent is now ${newStatus ? 'published live' : 'unpublished'}`);
      setTimeout(() => setSuccess(null), 3000);
    } catch (err: any) {
      setError(err.message || 'Failed to toggle publication');
    }
  };

  const handleCopyLink = () => {
    const url = `${window.location.origin}/a/${slug}`;
    navigator.clipboard.writeText(url);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDelete = async () => {
    if (!confirm('Are you sure you want to delete this agent?')) return;
    try {
      await api.deleteAgent(agentId);
      router.push('/dashboard/agents');
    } catch (err: any) {
      setError(err.message || 'Failed to delete agent');
    }
  };

  if (loading) {
    return <div className="p-16 text-center text-slate-500">Loading agent details...</div>;
  }

  if (!agent) {
    return (
      <div className="p-12 text-center text-red-400">
        Agent not found or you do not have permission to view it.
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <Link
            href="/dashboard/agents"
            className="p-2 rounded-lg bg-slate-900 border border-slate-800 text-slate-400 hover:text-white transition"
          >
            <ArrowLeft className="w-5 h-5" />
          </Link>
          <div>
            <h1 className="text-2xl font-bold text-white tracking-tight">{agent.name}</h1>
            <p className="text-slate-400 text-xs font-mono mt-0.5">ID: {agent.id}</p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <Link
            href={`/dashboard/agents/${agentId}/playground`}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 text-xs font-semibold transition"
          >
            <Sparkles className="w-4 h-4" />
            Launch Playground
          </Link>
          <button
            onClick={handleDelete}
            title="Delete Agent"
            className="p-2 rounded-xl bg-slate-900 border border-slate-800 text-slate-400 hover:text-red-400 hover:bg-red-500/10 transition"
          >
            <Trash2 className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Notifications */}
      {error && (
        <div className="p-4 rounded-xl bg-red-500/10 border border-red-500/30 text-red-400 text-sm">
          {error}
        </div>
      )}
      {success && (
        <div className="p-4 rounded-xl bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 text-sm">
          {success}
        </div>
      )}

      {/* Deployment & Share Banner */}
      <div className="p-6 rounded-2xl bg-gradient-to-r from-slate-900 to-slate-950 border border-slate-800 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <Globe className="w-4 h-4 text-emerald-400" />
            <span className="font-semibold text-white text-sm">Public Web Deployment</span>
            <span
              className={`px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase ${
                isPublished
                  ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30'
                  : 'bg-slate-800 text-slate-400'
              }`}
            >
              {isPublished ? 'Live & Active' : 'Private Draft'}
            </span>
          </div>
          <p className="text-xs text-slate-400">
            {isPublished
              ? 'Anyone with this shareable link can hold real-time voice calls with this agent.'
              : 'Publish this agent to generate a public voice link.'}
          </p>
        </div>

        <div className="flex items-center gap-2">
          {isPublished && (
            <>
              <button
                onClick={handleCopyLink}
                className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium transition"
              >
                {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                Copy Link
              </button>
              <Link
                href={`/a/${slug}`}
                target="_blank"
                className="inline-flex items-center gap-1 px-3 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium transition"
              >
                <ExternalLink className="w-3.5 h-3.5" />
                Visit
              </Link>
            </>
          )}
          <button
            onClick={handleTogglePublish}
            className={`px-4 py-2 rounded-lg text-xs font-semibold transition ${
              isPublished
                ? 'bg-slate-800 hover:bg-slate-700 text-slate-300'
                : 'bg-emerald-500 hover:bg-emerald-600 text-slate-950 font-semibold'
            }`}
          >
            {isPublished ? 'Unpublish' : 'Publish Agent'}
          </button>
        </div>
      </div>

      <form onSubmit={handleSave} className="space-y-6">
        {/* Identity & Personality */}
        <div className="p-6 rounded-2xl bg-slate-900/60 border border-slate-800 space-y-4">
          <div className="flex items-center gap-2 text-white font-semibold text-base border-b border-slate-800/80 pb-3">
            <Bot className="w-5 h-5 text-emerald-400" />
            General Settings
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-2">
                Agent Name
              </label>
              <input
                type="text"
                required
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="w-full px-4 py-2.5 bg-slate-950 border border-slate-800 rounded-lg text-white focus:outline-none focus:border-emerald-500 text-sm transition"
              />
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-2">
                Public URL Slug
              </label>
              <input
                type="text"
                required
                value={slug}
                onChange={(e) => setSlug(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, ''))}
                className="w-full px-4 py-2.5 bg-slate-950 border border-slate-800 rounded-lg text-white font-mono text-sm focus:outline-none focus:border-emerald-500 transition"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-2">
              Description
            </label>
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="w-full px-4 py-2.5 bg-slate-950 border border-slate-800 rounded-lg text-white focus:outline-none focus:border-emerald-500 text-sm transition"
            />
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-2">
              Personality Traits
            </label>
            <input
              type="text"
              value={personality}
              onChange={(e) => setPersonality(e.target.value)}
              className="w-full px-4 py-2.5 bg-slate-950 border border-slate-800 rounded-lg text-white focus:outline-none focus:border-emerald-500 text-sm transition"
            />
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-2">
              System Prompt
            </label>
            <textarea
              rows={5}
              required
              value={systemPrompt}
              onChange={(e) => setSystemPrompt(e.target.value)}
              className="w-full p-4 bg-slate-950 border border-slate-800 rounded-lg text-white font-mono text-sm focus:outline-none focus:border-emerald-500 transition"
            />
          </div>
        </div>

        {/* Model & Providers */}
        <div className="p-6 rounded-2xl bg-slate-900/60 border border-slate-800 space-y-4">
          <div className="flex items-center gap-2 text-white font-semibold text-base border-b border-slate-800/80 pb-3">
            <Sliders className="w-5 h-5 text-sky-400" />
            Model & Voice Engine
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
                  setLlmModel(e.target.value === 'gemini' ? 'gemini-2.5-flash' : 'gpt-4o-mini');
                }}
                className="w-full px-4 py-2.5 bg-slate-950 border border-slate-800 rounded-lg text-white text-sm focus:outline-none focus:border-emerald-500"
              >
                <option value="gemini">Google Gemini</option>
                <option value="openai">OpenAI</option>
              </select>
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-2">
                LLM Model
              </label>
              <select
                value={llmModel}
                onChange={(e) => setLlmModel(e.target.value)}
                className="w-full px-4 py-2.5 bg-slate-950 border border-slate-800 rounded-lg text-white text-sm focus:outline-none focus:border-emerald-500"
              >
                {llmProvider === 'gemini' ? (
                  <>
                    <option value="gemini-2.5-flash">gemini-2.5-flash</option>
                    <option value="gemini-1.5-pro">gemini-1.5-pro</option>
                  </>
                ) : (
                  <>
                    <option value="gpt-4o-mini">gpt-4o-mini</option>
                    <option value="gpt-4o">gpt-4o</option>
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
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-2">
            <div>
              <label className="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-2">
                TTS Voice
              </label>
              <select
                value={ttsVoice}
                onChange={(e) => setTtsVoice(e.target.value)}
                className="w-full px-4 py-2.5 bg-slate-950 border border-slate-800 rounded-lg text-white text-sm focus:outline-none focus:border-emerald-500"
              >
                <option value="en-US-GuyNeural">en-US-GuyNeural (Male, Natural)</option>
                <option value="en-US-JennyNeural">en-US-JennyNeural (Female, Friendly)</option>
                <option value="en-GB-SoniaNeural">en-GB-SoniaNeural (British Female)</option>
                <option value="en-AU-NatNeural">en-AU-NatNeural (Australian Male)</option>
              </select>
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-2">
                STT Language
              </label>
              <select
                value={sttLanguage}
                onChange={(e) => setSttLanguage(e.target.value)}
                className="w-full px-4 py-2.5 bg-slate-950 border border-slate-800 rounded-lg text-white text-sm focus:outline-none focus:border-emerald-500"
              >
                <option value="en">English (en)</option>
                <option value="es">Spanish (es)</option>
                <option value="fr">French (fr)</option>
                <option value="de">German (de)</option>
                <option value="hi">Hindi (hi)</option>
              </select>
            </div>
          </div>
        </div>

        {/* Save Bar */}
        <div className="flex justify-end gap-4">
          <button
            type="submit"
            disabled={saving}
            className="px-6 py-2.5 rounded-xl bg-emerald-500 hover:bg-emerald-600 text-slate-950 font-semibold text-sm transition flex items-center gap-2 shadow-lg shadow-emerald-500/20 disabled:opacity-50"
          >
            {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <><Save className="w-4 h-4" /> Save Changes</>}
          </button>
        </div>
      </form>
    </div>
  );
}
