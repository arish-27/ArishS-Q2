'use client';

import { useEffect, useState, useRef } from 'react';
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
  Save,
  MessageSquare,
  Send,
  RotateCcw,
  Clock,
  Zap,
  Key
} from 'lucide-react';

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  firstTokenLatencyMs?: number;
  totalLatencyMs?: number;
}

export default function EditAgentPage() {
  const router = useRouter();
  const params = useParams();
  const agentId = params.id as string;

  const [activeTab, setActiveTab] = useState<'config' | 'chat'>('config');

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

  // Chat State
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputMessage, setInputMessage] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [sessionId, setSessionId] = useState<string | undefined>(undefined);
  const [chatError, setChatError] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

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

  useEffect(() => {
    if (activeTab === 'chat') {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages, activeTab]);

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

  const handleSendMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    const text = inputMessage.trim();
    if (!text || isStreaming) return;

    setChatError(null);
    setInputMessage('');

    const userMsgId = 'user-' + Date.now();
    const asstMsgId = 'asst-' + Date.now();

    const newMessages: ChatMessage[] = [
      ...messages,
      { id: userMsgId, role: 'user', content: text },
      { id: asstMsgId, role: 'assistant', content: '' },
    ];
    setMessages(newMessages);
    setIsStreaming(true);

    try {
      await api.streamChat(agentId, text, sessionId, {
        onFirstToken: (latMs) => {
          setMessages((prev) =>
            prev.map((m) => (m.id === asstMsgId ? { ...m, firstTokenLatencyMs: latMs } : m))
          );
        },
        onToken: (token) => {
          setMessages((prev) =>
            prev.map((m) => (m.id === asstMsgId ? { ...m, content: m.content + token } : m))
          );
        },
        onDone: (data) => {
          setSessionId(data.session_id);
          setMessages((prev) =>
            prev.map((m) =>
              m.id === asstMsgId
                ? {
                    ...m,
                    content: data.content,
                    firstTokenLatencyMs: data.first_token_latency_ms,
                    totalLatencyMs: data.total_latency_ms,
                  }
                : m
            )
          );
          setIsStreaming(false);
        },
        onError: (errData) => {
          setChatError(errData.error || 'Streaming error occurred');
          setIsStreaming(false);
        },
      });
    } catch (err: any) {
      setChatError(err.message || 'Failed to send message');
      setIsStreaming(false);
    }
  };

  const handleClearChat = () => {
    setMessages([]);
    setSessionId(undefined);
    setChatError(null);
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
            className="inline-flex items-center gap-2 px-3 py-1.5 rounded-xl bg-slate-900 border border-slate-800 text-slate-300 hover:text-white text-xs font-medium transition"
          >
            <Sparkles className="w-3.5 h-3.5 text-emerald-400" />
            Voice Playground
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

      {/* Tabs */}
      <div className="flex border-b border-slate-800 space-x-2">
        <button
          onClick={() => setActiveTab('config')}
          className={`flex items-center gap-2 px-4 py-2.5 text-sm font-semibold border-b-2 transition ${
            activeTab === 'config'
              ? 'border-emerald-500 text-emerald-400'
              : 'border-transparent text-slate-400 hover:text-slate-200'
          }`}
        >
          <Sliders className="w-4 h-4" />
          Configuration
        </button>
        <button
          onClick={() => setActiveTab('chat')}
          className={`flex items-center gap-2 px-4 py-2.5 text-sm font-semibold border-b-2 transition ${
            activeTab === 'chat'
              ? 'border-emerald-500 text-emerald-400'
              : 'border-transparent text-slate-400 hover:text-slate-200'
          }`}
        >
          <MessageSquare className="w-4 h-4" />
          Text Chat Test
          <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
        </button>
      </div>

      {/* TAB 1: CONFIGURATION */}
      {activeTab === 'config' && (
        <div className="space-y-6">
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

          {/* Deployment Banner */}
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
                  ? 'Anyone with this shareable link can hold real-time calls with this agent.'
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
            {/* General Settings */}
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
                    LLM Model (Active Models)
                  </label>
                  <select
                    value={llmModel}
                    onChange={(e) => setLlmModel(e.target.value)}
                    className="w-full px-4 py-2.5 bg-slate-950 border border-slate-800 rounded-lg text-white text-sm focus:outline-none focus:border-emerald-500"
                  >
                    {llmProvider === 'gemini' ? (
                      <>
                        <option value="gemini-2.5-flash">gemini-2.5-flash (Low-latency reasoning)</option>
                        <option value="gemini-2.5-pro">gemini-2.5-pro (Advanced reasoning)</option>
                        <option value="gemini-1.5-flash">gemini-1.5-flash (High speed)</option>
                        <option value="gemini-1.5-pro">gemini-1.5-pro</option>
                      </>
                    ) : (
                      <>
                        <option value="gpt-4o-mini">gpt-4o-mini (Fast & economical)</option>
                        <option value="gpt-4o">gpt-4o (Multimodal flagship)</option>
                        <option value="o1-mini">o1-mini (Fast reasoning)</option>
                        <option value="o1">o1 (Full reasoning)</option>
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
      )}

      {/* TAB 2: LIVE TEXT CHAT */}
      {activeTab === 'chat' && (
        <div className="flex flex-col h-[650px] bg-slate-900/70 border border-slate-800 rounded-2xl overflow-hidden shadow-2xl">
          {/* Chat Sub-header */}
          <div className="p-4 bg-slate-950/80 border-b border-slate-800 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-xl bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center text-emerald-400">
                <Bot className="w-5 h-5" />
              </div>
              <div>
                <h3 className="font-bold text-white text-sm">{agent.name}</h3>
                <p className="text-[11px] text-slate-400">
                  <span className="capitalize">{agent.llm_provider}</span> ({agent.llm_model}) • Temp: {agent.temperature}
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <Link
                href="/dashboard/vault"
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs transition"
              >
                <Key className="w-3.5 h-3.5 text-sky-400" />
                Key Vault
              </Link>
              <button
                onClick={handleClearChat}
                title="Reset Conversation"
                className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs transition"
              >
                <RotateCcw className="w-3.5 h-3.5" />
                Reset
              </button>
            </div>
          </div>

          {/* Error Banner */}
          {chatError && (
            <div className="p-3 bg-red-500/10 border-b border-red-500/30 text-red-400 text-xs flex items-center justify-between px-4">
              <span>{chatError}</span>
              {chatError.includes('API key') && (
                <Link
                  href="/dashboard/vault"
                  className="underline font-semibold ml-2 hover:text-white"
                >
                  Configure Vault &rarr;
                </Link>
              )}
            </div>
          )}

          {/* Messages Stream */}
          <div className="flex-1 overflow-y-auto p-4 sm:p-6 space-y-4">
            {messages.length === 0 ? (
              <div className="h-full flex flex-col items-center justify-center text-center p-8 text-slate-500 space-y-2">
                <Bot className="w-12 h-12 text-slate-700 mb-2" />
                <p className="font-semibold text-slate-300 text-sm">Start a conversation with {agent.name}</p>
                <p className="text-xs text-slate-500 max-w-sm">
                  Test streaming LLM generation, system prompt adherence, context window trimming, and response latencies.
                </p>
              </div>
            ) : (
              messages.map((msg) => (
                <div
                  key={msg.id}
                  className={`flex flex-col ${msg.role === 'user' ? 'items-end' : 'items-start'}`}
                >
                  <div
                    className={`max-w-[85%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
                      msg.role === 'user'
                        ? 'bg-emerald-500 text-slate-950 font-medium rounded-br-none shadow-md shadow-emerald-500/10'
                        : 'bg-slate-800/80 text-slate-100 rounded-bl-none border border-slate-700/60 shadow-md'
                    }`}
                  >
                    {msg.content ? (
                      <div className="whitespace-pre-wrap">{msg.content}</div>
                    ) : (
                      <span className="inline-flex items-center gap-1.5 text-xs text-slate-400 italic">
                        <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
                        Thinking...
                      </span>
                    )}
                  </div>

                  {/* Latency HUD for assistant turns */}
                  {msg.role === 'assistant' && (msg.firstTokenLatencyMs || msg.totalLatencyMs) && (
                    <div className="flex items-center gap-3 mt-1.5 px-1 text-[10px] text-slate-500 font-mono">
                      {msg.firstTokenLatencyMs && (
                        <span className="inline-flex items-center gap-1 text-emerald-400">
                          <Zap className="w-3 h-3" />
                          TTFT: {msg.firstTokenLatencyMs}ms
                        </span>
                      )}
                      {msg.totalLatencyMs && (
                        <span className="inline-flex items-center gap-1 text-slate-400">
                          <Clock className="w-3 h-3" />
                          Total: {msg.totalLatencyMs}ms
                        </span>
                      )}
                    </div>
                  )}
                </div>
              ))
            )}
            <div ref={messagesEndRef} />
          </div>

          {/* Message Input Box */}
          <form onSubmit={handleSendMessage} className="p-4 bg-slate-950/80 border-t border-slate-800 flex gap-2">
            <input
              type="text"
              value={inputMessage}
              onChange={(e) => setInputMessage(e.target.value)}
              placeholder={`Message ${agent.name}...`}
              disabled={isStreaming}
              className="flex-1 px-4 py-3 bg-slate-900 border border-slate-800 rounded-xl text-white placeholder-slate-500 focus:outline-none focus:border-emerald-500 text-sm transition disabled:opacity-50"
            />
            <button
              type="submit"
              disabled={isStreaming || !inputMessage.trim()}
              className="px-5 py-3 rounded-xl bg-emerald-500 hover:bg-emerald-600 text-slate-950 font-semibold text-sm transition flex items-center justify-center gap-2 shadow-lg shadow-emerald-500/20 disabled:opacity-50"
            >
              {isStreaming ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
            </button>
          </form>
        </div>
      )}
    </div>
  );
}
