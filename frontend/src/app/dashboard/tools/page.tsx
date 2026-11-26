'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import { Agent, BuiltinToolPreset, ToolItem } from '@/types';
import {
  Wrench,
  Plus,
  Trash2,
  Edit3,
  ShieldAlert,
  Globe,
  Cpu,
  CheckCircle2,
  AlertCircle,
  Loader2,
  Bot,
  X,
} from 'lucide-react';

const DEFAULT_SCHEMA = JSON.stringify(
  {
    type: 'object',
    properties: {
      query: { type: 'string', description: 'Input parameter' },
    },
    required: ['query'],
  },
  null,
  2
);

export default function ToolsPage() {
  const [tools, setTools] = useState<ToolItem[]>([]);
  const [builtins, setBuiltins] = useState<BuiltinToolPreset[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  // Editor modal state
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [executionType, setExecutionType] = useState<'mock' | 'webhook' | 'built_in'>('mock');
  const [isSensitive, setIsSensitive] = useState(false);
  const [parametersSchema, setParametersSchema] = useState(DEFAULT_SCHEMA);
  const [schemaError, setSchemaError] = useState<string | null>(null);
  const [webhookUrl, setWebhookUrl] = useState('');
  const [webhookMethod, setWebhookMethod] = useState('POST');
  const [webhookHeaders, setWebhookHeaders] = useState('{}');
  const [webhookBodyTemplate, setWebhookBodyTemplate] = useState('');
  const [saving, setSaving] = useState(false);

  const loadAll = async () => {
    setLoading(true);
    try {
      const [tList, bList, aList] = await Promise.all([
        api.listTools(),
        api.listBuiltinTools(),
        api.listAgents(),
      ]);
      setTools(tList);
      setBuiltins(bList);
      setAgents(aList);
    } catch (err: any) {
      setError(err.message || 'Failed to load tools');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadAll();
  }, []);

  const validateSchemaText = (txt: string): boolean => {
    try {
      const parsed = JSON.parse(txt);
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        setSchemaError('Schema must be a JSON object.');
        return false;
      }
      setSchemaError(null);
      return true;
    } catch (e: any) {
      setSchemaError(`Invalid JSON: ${e.message}`);
      return false;
    }
  };

  const openNewForm = (preset?: BuiltinToolPreset) => {
    setEditingId(null);
    setName(preset ? preset.name : '');
    setDescription(preset ? preset.description : '');
    setExecutionType(preset ? 'built_in' : 'mock');
    setIsSensitive(preset ? preset.is_sensitive : false);
    setParametersSchema(
      preset ? JSON.stringify(JSON.parse(preset.parameters_schema), null, 2) : DEFAULT_SCHEMA
    );
    setWebhookUrl('');
    setWebhookMethod('POST');
    setWebhookHeaders('{}');
    setWebhookBodyTemplate('');
    setSchemaError(null);
    setShowForm(true);
  };

  const openEditForm = (tool: ToolItem) => {
    setEditingId(tool.id);
    setName(tool.name);
    setDescription(tool.description);
    setExecutionType(tool.execution_type);
    setIsSensitive(tool.is_sensitive);
    try {
      setParametersSchema(JSON.stringify(JSON.parse(tool.parameters_schema), null, 2));
    } catch {
      setParametersSchema(tool.parameters_schema);
    }
    setWebhookUrl(tool.webhook_url || '');
    setWebhookMethod(tool.webhook_method || 'POST');
    setWebhookHeaders(tool.webhook_headers || '{}');
    setWebhookBodyTemplate(tool.webhook_body_template || '');
    setSchemaError(null);
    setShowForm(true);
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!validateSchemaText(parametersSchema)) return;
    setError(null);
    setSuccess(null);
    setSaving(true);
    try {
      const payload = {
        name: name.trim(),
        description: description.trim(),
        execution_type: executionType,
        is_sensitive: isSensitive,
        parameters_schema: parametersSchema,
        webhook_url: executionType === 'webhook' ? webhookUrl.trim() : undefined,
        webhook_method: executionType === 'webhook' ? webhookMethod : 'POST',
        webhook_headers: executionType === 'webhook' ? webhookHeaders : '{}',
        webhook_body_template: executionType === 'webhook' ? webhookBodyTemplate : undefined,
      };
      if (editingId) {
        await api.updateTool(editingId, payload);
        setSuccess(`Updated tool "${name.trim()}".`);
      } else {
        await api.createTool(payload);
        setSuccess(`Created tool "${name.trim()}".`);
      }
      setShowForm(false);
      await loadAll();
    } catch (err: any) {
      setError(err.message || 'Failed to save tool');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (tool: ToolItem) => {
    setError(null);
    try {
      await api.deleteTool(tool.id);
      setTools((prev) => prev.filter((t) => t.id !== tool.id));
      setSuccess(`Deleted tool "${tool.name}".`);
    } catch (err: any) {
      setError(err.message || 'Failed to delete tool');
    }
  };

  const toggleAgentAssignment = async (tool: ToolItem, agentId: string) => {
    const assigned = tool.agent_ids.includes(agentId);
    try {
      const updated = assigned
        ? await api.unassignToolFromAgent(tool.id, agentId)
        : await api.assignToolToAgent(tool.id, agentId);
      setTools((prev) => prev.map((t) => (t.id === tool.id ? updated : t)));
    } catch (err: any) {
      setError(err.message || 'Failed to update assignment');
    }
  };

  return (
    <div className="max-w-6xl mx-auto space-y-6 pb-12">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-800 pb-5">
        <div>
          <div className="flex items-center gap-2 text-amber-400 text-xs font-semibold uppercase tracking-wider mb-1">
            <Wrench className="w-4 h-4" />
            Function Calling & Webhooks
          </div>
          <h1 className="text-2xl font-bold text-white tracking-tight">Agent Tools</h1>
          <p className="text-slate-400 text-sm mt-1">
            Define JSON-schema tools, SSRF-protected HTTP webhooks, and sensitive confirmation gates for your voice & text agents.
          </p>
        </div>
        <button
          onClick={() => openNewForm()}
          className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-amber-500 hover:bg-amber-600 text-slate-950 font-semibold text-sm transition"
        >
          <Plus className="w-4 h-4" />
          New Custom Tool
        </button>
      </div>

      {error && (
        <div className="p-3.5 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-300 text-sm flex items-center gap-2">
          <AlertCircle className="w-4 h-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}
      {success && (
        <div className="p-3.5 rounded-xl bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 text-sm flex items-center gap-2">
          <CheckCircle2 className="w-4 h-4 shrink-0" />
          <span>{success}</span>
        </div>
      )}

      {/* Read-only Built-in Presets */}
      <div className="space-y-3">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-400">
          Built-in Presets (Read-Only Templates)
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          {builtins.map((preset) => (
            <div
              key={preset.name}
              className="p-4 rounded-2xl bg-slate-900/50 border border-slate-800 flex flex-col justify-between gap-3"
            >
              <div>
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-sm font-bold text-white">{preset.name}</span>
                  {preset.is_sensitive && (
                    <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-rose-500/10 text-rose-400 border border-rose-500/30">
                      Sensitive
                    </span>
                  )}
                </div>
                <p className="text-xs text-slate-400 mt-1.5 line-clamp-2">{preset.description}</p>
              </div>
              <button
                onClick={() => openNewForm(preset)}
                className="w-full py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold transition"
              >
                + Add Preset to My Tools
              </button>
            </div>
          ))}
        </div>
      </div>

      {/* User Tools List */}
      <div className="space-y-3">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-400">
          Your Configured Tools ({tools.length})
        </h2>
        {loading ? (
          <div className="p-10 text-center text-slate-500 flex items-center justify-center gap-2">
            <Loader2 className="w-4 h-4 animate-spin" /> Loading tools...
          </div>
        ) : tools.length === 0 ? (
          <div className="p-10 text-center rounded-2xl border border-dashed border-slate-800 text-slate-500 text-sm">
            No tools configured yet. Add a built-in preset above or create a custom tool.
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {tools.map((tool) => (
              <div key={tool.id} className="p-5 rounded-2xl bg-slate-900/60 border border-slate-800 space-y-4">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-base font-bold text-white">{tool.name}</span>
                      <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase bg-sky-500/10 text-sky-300 border border-sky-500/30">
                        {tool.execution_type}
                      </span>
                      {tool.is_sensitive && (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-rose-500/10 text-rose-400 border border-rose-500/30">
                          <ShieldAlert className="w-3 h-3" /> Sensitive
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-slate-400 mt-1">{tool.description}</p>
                    {tool.execution_type === 'webhook' && tool.webhook_url && (
                      <p className="text-[11px] font-mono text-amber-300 mt-1 flex items-center gap-1 truncate">
                        <Globe className="w-3 h-3 shrink-0" />
                        {tool.webhook_method || 'POST'} {tool.webhook_url}
                      </p>
                    )}
                  </div>
                  <div className="flex items-center gap-1 shrink-0">
                    <button
                      onClick={() => openEditForm(tool)}
                      className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition"
                    >
                      <Edit3 className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() => void handleDelete(tool)}
                      className="p-1.5 rounded-lg text-slate-400 hover:text-rose-400 hover:bg-rose-500/10 transition"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>

                {/* Assign to Agents */}
                <div className="pt-3 border-t border-slate-800/80">
                  <span className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold flex items-center gap-1 mb-2">
                    <Bot className="w-3 h-3" /> Assigned Agents
                  </span>
                  {agents.length === 0 ? (
                    <p className="text-xs text-slate-500">No agents created yet.</p>
                  ) : (
                    <div className="flex flex-wrap gap-1.5">
                      {agents.map((ag) => {
                        const active = tool.agent_ids.includes(ag.id);
                        return (
                          <button
                            key={ag.id}
                            type="button"
                            onClick={() => void toggleAgentAssignment(tool, ag.id)}
                            className={`px-2.5 py-1 rounded-lg text-xs font-medium border transition ${
                              active
                                ? 'bg-emerald-500/15 border-emerald-500/40 text-emerald-300'
                                : 'bg-slate-950 border-slate-800 text-slate-400 hover:text-white'
                            }`}
                          >
                            {active ? '✓ ' : '+ '}
                            {ag.name}
                          </button>
                        );
                      })}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Create / Edit Modal */}
      {showForm && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="w-full max-w-2xl rounded-2xl bg-slate-900 border border-slate-800 shadow-2xl overflow-hidden max-h-[90vh] flex flex-col">
            <div className="px-6 py-4 border-b border-slate-800 flex items-center justify-between">
              <h3 className="text-base font-bold text-white flex items-center gap-2">
                <Cpu className="w-4 h-4 text-amber-400" />
                {editingId ? 'Edit Tool' : 'Create Function Tool'}
              </h3>
              <button onClick={() => setShowForm(false)} className="text-slate-400 hover:text-white">
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleSave} className="p-6 space-y-4 overflow-y-auto">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-semibold text-slate-300 uppercase mb-1.5">Tool Name</label>
                  <input
                    required
                    pattern="^[a-zA-Z_][a-zA-Z0-9_]*$"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="get_order_status"
                    className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-xl text-sm font-mono text-white"
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-slate-300 uppercase mb-1.5">Execution Type</label>
                  <select
                    value={executionType}
                    onChange={(e) => setExecutionType(e.target.value as any)}
                    className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-xl text-sm text-white"
                  >
                    <option value="mock">Mock</option>
                    <option value="webhook">HTTP Webhook (SSRF-protected)</option>
                    <option value="built_in">Built-in</option>
                  </select>
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-300 uppercase mb-1.5">Description</label>
                <input
                  required
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="Describe when the LLM should call this tool..."
                  className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-xl text-sm text-white"
                />
              </div>

              {executionType === 'webhook' && (
                <div className="p-4 rounded-xl bg-slate-950/70 border border-slate-800 space-y-3">
                  <div className="grid grid-cols-4 gap-2">
                    <div>
                      <label className="block text-[11px] text-slate-400 mb-1">Method</label>
                      <select
                        value={webhookMethod}
                        onChange={(e) => setWebhookMethod(e.target.value)}
                        className="w-full px-2.5 py-2 bg-slate-900 border border-slate-800 rounded-lg text-xs text-white"
                      >
                        <option value="POST">POST</option>
                        <option value="GET">GET</option>
                        <option value="PUT">PUT</option>
                        <option value="PATCH">PATCH</option>
                      </select>
                    </div>
                    <div className="col-span-3">
                      <label className="block text-[11px] text-slate-400 mb-1">Webhook URL (https://)</label>
                      <input
                        required
                        value={webhookUrl}
                        onChange={(e) => setWebhookUrl(e.target.value)}
                        placeholder="https://api.example.com/webhook"
                        className="w-full px-3 py-2 bg-slate-900 border border-slate-800 rounded-lg text-xs font-mono text-white"
                      />
                    </div>
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <div>
                      <label className="block text-[11px] text-slate-400 mb-1">Headers (JSON)</label>
                      <input
                        value={webhookHeaders}
                        onChange={(e) => setWebhookHeaders(e.target.value)}
                        className="w-full px-3 py-2 bg-slate-900 border border-slate-800 rounded-lg text-xs font-mono text-white"
                      />
                    </div>
                    <div>
                      <label className="block text-[11px] text-slate-400 mb-1">Body Template (optional)</label>
                      <input
                        value={webhookBodyTemplate}
                        onChange={(e) => setWebhookBodyTemplate(e.target.value)}
                        placeholder='{"query": "{{query}}"}'
                        className="w-full px-3 py-2 bg-slate-900 border border-slate-800 rounded-lg text-xs font-mono text-white"
                      />
                    </div>
                  </div>
                </div>
              )}

              <div>
                <div className="flex items-center justify-between mb-1.5">
                  <label className="text-xs font-semibold text-slate-300 uppercase">Parameters JSON Schema</label>
                  {schemaError && <span className="text-xs text-rose-400">{schemaError}</span>}
                </div>
                <textarea
                  rows={7}
                  value={parametersSchema}
                  onChange={(e) => {
                    setParametersSchema(e.target.value);
                    validateSchemaText(e.target.value);
                  }}
                  className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-xl text-xs font-mono text-emerald-300"
                />
              </div>

              <label className="flex items-center gap-2.5 text-sm text-slate-200 cursor-pointer">
                <input
                  type="checkbox"
                  checked={isSensitive}
                  onChange={(e) => setIsSensitive(e.target.checked)}
                  className="rounded border-slate-700 bg-slate-950 accent-rose-500"
                />
                <span>Sensitive tool (require user Confirm / Cancel in Playground before running)</span>
              </label>

              <div className="flex justify-end gap-3 pt-2 border-t border-slate-800">
                <button
                  type="button"
                  onClick={() => setShowForm(false)}
                  className="px-4 py-2 rounded-xl bg-slate-800 text-slate-300 text-sm font-semibold"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={saving || !!schemaError}
                  className="px-5 py-2 rounded-xl bg-amber-500 hover:bg-amber-600 disabled:opacity-50 text-slate-950 text-sm font-semibold"
                >
                  {saving ? 'Saving...' : editingId ? 'Save Changes' : 'Create Tool'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
