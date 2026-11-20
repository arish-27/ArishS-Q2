'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { api } from '@/lib/api';
import { Agent, ApiKeyItem } from '@/types';
import { Bot, Plus, Key, ArrowRight, Activity, Sparkles, Radio } from 'lucide-react';

export default function DashboardPage() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [keys, setKeys] = useState<ApiKeyItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function loadData() {
      try {
        const [agentsData, keysData] = await Promise.all([
          api.listAgents().catch(() => []),
          api.listKeys().catch(() => []),
        ]);
        setAgents(agentsData);
        setKeys(keysData);
      } finally {
        setLoading(false);
      }
    }
    loadData();
  }, []);

  return (
    <div className="max-w-6xl mx-auto space-y-8">
      {/* Header Banner */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-6 rounded-2xl bg-gradient-to-r from-slate-900 via-slate-900/90 to-slate-950 border border-slate-800 shadow-xl">
        <div>
          <div className="inline-flex items-center gap-2 px-2.5 py-0.5 rounded-full border border-emerald-500/30 bg-emerald-500/10 text-emerald-400 text-xs font-medium mb-2">
            <Radio className="w-3 h-3 animate-pulse" />
            Full-Duplex Engine Active
          </div>
          <h1 className="text-2xl font-bold text-white tracking-tight">Voice Agent Studio</h1>
          <p className="text-slate-400 text-sm mt-1">Design, test, and deploy real-time conversational AI voice agents.</p>
        </div>
        <Link
          href="/dashboard/agents/new"
          className="inline-flex items-center justify-center gap-2 px-5 py-2.5 rounded-xl bg-emerald-500 hover:bg-emerald-600 text-slate-950 font-semibold text-sm transition shadow-lg shadow-emerald-500/20"
        >
          <Plus className="w-4 h-4" />
          Create New Agent
        </Link>
      </div>

      {/* Metrics Row */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-5">
        <div className="p-5 rounded-2xl bg-slate-900/60 border border-slate-800">
          <div className="flex items-center justify-between text-slate-400 mb-3">
            <span className="text-xs font-semibold uppercase tracking-wider">Total Agents</span>
            <Bot className="w-4 h-4 text-emerald-400" />
          </div>
          <p className="text-3xl font-extrabold text-white">{loading ? '...' : agents.length}</p>
          <p className="text-xs text-slate-500 mt-1">{agents.filter((a) => a.is_published).length} published live</p>
        </div>

        <div className="p-5 rounded-2xl bg-slate-900/60 border border-slate-800">
          <div className="flex items-center justify-between text-slate-400 mb-3">
            <span className="text-xs font-semibold uppercase tracking-wider">Encrypted API Keys</span>
            <Key className="w-4 h-4 text-sky-400" />
          </div>
          <p className="text-3xl font-extrabold text-white">{loading ? '...' : keys.length}</p>
          <p className="text-xs text-slate-500 mt-1">Stored securely via Fernet AES-256</p>
        </div>

        <div className="p-5 rounded-2xl bg-slate-900/60 border border-slate-800">
          <div className="flex items-center justify-between text-slate-400 mb-3">
            <span className="text-xs font-semibold uppercase tracking-wider">Target Latency</span>
            <Activity className="w-4 h-4 text-purple-400" />
          </div>
          <p className="text-3xl font-extrabold text-white">&lt; 1.2s</p>
          <p className="text-xs text-slate-500 mt-1">End-to-end VAD + STT + LLM + TTS</p>
        </div>
      </div>

      {/* Agents Section */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-bold text-white tracking-tight">Your Voice Agents</h2>
          <Link
            href="/dashboard/agents"
            className="text-xs font-medium text-emerald-400 hover:text-emerald-300 flex items-center gap-1 transition"
          >
            View all <ArrowRight className="w-3.5 h-3.5" />
          </Link>
        </div>

        {loading ? (
          <div className="p-12 text-center text-slate-500">Loading agents...</div>
        ) : agents.length === 0 ? (
          <div className="p-12 text-center rounded-2xl border border-dashed border-slate-800 bg-slate-900/30">
            <Bot className="w-10 h-10 text-slate-600 mx-auto mb-3" />
            <h3 className="text-base font-semibold text-white">No voice agents created yet</h3>
            <p className="text-sm text-slate-400 max-w-sm mx-auto mt-1 mb-4">
              Get started by creating your first agent with custom personality, LLM provider, and voice settings.
            </p>
            <Link
              href="/dashboard/agents/new"
              className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-emerald-500 hover:bg-emerald-600 text-slate-950 font-semibold text-xs transition"
            >
              <Plus className="w-3.5 h-3.5" />
              Build Agent
            </Link>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
            {agents.slice(0, 6).map((agent) => (
              <div
                key={agent.id}
                className="p-5 rounded-2xl bg-slate-900/60 border border-slate-800 hover:border-slate-700 transition flex flex-col justify-between"
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

                  <div className="grid grid-cols-2 gap-2 text-[11px] text-slate-400 bg-slate-950/60 p-2.5 rounded-xl border border-slate-800/40 mb-4">
                    <div>
                      <span className="text-slate-500 block text-[9px] uppercase">LLM</span>
                      <span className="font-medium text-slate-200 capitalize">{agent.llm_provider}</span>
                    </div>
                    <div>
                      <span className="text-slate-500 block text-[9px] uppercase">Voice</span>
                      <span className="font-medium text-slate-200 truncate block">{agent.tts_voice.split('-')[2] || agent.tts_voice}</span>
                    </div>
                  </div>
                </div>

                <div className="flex items-center justify-between pt-3 border-t border-slate-800/60">
                  <Link
                    href={`/dashboard/agents/${agent.id}`}
                    className="text-xs font-semibold text-slate-300 hover:text-white transition"
                  >
                    Edit Agent
                  </Link>
                  <Link
                    href={`/dashboard/agents/${agent.id}/playground`}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 text-xs font-semibold transition"
                  >
                    <Sparkles className="w-3.5 h-3.5" />
                    Playground
                  </Link>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
