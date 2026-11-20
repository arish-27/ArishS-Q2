'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { api } from '@/lib/api';
import { Agent } from '@/types';
import {
  Bot,
  Plus,
  Search,
  Sparkles,
  ExternalLink,
  Edit,
  Trash2,
  Copy,
  Check,
  AlertCircle
} from 'lucide-react';

export default function AgentsListPage() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [copiedSlug, setCopiedSlug] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const fetchAgents = async () => {
    try {
      const data = await api.listAgents();
      setAgents(data);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAgents();
  }, []);

  const handleDelete = async (id: string) => {
    if (!confirm('Are you sure you want to delete this voice agent? This action cannot be undone.')) {
      return;
    }
    setDeletingId(id);
    try {
      await api.deleteAgent(id);
      setAgents((prev) => prev.filter((a) => a.id !== id));
    } catch (err: any) {
      alert(err.message || 'Failed to delete agent');
    } finally {
      setDeletingId(null);
    }
  };

  const handleCopyLink = (slug: string) => {
    const url = `${window.location.origin}/a/${slug}`;
    navigator.clipboard.writeText(url);
    setCopiedSlug(slug);
    setTimeout(() => setCopiedSlug(null), 2000);
  };

  const filteredAgents = agents.filter(
    (a) =>
      a.name.toLowerCase().includes(search.toLowerCase()) ||
      (a.description && a.description.toLowerCase().includes(search.toLowerCase())) ||
      (a.personality && a.personality.toLowerCase().includes(search.toLowerCase()))
  );

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white tracking-tight">Voice Agents</h1>
          <p className="text-slate-400 text-sm mt-1">
            Manage your conversational voice bots, personality prompts, and voice models.
          </p>
        </div>
        <Link
          href="/dashboard/agents/new"
          className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-emerald-500 hover:bg-emerald-600 text-slate-950 font-semibold text-sm transition shadow-lg shadow-emerald-500/20"
        >
          <Plus className="w-4 h-4" />
          Create Voice Agent
        </Link>
      </div>

      {/* Search Bar */}
      <div className="relative">
        <Search className="w-5 h-5 absolute left-3 top-3 text-slate-500" />
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search agents by name, personality, or description..."
          className="w-full pl-10 pr-4 py-2.5 bg-slate-900 border border-slate-800 rounded-xl text-white placeholder-slate-500 focus:outline-none focus:border-emerald-500 text-sm transition"
        />
      </div>

      {/* Agent Grid */}
      {loading ? (
        <div className="p-16 text-center text-slate-500">Loading your voice agents...</div>
      ) : filteredAgents.length === 0 ? (
        <div className="p-16 text-center rounded-2xl border border-dashed border-slate-800 bg-slate-900/30">
          <Bot className="w-12 h-12 text-slate-600 mx-auto mb-3" />
          <h3 className="text-base font-semibold text-white">No agents match your search</h3>
          <p className="text-sm text-slate-400 mt-1 mb-4">
            Try adjusting your search filter or create a new voice agent.
          </p>
          <Link
            href="/dashboard/agents/new"
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-emerald-500 hover:bg-emerald-600 text-slate-950 font-semibold text-xs transition"
          >
            <Plus className="w-3.5 h-3.5" />
            Create Agent
          </Link>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
          {filteredAgents.map((agent) => (
            <div
              key={agent.id}
              className="p-5 rounded-2xl bg-slate-900/70 border border-slate-800 hover:border-slate-700 transition flex flex-col justify-between"
            >
              <div>
                <div className="flex items-start justify-between gap-2 mb-2">
                  <h3 className="font-bold text-white text-base truncate">{agent.name}</h3>
                  <span
                    className={`px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wider ${
                      agent.is_published
                        ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30'
                        : 'bg-slate-800 text-slate-400'
                    }`}
                  >
                    {agent.is_published ? 'Published' : 'Draft'}
                  </span>
                </div>

                <p className="text-xs text-slate-400 line-clamp-2 mb-4">
                  {agent.description || agent.personality || 'No description provided.'}
                </p>

                {/* Specs Box */}
                <div className="space-y-1.5 text-[11px] text-slate-400 bg-slate-950/60 p-3 rounded-xl border border-slate-800/40 mb-4">
                  <div className="flex justify-between">
                    <span className="text-slate-500">LLM Provider</span>
                    <span className="text-slate-200 font-medium capitalize">{agent.llm_provider} ({agent.llm_model})</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-500">TTS Voice</span>
                    <span className="text-slate-200 font-medium truncate max-w-[150px]">{agent.tts_voice}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-500">Temperature</span>
                    <span className="text-slate-200 font-medium">{agent.temperature}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-500">Public Slug</span>
                    <span className="text-slate-300 font-mono text-[10px]">/a/{agent.slug}</span>
                  </div>
                </div>
              </div>

              {/* Action Buttons */}
              <div className="space-y-2 pt-3 border-t border-slate-800/60">
                <div className="flex items-center gap-2">
                  <Link
                    href={`/dashboard/agents/${agent.id}/playground`}
                    className="flex-1 inline-flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 text-xs font-semibold transition"
                  >
                    <Sparkles className="w-3.5 h-3.5" />
                    Playground
                  </Link>

                  {agent.is_published && (
                    <button
                      onClick={() => handleCopyLink(agent.slug)}
                      title="Copy public shareable link"
                      className="p-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white transition text-xs"
                    >
                      {copiedSlug === agent.slug ? <Check className="w-4 h-4 text-emerald-400" /> : <Copy className="w-4 h-4" />}
                    </button>
                  )}

                  <Link
                    href={`/dashboard/agents/${agent.id}`}
                    title="Edit Agent"
                    className="p-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white transition text-xs"
                  >
                    <Edit className="w-4 h-4" />
                  </Link>

                  <button
                    onClick={() => handleDelete(agent.id)}
                    disabled={deletingId === agent.id}
                    title="Delete Agent"
                    className="p-2 rounded-lg bg-slate-800 hover:bg-red-500/20 text-slate-400 hover:text-red-400 transition text-xs disabled:opacity-50"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
