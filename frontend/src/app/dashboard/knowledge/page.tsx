'use client';

import { useEffect, useState, useCallback, useRef } from 'react';
import { api } from '@/lib/api';
import { Agent, KnowledgeDocument, RagChunkResult } from '@/types';
import {
  Upload,
  FileText,
  Trash2,
  Search,
  CheckCircle2,
  Clock,
  AlertCircle,
  Loader2,
  Bot,
  Layers,
  Sparkles,
} from 'lucide-react';

export default function KnowledgePage() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [selectedAgentId, setSelectedAgentId] = useState<string>('');
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [loadingDocs, setLoadingDocs] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // Query test state
  const [queryText, setQueryText] = useState('');
  const [querying, setQuerying] = useState(false);
  const [queryResults, setQueryResults] = useState<RagChunkResult[] | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    async function init() {
      try {
        const list = await api.listAgents();
        setAgents(list);
        if (list.length > 0) {
          setSelectedAgentId(list[0].id);
        }
      } catch (err: any) {
        setError(err.message || 'Failed to load agents');
      }
    }
    init();
  }, []);

  const fetchDocuments = useCallback(async (agentId: string) => {
    if (!agentId) return;
    setLoadingDocs(true);
    try {
      const docs = await api.listKnowledge(agentId);
      setDocuments(docs);
    } catch (err: any) {
      setError(err.message || 'Failed to load documents');
    } finally {
      setLoadingDocs(false);
    }
  }, []);

  useEffect(() => {
    if (selectedAgentId) {
      setQueryResults(null);
      void fetchDocuments(selectedAgentId);
    }
  }, [selectedAgentId, fetchDocuments]);

  // Poll while any document is still processing
  useEffect(() => {
    const hasProcessing = documents.some((d) => d.status === 'processing');
    if (!hasProcessing || !selectedAgentId) return;
    const timer = setInterval(() => {
      void fetchDocuments(selectedAgentId);
    }, 2000);
    return () => clearInterval(timer);
  }, [documents, selectedAgentId, fetchDocuments]);

  const handleUploadFile = async (file: File) => {
    if (!selectedAgentId) {
      setError('Please select an agent first.');
      return;
    }
    setError(null);
    setSuccessMsg(null);
    setUploading(true);
    try {
      const created = await api.uploadKnowledge(selectedAgentId, file);
      setSuccessMsg(`Uploaded "${created.filename}". Indexing in background...`);
      await fetchDocuments(selectedAgentId);
    } catch (err: any) {
      setError(err.message || 'Upload failed');
    } finally {
      setUploading(false);
    }
  };

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(false);
    const file = e.dataTransfer.files?.[0];
    if (file) void handleUploadFile(file);
  };

  const handleDelete = async (docId: string, filename: string) => {
    setError(null);
    try {
      await api.deleteKnowledge(docId);
      setDocuments((prev) => prev.filter((d) => d.id !== docId));
      setSuccessMsg(`Deleted "${filename}".`);
    } catch (err: any) {
      setError(err.message || 'Delete failed');
    }
  };

  const handleQueryTest = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedAgentId || !queryText.trim()) return;
    setError(null);
    setQuerying(true);
    try {
      const res = await api.queryTestKnowledge(selectedAgentId, queryText.trim(), 4, 0.35);
      setQueryResults(res.results);
    } catch (err: any) {
      setError(err.message || 'Query test failed');
    } finally {
      setQuerying(false);
    }
  };

  const formatBytes = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
  };

  return (
    <div className="max-w-6xl mx-auto space-y-6 pb-12">
      {/* Header & Agent Selector */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-800 pb-5">
        <div>
          <div className="flex items-center gap-2 text-sky-400 text-xs font-semibold uppercase tracking-wider mb-1">
            <Layers className="w-4 h-4" />
            Knowledge Base & RAG
          </div>
          <h1 className="text-2xl font-bold text-white tracking-tight">Agent Knowledge Documents</h1>
          <p className="text-slate-400 text-sm mt-1">
            Upload PDF, TXT, or DOCX files. Chunks are embedded with Gemini <code className="text-sky-300">gemini-embedding-001</code> (768-dim) into pgvector HNSW.
          </p>
        </div>

        <div className="flex items-center gap-2 min-w-[260px]">
          <Bot className="w-4 h-4 text-slate-400 shrink-0" />
          <select
            value={selectedAgentId}
            onChange={(e) => setSelectedAgentId(e.target.value)}
            className="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-xl text-sm text-white focus:outline-none focus:border-sky-500"
          >
            {agents.length === 0 ? (
              <option value="">No agents found</option>
            ) : (
              agents.map((ag) => (
                <option key={ag.id} value={ag.id}>
                  {ag.name} ({ag.llm_model})
                </option>
              ))
            )}
          </select>
        </div>
      </div>

      {error && (
        <div className="p-3.5 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-300 text-sm flex items-center gap-2">
          <AlertCircle className="w-4 h-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {successMsg && (
        <div className="p-3.5 rounded-xl bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 text-sm flex items-center gap-2">
          <CheckCircle2 className="w-4 h-4 shrink-0" />
          <span>{successMsg}</span>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left: Upload + Document List */}
        <div className="lg:col-span-7 space-y-6">
          {/* Drag-and-drop Upload Zone */}
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setIsDragging(true);
            }}
            onDragLeave={() => setIsDragging(false)}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            className={`cursor-pointer rounded-2xl border-2 border-dashed p-8 text-center transition ${
              isDragging
                ? 'border-sky-400 bg-sky-500/10'
                : 'border-slate-800 bg-slate-900/40 hover:border-slate-700 hover:bg-slate-900/70'
            }`}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,.txt,.docx"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) void handleUploadFile(file);
                e.target.value = '';
              }}
            />
            <div className="w-12 h-12 rounded-xl bg-sky-500/10 border border-sky-500/30 flex items-center justify-center text-sky-400 mx-auto mb-3">
              {uploading ? <Loader2 className="w-6 h-6 animate-spin" /> : <Upload className="w-6 h-6" />}
            </div>
            <p className="text-sm font-semibold text-white">
              {uploading ? 'Uploading & starting indexing...' : 'Drag & drop a file here, or click to browse'}
            </p>
            <p className="text-xs text-slate-400 mt-1">Supported formats: PDF, TXT, DOCX (max 10 MB)</p>
          </div>

          {/* Document List */}
          <div className="rounded-2xl border border-slate-800 bg-slate-900/50 overflow-hidden">
            <div className="px-5 py-3.5 border-b border-slate-800 flex items-center justify-between">
              <h2 className="text-sm font-semibold text-white flex items-center gap-2">
                <FileText className="w-4 h-4 text-sky-400" />
                Indexed Documents ({documents.length})
              </h2>
              {loadingDocs && <Loader2 className="w-4 h-4 text-slate-400 animate-spin" />}
            </div>

            {documents.length === 0 ? (
              <div className="p-8 text-center text-sm text-slate-500">
                No documents uploaded for this agent yet.
              </div>
            ) : (
              <div className="divide-y divide-slate-800/80">
                {documents.map((doc) => (
                  <div key={doc.id} className="px-5 py-3.5 flex items-center justify-between gap-4">
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-white truncate">{doc.filename}</p>
                      <p className="text-xs text-slate-400 mt-0.5">
                        {doc.file_type.toUpperCase()} • {formatBytes(doc.file_size)} • {doc.chunk_count} chunks
                      </p>
                    </div>
                    <div className="flex items-center gap-3 shrink-0">
                      {doc.status === 'indexed' && (
                        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
                          <CheckCircle2 className="w-3 h-3" /> indexed
                        </span>
                      )}
                      {doc.status === 'processing' && (
                        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-amber-500/10 text-amber-400 border border-amber-500/30">
                          <Clock className="w-3 h-3 animate-pulse" /> processing
                        </span>
                      )}
                      {doc.status === 'failed' && (
                        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-rose-500/10 text-rose-400 border border-rose-500/30">
                          <AlertCircle className="w-3 h-3" /> failed
                        </span>
                      )}
                      <button
                        onClick={() => void handleDelete(doc.id, doc.filename)}
                        className="p-1.5 rounded-lg text-slate-400 hover:text-rose-400 hover:bg-rose-500/10 transition"
                        title="Delete document"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Right: Query-Test Box */}
        <div className="lg:col-span-5">
          <div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-5 space-y-4">
            <div>
              <h2 className="text-sm font-semibold text-white flex items-center gap-2">
                <Sparkles className="w-4 h-4 text-sky-400" />
                RAG Query Test
              </h2>
              <p className="text-xs text-slate-400 mt-1">
                Test semantic retrieval against this agent&apos;s indexed chunks before calling in the Voice Playground.
              </p>
            </div>

            <form onSubmit={handleQueryTest} className="space-y-3">
              <div className="flex gap-2">
                <input
                  type="text"
                  value={queryText}
                  onChange={(e) => setQueryText(e.target.value)}
                  placeholder="Ask a question about your uploaded docs..."
                  className="flex-1 px-3.5 py-2 bg-slate-950 border border-slate-800 rounded-xl text-sm text-white placeholder-slate-500 focus:outline-none focus:border-sky-500"
                />
                <button
                  type="submit"
                  disabled={querying || !selectedAgentId || !queryText.trim()}
                  className="px-4 py-2 rounded-xl bg-sky-600 hover:bg-sky-500 disabled:opacity-50 text-white text-sm font-semibold flex items-center gap-1.5 transition"
                >
                  {querying ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
                  Search
                </button>
              </div>
            </form>

            {queryResults !== null && (
              <div className="space-y-3 pt-2">
                <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                  Top Matching Chunks ({queryResults.length})
                </p>
                {queryResults.length === 0 ? (
                  <p className="text-xs text-slate-500 py-4 text-center border border-slate-800 rounded-xl">
                    No chunks matched above similarity threshold (0.35).
                  </p>
                ) : (
                  <div className="space-y-2.5 max-h-[440px] overflow-y-auto pr-1">
                    {queryResults.map((chunk, idx) => (
                      <div
                        key={`${chunk.document_id}-${chunk.chunk_index}-${idx}`}
                        className="p-3 rounded-xl bg-slate-950 border border-slate-800 space-y-1.5"
                      >
                        <div className="flex items-center justify-between text-xs">
                          <span className="font-semibold text-sky-300 truncate">
                            {chunk.filename} (chunk #{chunk.chunk_index})
                          </span>
                          <span className="px-2 py-0.5 rounded-md bg-emerald-500/10 text-emerald-400 font-mono">
                            score: {chunk.score.toFixed(3)}
                          </span>
                        </div>
                        <p className="text-xs text-slate-300 leading-relaxed whitespace-pre-wrap">
                          {chunk.content}
                        </p>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
