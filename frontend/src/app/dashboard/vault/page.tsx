'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import { ApiKeyItem } from '@/types';
import { Key, ShieldCheck, Plus, Trash2, Loader2, Lock, CheckCircle2 } from 'lucide-react';

export default function VaultPage() {
  const [keys, setKeys] = useState<ApiKeyItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [provider, setProvider] = useState('gemini');
  const [apiKey, setApiKey] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const fetchKeys = async () => {
    try {
      const data = await api.listKeys();
      setKeys(data);
    } catch (err: any) {
      setError(err.message || 'Failed to load keys');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchKeys();
  }, []);

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!apiKey.trim()) return;

    setSaving(true);
    setError(null);
    setSuccess(null);

    try {
      const saved = await api.saveKey(provider, apiKey.trim());
      setSuccess(`API Key for ${provider} encrypted & stored securely.`);
      setApiKey('');
      fetchKeys();
      setTimeout(() => setSuccess(null), 3000);
    } catch (err: any) {
      setError(err.message || 'Failed to store key');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (prov: string) => {
    if (!confirm(`Delete encrypted key for ${prov}?`)) return;
    try {
      await api.deleteKey(prov);
      setKeys((prev) => prev.filter((k) => k.provider !== prov));
    } catch (err: any) {
      alert(err.message || 'Failed to delete key');
    }
  };

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      {/* Header */}
      <div>
        <div className="inline-flex items-center gap-2 px-2.5 py-0.5 rounded-full border border-sky-500/30 bg-sky-500/10 text-sky-400 text-xs font-medium mb-2">
          <ShieldCheck className="w-3.5 h-3.5" />
          Fernet AES-256 Key Vault
        </div>
        <h1 className="text-2xl font-bold text-white tracking-tight">API Key Secrets Vault</h1>
        <p className="text-slate-400 text-sm mt-1">
          Store your proprietary AI credentials. Keys are encrypted at rest in the database and never exposed in cleartext.
        </p>
      </div>

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

      {/* Add / Update Key Card */}
      <div className="p-6 rounded-2xl bg-slate-900/60 border border-slate-800 space-y-4">
        <div className="flex items-center gap-2 text-white font-semibold text-base border-b border-slate-800/80 pb-3">
          <Key className="w-5 h-5 text-emerald-400" />
          Add or Update Provider Secret
        </div>

        <form onSubmit={handleSave} className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div>
              <label className="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-2">
                Provider
              </label>
              <select
                value={provider}
                onChange={(e) => setProvider(e.target.value)}
                className="w-full px-4 py-2.5 bg-slate-950 border border-slate-800 rounded-lg text-white text-sm focus:outline-none focus:border-emerald-500"
              >
                <option value="gemini">Google Gemini</option>
                <option value="openai">OpenAI</option>
                <option value="elevenlabs">ElevenLabs</option>
                <option value="deepgram">Deepgram</option>
              </select>
            </div>

            <div className="sm:col-span-2">
              <label className="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-2">
                API Key Secret
              </label>
              <div className="relative">
                <Lock className="w-4 h-4 absolute left-3 top-3 text-slate-500" />
                <input
                  type="password"
                  required
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder="Paste your secret key here (e.g. sk-... or AIza...)"
                  className="w-full pl-10 pr-4 py-2.5 bg-slate-950 border border-slate-800 rounded-lg text-white font-mono text-sm placeholder-slate-600 focus:outline-none focus:border-emerald-500 transition"
                />
              </div>
            </div>
          </div>

          <div className="flex justify-end pt-2">
            <button
              type="submit"
              disabled={saving}
              className="px-5 py-2.5 rounded-xl bg-emerald-500 hover:bg-emerald-600 text-slate-950 font-semibold text-sm transition flex items-center gap-2 shadow-lg shadow-emerald-500/20 disabled:opacity-50"
            >
              {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <><Plus className="w-4 h-4" /> Encrypt & Save Key</>}
            </button>
          </div>
        </form>
      </div>

      {/* Configured Keys List */}
      <div className="p-6 rounded-2xl bg-slate-900/60 border border-slate-800 space-y-4">
        <h2 className="text-base font-bold text-white tracking-tight">Active Provider Vault Keys</h2>

        {loading ? (
          <div className="p-8 text-center text-slate-500">Loading vault keys...</div>
        ) : keys.length === 0 ? (
          <div className="p-8 text-center text-slate-500 text-sm">
            No API keys stored yet. You can still use platform fallback keys or add your own above.
          </div>
        ) : (
          <div className="space-y-3">
            {keys.map((k) => (
              <div
                key={k.id}
                className="flex items-center justify-between p-4 rounded-xl bg-slate-950/60 border border-slate-800/60"
              >
                <div className="flex items-center gap-3">
                  <div className="w-8 h-8 rounded-lg bg-sky-500/10 border border-sky-500/30 flex items-center justify-center text-sky-400">
                    <CheckCircle2 className="w-4 h-4" />
                  </div>
                  <div>
                    <h4 className="font-semibold text-white text-sm capitalize">{k.provider}</h4>
                    <p className="font-mono text-xs text-slate-400">{k.masked_key}</p>
                  </div>
                </div>

                <button
                  onClick={() => handleDelete(k.provider)}
                  className="p-2 rounded-lg text-slate-400 hover:text-red-400 hover:bg-red-500/10 transition"
                  title="Delete Key"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
