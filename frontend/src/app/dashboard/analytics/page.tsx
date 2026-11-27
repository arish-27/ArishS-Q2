'use client';

import { useEffect, useState, useCallback } from 'react';
import { api } from '@/lib/api';
import {
  Agent,
  AnalyticsOverview,
  AnalyticsSessionDetail,
  AnalyticsSessionSummary,
} from '@/types';
import {
  BarChart3,
  Clock,
  AlertTriangle,
  Activity,
  PhoneCall,
  Loader2,
  X,
  Bot,
  Mic,
  Wrench,
  Layers,
} from 'lucide-react';

export default function AnalyticsPage() {
  const [overview, setOverview] = useState<AnalyticsOverview | null>(null);
  const [sessions, setSessions] = useState<AnalyticsSessionSummary[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);

  // Filters
  const [filterAgent, setFilterAgent] = useState('');
  const [filterDate, setFilterDate] = useState('');
  const [filterStatus, setFilterStatus] = useState('');
  const [showEmpty, setShowEmpty] = useState(false);

  // Detail modal
  const [selectedDetail, setSelectedDetail] = useState<AnalyticsSessionDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [ov, sessList, agList] = await Promise.all([
        api.getAnalyticsOverview(),
        api.listAnalyticsSessions({
          agent_id: filterAgent || undefined,
          date: filterDate || undefined,
          status: filterStatus || undefined,
          include_empty: showEmpty,
        }),
        api.listAgents(),
      ]);
      setOverview(ov);
      setSessions(sessList);
      setAgents(agList);
    } finally {
      setLoading(false);
    }
  }, [filterAgent, filterDate, filterStatus, showEmpty]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const openDetail = async (sessionId: string) => {
    setLoadingDetail(true);
    try {
      const detail = await api.getAnalyticsSessionDetail(sessionId);
      setSelectedDetail(detail);
    } finally {
      setLoadingDetail(false);
    }
  };

  const maxDailySessions = Math.max(1, ...(overview?.sessions_per_day.map((d) => d.sessions) || [1]));
  const maxStageLatency = Math.max(
    1,
    overview?.avg_stt_latency_ms || 0,
    overview?.avg_llm_first_token_ms || 0,
    overview?.avg_tts_first_audio_ms || 0,
    overview?.avg_e2e_latency_ms || 0
  );

  const stageBars = [
    { label: 'STT', value: overview?.avg_stt_latency_ms || 0, color: 'bg-emerald-400' },
    { label: 'LLM TTFT', value: overview?.avg_llm_first_token_ms || 0, color: 'bg-sky-400' },
    { label: 'TTS First', value: overview?.avg_tts_first_audio_ms || 0, color: 'bg-purple-400' },
    { label: 'E2E', value: overview?.avg_e2e_latency_ms || 0, color: 'bg-amber-400' },
  ];

  return (
    <div className="max-w-6xl mx-auto space-y-6 pb-12">
      <div className="border-b border-slate-800 pb-5">
        <div className="flex items-center gap-2 text-purple-400 text-xs font-semibold uppercase tracking-wider mb-1">
          <BarChart3 className="w-4 h-4" />
          Telemetry & Observability
        </div>
        <h1 className="text-2xl font-bold text-white tracking-tight">Call Analytics</h1>
        <p className="text-slate-400 text-sm mt-1">
          Session volume, stage-level latency averages, error counts, and full turn-by-turn transcripts.
        </p>
      </div>

      {/* Stat Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="p-5 rounded-2xl bg-slate-900/60 border border-slate-800">
          <div className="flex items-center justify-between text-xs text-slate-400 mb-2">
            <span>Total Sessions</span>
            <PhoneCall className="w-4 h-4 text-emerald-400" />
          </div>
          <p className="text-3xl font-extrabold text-white">{overview ? overview.total_sessions : '...'}</p>
        </div>
        <div className="p-5 rounded-2xl bg-slate-900/60 border border-slate-800">
          <div className="flex items-center justify-between text-xs text-slate-400 mb-2">
            <span>Total Minutes</span>
            <Clock className="w-4 h-4 text-sky-400" />
          </div>
          <p className="text-3xl font-extrabold text-white">{overview ? `${overview.total_minutes}m` : '...'}</p>
        </div>
        <div className="p-5 rounded-2xl bg-slate-900/60 border border-slate-800">
          <div className="flex items-center justify-between text-xs text-slate-400 mb-2">
            <span>Avg E2E Latency</span>
            <Activity className="w-4 h-4 text-amber-400" />
          </div>
          <p className="text-3xl font-extrabold text-white">{overview ? `${overview.avg_e2e_latency_ms} ms` : '...'}</p>
        </div>
        <div className="p-5 rounded-2xl bg-slate-900/60 border border-slate-800">
          <div className="flex items-center justify-between text-xs text-slate-400 mb-2">
            <span>Errors</span>
            <AlertTriangle className="w-4 h-4 text-rose-400" />
          </div>
          <p className="text-3xl font-extrabold text-white">{overview ? overview.error_count : '...'}</p>
          {overview?.error_breakdown && Object.keys(overview.error_breakdown).length > 0 && (
            <div className="flex flex-wrap gap-1 mt-2">
              {Object.entries(overview.error_breakdown).map(([code, cnt]) => (
                <span key={code} className="px-1.5 py-0.5 rounded bg-rose-500/10 text-rose-300 text-[10px] font-mono">
                  {code}: {cnt}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Sessions per Day (14 days) */}
        <div className="p-5 rounded-2xl bg-slate-900/60 border border-slate-800 space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-white">Sessions per Day (Last 14 Days)</h2>
            <span className="text-[11px] text-slate-500">Red = errors</span>
          </div>
          <div className="h-44 flex items-end gap-1.5 pt-4">
            {(overview?.sessions_per_day || []).map((day) => {
              const pct = Math.max(4, Math.round((day.sessions / maxDailySessions) * 100));
              const errPct = day.sessions > 0 ? Math.round((day.errors / day.sessions) * 100) : 0;
              return (
                <div key={day.date} className="flex-1 flex flex-col items-center gap-1 group">
                  <div className="w-full h-32 flex items-end justify-center relative">
                    <div
                      className="w-full max-w-[20px] rounded-t-md bg-sky-500/70 relative overflow-hidden transition-all"
                      style={{ height: `${day.sessions === 0 ? 4 : pct}%` }}
                      title={`${day.date}: ${day.sessions} sessions (${day.errors} errors)`}
                    >
                      {errPct > 0 && (
                        <div className="absolute bottom-0 inset-x-0 bg-rose-500" style={{ height: `${errPct}%` }} />
                      )}
                    </div>
                  </div>
                  <span className="text-[9px] font-mono text-slate-500">{day.date.slice(5)}</span>
                </div>
              );
            })}
          </div>
        </div>

        {/* Avg Latency per Stage */}
        <div className="p-5 rounded-2xl bg-slate-900/60 border border-slate-800 space-y-4">
          <h2 className="text-sm font-semibold text-white">Average Latency per Stage</h2>
          <div className="space-y-3 pt-1">
            {stageBars.map((bar) => (
              <div key={bar.label} className="space-y-1">
                <div className="flex justify-between text-xs">
                  <span className="text-slate-300 font-medium">{bar.label}</span>
                  <span className="font-mono text-slate-400">{bar.value} ms</span>
                </div>
                <div className="h-2.5 bg-slate-950 rounded-full overflow-hidden border border-slate-800">
                  <div
                    className={`h-full ${bar.color} transition-all`}
                    style={{ width: `${Math.min(100, Math.round((bar.value / maxStageLatency) * 100))}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Filters + Session History Table */}
      <div className="rounded-2xl bg-slate-900/60 border border-slate-800 overflow-hidden">
        <div className="p-4 border-b border-slate-800 flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-sm font-semibold text-white">Session History ({sessions.length})</h2>
          <div className="flex flex-wrap items-center gap-2">
            <select
              value={filterAgent}
              onChange={(e) => setFilterAgent(e.target.value)}
              className="px-3 py-1.5 bg-slate-950 border border-slate-800 rounded-lg text-xs text-white"
            >
              <option value="">All Agents</option>
              {agents.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
            <input
              type="date"
              value={filterDate}
              onChange={(e) => setFilterDate(e.target.value)}
              className="px-3 py-1.5 bg-slate-950 border border-slate-800 rounded-lg text-xs text-white"
            />
            <select
              value={filterStatus}
              onChange={(e) => setFilterStatus(e.target.value)}
              className="px-3 py-1.5 bg-slate-950 border border-slate-800 rounded-lg text-xs text-white"
            >
              <option value="">All Statuses</option>
              <option value="completed">completed</option>
              <option value="active">active</option>
              <option value="error">error</option>
            </select>
            <label className="inline-flex items-center gap-1.5 text-xs text-slate-300 cursor-pointer px-2">
              <input
                type="checkbox"
                checked={showEmpty}
                onChange={(e) => setShowEmpty(e.target.checked)}
                className="rounded border-slate-700 bg-slate-950 accent-sky-500"
              />
              Show empty sessions
            </label>
          </div>
        </div>

        {loading ? (
          <div className="p-10 text-center text-slate-500 flex items-center justify-center gap-2">
            <Loader2 className="w-4 h-4 animate-spin" /> Loading sessions...
          </div>
        ) : sessions.length === 0 ? (
          <div className="p-10 text-center text-slate-500 text-sm">No sessions match the selected filters.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-950/60 text-slate-400 uppercase text-[10px]">
                <tr>
                  <th className="px-4 py-3">Agent</th>
                  <th className="px-4 py-3">Started</th>
                  <th className="px-4 py-3">Duration</th>
                  <th className="px-4 py-3">Turns</th>
                  <th className="px-4 py-3">Avg Latency</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3 text-right">Transcript</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/70">
                {sessions.map((s) => (
                  <tr key={s.id} className="hover:bg-slate-800/30">
                    <td className="px-4 py-3 font-medium text-white">
                      {s.agent_name}
                      {s.is_public && (
                        <span className="ml-2 px-1.5 py-0.5 rounded bg-sky-500/10 text-sky-400 text-[10px]">
                          public
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-slate-400 font-mono">
                      {s.started_at ? new Date(s.started_at).toLocaleString() : '-'}
                    </td>
                    <td className="px-4 py-3 text-slate-300 font-mono">{s.duration_seconds}s</td>
                    <td className="px-4 py-3 text-slate-300">{s.total_turns}</td>
                    <td className="px-4 py-3 text-amber-300 font-mono">{s.avg_latency_ms} ms</td>
                    <td className="px-4 py-3">
                      <span
                        className={`px-2 py-0.5 rounded-full text-[10px] font-semibold ${
                          s.status === 'error' || s.error_count > 0
                            ? 'bg-rose-500/10 text-rose-400'
                            : s.status === 'active'
                              ? 'bg-sky-500/10 text-sky-400'
                              : 'bg-emerald-500/10 text-emerald-400'
                        }`}
                        title={s.last_error || undefined}
                      >
                        {s.status}
                        {s.error_count > 0 ? ` (${s.error_count} err)` : ''}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right">
                      <button
                        onClick={() => void openDetail(s.id)}
                        className="px-3 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 font-semibold"
                      >
                        Inspect
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Session Detail Modal */}
      {(selectedDetail || loadingDetail) && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="w-full max-w-3xl max-h-[88vh] rounded-2xl bg-slate-900 border border-slate-800 flex flex-col overflow-hidden shadow-2xl">
            <div className="px-6 py-4 border-b border-slate-800 flex items-center justify-between">
              <div>
                <h3 className="text-base font-bold text-white">
                  {selectedDetail ? `${selectedDetail.agent_name} — Session Transcript` : 'Loading session...'}
                </h3>
                {selectedDetail && (
                  <p className="text-xs text-slate-400 font-mono mt-0.5">
                    ID: {selectedDetail.id} • {selectedDetail.duration_seconds}s • {selectedDetail.status}
                  </p>
                )}
              </div>
              <button onClick={() => setSelectedDetail(null)} className="text-slate-400 hover:text-white">
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto p-6 space-y-4">
              {loadingDetail ? (
                <div className="py-12 text-center text-slate-400 flex items-center justify-center gap-2">
                  <Loader2 className="w-4 h-4 animate-spin" /> Loading transcript...
                </div>
              ) : (
                selectedDetail?.messages.map((m) => (
                  <div key={m.id} className="p-4 rounded-xl bg-slate-950/70 border border-slate-800 space-y-2">
                    <div className="flex items-center justify-between text-xs">
                      <span className="font-semibold uppercase flex items-center gap-1.5 text-slate-300">
                        {m.role === 'user' ? <Mic className="w-3.5 h-3.5 text-emerald-400" /> : <Bot className="w-3.5 h-3.5 text-sky-400" />}
                        {m.role}
                        {m.interrupted && (
                          <span className="px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-300 text-[10px]">
                            interrupted
                          </span>
                        )}
                      </span>
                      {m.role === 'assistant' && m.e2e_latency_ms > 0 && (
                        <span className="font-mono text-[11px] text-slate-400">
                          STT {m.stt_latency_ms}ms | LLM TTFT {m.llm_first_token_ms}ms | TTS {m.tts_first_audio_ms}ms | E2E {m.e2e_latency_ms}ms
                        </span>
                      )}
                    </div>
                    <p className="text-sm text-slate-200 whitespace-pre-wrap">{m.content}</p>
                    {m.rag_sources && m.rag_sources.length > 0 && (
                      <div className="text-[11px] text-sky-300 flex items-center gap-1.5 pt-1">
                        <Layers className="w-3.5 h-3.5" />
                        RAG: {m.rag_sources.map((r) => `${r.file} (${r.score})`).join(', ')}
                      </div>
                    )}
                    {m.tool_calls && m.tool_calls.length > 0 && (
                      <div className="text-[11px] text-amber-300 flex items-center gap-1.5 pt-1">
                        <Wrench className="w-3.5 h-3.5" />
                        Tools: {m.tool_calls.map((t) => t.name).join(', ')}
                      </div>
                    )}
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
