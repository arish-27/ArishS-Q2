'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import { api } from '@/lib/api';
import { GaplessAudioPlayer } from '@/lib/audioQueue';
import { Agent } from '@/types';
import {
  Mic,
  MicOff,
  PhoneCall,
  PhoneOff,
  ArrowLeft,
  Bot,
  Activity,
  Clock,
  Zap,
  Volume2,
  Sliders,
  AlertCircle,
  Terminal,
  Send,
  Square,
  Key,
} from 'lucide-react';

type OrchestratorState = 'IDLE' | 'LISTENING' | 'THINKING' | 'SPEAKING';

interface TranscriptItem {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  streaming?: boolean;
  interrupted?: boolean;
  metrics?: {
    stt_latency_ms?: number;
    llm_first_token_ms?: number;
    tts_first_audio_ms?: number;
    e2e_latency_ms?: number;
    audio_duration_ms?: number;
  };
}

interface RagSourceItem {
  file: string;
  score: number;
  chunk_index: number;
}

interface ToolCallLog {
  name: string;
  arguments: Record<string, unknown>;
  result: Record<string, unknown>;
  duration_ms: number;
}

interface PendingConfirm {
  confirm_id: string;
  tool_name: string;
  arguments: Record<string, unknown>;
}

interface DebugEvent {
  id: string;
  time: string;
  type: string;
  summary: string;
}

const NOISE_PRESETS = {
  low: { speech_start_threshold: 0.4, speech_end_threshold: 0.25, energy_multiplier: 1.5, min_speech_ms: 120 },
  medium: { speech_start_threshold: 0.5, speech_end_threshold: 0.35, energy_multiplier: 2.0, min_speech_ms: 150 },
  high: { speech_start_threshold: 0.7, speech_end_threshold: 0.5, energy_multiplier: 2.5, min_speech_ms: 200 },
} as const;

const WS_BASE_URL = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000/api/v1/voice/stream';

export default function VoicePlaygroundPage() {
  const params = useParams();
  const agentId = params.id as string;

  const [agent, setAgent] = useState<Agent | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Voice connection & state machine
  const [isConnected, setIsConnected] = useState(false);
  const [isCalling, setIsCalling] = useState(false);
  const [isMuted, setIsMuted] = useState(false);
  const [voiceState, setVoiceState] = useState<OrchestratorState>('IDLE');
  const [vadSpeechActive, setVadSpeechActive] = useState(false);
  const [vadProb, setVadProb] = useState(0);
  const [noiseSensitivity, setNoiseSensitivity] = useState<'low' | 'medium' | 'high'>('medium');
  const [micLevel, setMicLevel] = useState(0);
  const [silenceThresholdMs, setSilenceThresholdMs] = useState(550);
  const [runtimeInfo, setRuntimeInfo] = useState<{
    sessionId?: string;
    rateLimiterBackend?: string;
    vadBackend?: string;
    maxSessionSeconds?: number;
  }>({});
  const [wsError, setWsError] = useState<{ code?: string; message: string } | null>(null);

  // Transcripts & debug logs
  const [transcripts, setTranscripts] = useState<TranscriptItem[]>([]);
  const [ragSources, setRagSources] = useState<RagSourceItem[]>([]);
  const [toolCalls, setToolCalls] = useState<ToolCallLog[]>([]);
  const [pendingConfirm, setPendingConfirm] = useState<PendingConfirm | null>(null);
  const [debugLogs, setDebugLogs] = useState<DebugEvent[]>([]);
  const [showDebug, setShowDebug] = useState(true);

  // Audio & Socket refs
  const wsRef = useRef<WebSocket | null>(null);
  const captureCtxRef = useRef<AudioContext | null>(null);
  const workletNodeRef = useRef<AudioWorkletNode | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const playerRef = useRef<GaplessAudioPlayer | null>(null);
  const sentenceChunksRef = useRef<Uint8Array[]>([]);
  const activeStreamMsgIdRef = useRef<string | null>(null);
  const lastUserMsgIdRef = useRef<string | null>(null);
  const transcriptsEndRef = useRef<HTMLDivElement>(null);

  const pushDebug = useCallback((type: string, summary: string) => {
    const time = new Date().toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
    setDebugLogs((prev) => [{ id: `${Date.now()}-${Math.random()}`, time, type, summary }, ...prev.slice(0, 49)]);
  }, []);

  useEffect(() => {
    async function fetchAgent() {
      try {
        const data = await api.getAgent(agentId);
        setAgent(data);
      } catch (err: any) {
        setLoadError(err.message || 'Failed to load agent');
      } finally {
        setLoading(false);
      }
    }
    fetchAgent();
  }, [agentId]);

  useEffect(() => {
    transcriptsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [transcripts]);

  const cleanupCall = useCallback(async () => {
    setIsCalling(false);
    setIsConnected(false);
    setVadSpeechActive(false);
    setMicLevel(0);
    setVoiceState('IDLE');

    if (workletNodeRef.current) {
      try {
        workletNodeRef.current.disconnect();
      } catch {
        // ignore
      }
      workletNodeRef.current = null;
    }

    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach((t) => t.stop());
      mediaStreamRef.current = null;
    }

    if (captureCtxRef.current && captureCtxRef.current.state !== 'closed') {
      await captureCtxRef.current.close().catch(() => {});
      captureCtxRef.current = null;
    }

    if (playerRef.current) {
      playerRef.current.stopAndClear();
    }

    if (wsRef.current) {
      try {
        if (wsRef.current.readyState === WebSocket.OPEN) {
          wsRef.current.send(JSON.stringify({ type: 'stop' }));
        }
        wsRef.current.close();
      } catch {
        // ignore
      }
      wsRef.current = null;
    }
  }, []);

  useEffect(() => {
    return () => {
      void cleanupCall();
      void playerRef.current?.close();
    };
  }, [cleanupCall]);

  const startCall = async () => {
    setWsError(null);
    const token = api.getToken();
    if (!token) {
      setWsError({ code: 'AUTH', message: 'Not authenticated. Please sign in again.' });
      return;
    }

    // Warm up Web Audio playback context during user click gesture
    if (!playerRef.current) {
      playerRef.current = new GaplessAudioPlayer();
    }
    playerRef.current.warmup();

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          channelCount: 1,
        },
      });
      mediaStreamRef.current = stream;

      const wsUrl = `${WS_BASE_URL}/${agentId}?token=${encodeURIComponent(token)}`;
      const ws = new WebSocket(wsUrl);
      ws.binaryType = 'arraybuffer';
      wsRef.current = ws;
      setIsCalling(true);

      ws.onopen = async () => {
        setIsConnected(true);
        pushDebug('ws.open', 'WebSocket connected');

        try {
          const AudioCtx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
          const captureCtx = new AudioCtx();
          captureCtxRef.current = captureCtx;
          await captureCtx.audioWorklet.addModule('/worklets/pcm16-processor.js');

          const source = captureCtx.createMediaStreamSource(stream);
          const workletNode = new AudioWorkletNode(captureCtx, 'pcm16-processor');
          workletNodeRef.current = workletNode;

          workletNode.port.onmessage = (event) => {
            const { pcm16, rms } = event.data as { pcm16: ArrayBuffer; rms: number };
            setMicLevel(Math.min(100, Math.round(rms * 350)));
            if (ws.readyState === WebSocket.OPEN) {
              ws.send(pcm16);
            }
          };

          source.connect(workletNode);
          ws.send(
            JSON.stringify({
              type: 'config',
              silence_threshold_ms: silenceThresholdMs,
              ...NOISE_PRESETS[noiseSensitivity],
            })
          );
          ws.send(JSON.stringify({ type: 'start' }));
        } catch (audioErr: any) {
          setWsError({ code: 'AUDIO_WORKLET', message: audioErr.message || 'Microphone AudioWorklet setup failed' });
          void cleanupCall();
        }
      };

      ws.onmessage = (event) => {
        if (event.data instanceof ArrayBuffer) {
          sentenceChunksRef.current.push(new Uint8Array(event.data));
          return;
        }

        try {
          const msg = JSON.parse(event.data as string);
          switch (msg.type) {
            case 'session_ready':
              setRuntimeInfo({
                sessionId: msg.session_id,
                rateLimiterBackend: msg.rate_limiter_backend,
                vadBackend: msg.vad_backend,
                maxSessionSeconds: msg.max_session_seconds,
              });
              setVoiceState(msg.state || 'IDLE');
              pushDebug('session_ready', `VAD=${msg.vad_backend}, RateLimiter=${msg.rate_limiter_backend}`);
              break;

            case 'state':
              setVoiceState(msg.state);
              if (msg.state !== 'LISTENING') setVadSpeechActive(false);
              pushDebug('state', `${msg.state} (${msg.reason || ''})`);
              break;

            case 'vad_speech_start':
              setVadSpeechActive(true);
              pushDebug('vad_speech_start', 'Speech onset detected');
              break;

            case 'vad_speech_end':
              setVadSpeechActive(false);
              pushDebug('vad_speech_end', `Utterance duration ${msg.duration_ms}ms`);
              break;

            case 'vad_prob':
              setVadProb(typeof msg.prob === 'number' ? msg.prob : 0);
              break;

            case 'transcript':
              if (msg.role === 'user') {
                const uid = `user-${Date.now()}`;
                lastUserMsgIdRef.current = uid;
                setTranscripts((prev) => [
                  ...prev,
                  {
                    id: uid,
                    role: 'user',
                    text: msg.text,
                    metrics: {
                      stt_latency_ms: msg.stt_latency_ms,
                      audio_duration_ms: msg.audio_duration_ms,
                    },
                  },
                ]);
                pushDebug('transcript.user', `"${msg.text}" (STT ${msg.stt_latency_ms}ms)`);
              } else if (msg.role === 'assistant') {
                const streamId = activeStreamMsgIdRef.current;
                if (streamId) {
                  setTranscripts((prev) =>
                    prev.map((m) => (m.id === streamId ? { ...m, text: msg.text, streaming: false } : m))
                  );
                } else {
                  const aid = `asst-${Date.now()}`;
                  activeStreamMsgIdRef.current = aid;
                  setTranscripts((prev) => [...prev, { id: aid, role: 'assistant', text: msg.text, streaming: false }]);
                }
                pushDebug('transcript.assistant', `${msg.text.slice(0, 60)}...`);
              }
              break;

            case 'llm_token':
              if (!activeStreamMsgIdRef.current) {
                const aid = `asst-${Date.now()}`;
                activeStreamMsgIdRef.current = aid;
                setTranscripts((prev) => [...prev, { id: aid, role: 'assistant', text: msg.token, streaming: true }]);
              } else {
                const aid = activeStreamMsgIdRef.current;
                setTranscripts((prev) =>
                  prev.map((m) => (m.id === aid ? { ...m, text: m.text + msg.token } : m))
                );
              }
              break;

            case 'audio_start':
              sentenceChunksRef.current = [];
              pushDebug('audio_start', `Sentence #${msg.sentence_index}: "${msg.text.slice(0, 40)}"`);
              break;

            case 'audio_end':
              if (sentenceChunksRef.current.length > 0) {
                playerRef.current?.enqueueEncodedChunks(sentenceChunksRef.current);
                sentenceChunksRef.current = [];
              }
              pushDebug('audio_end', `Queued sentence #${msg.sentence_index}`);
              break;

            case 'audio_stop':
              playerRef.current?.stopAndClear();
              sentenceChunksRef.current = [];
              activeStreamMsgIdRef.current = null;
              pushDebug('audio_stop', msg.reason || 'stopped');
              break;

            case 'interrupt':
              playerRef.current?.stopAndClear();
              sentenceChunksRef.current = [];
              if (activeStreamMsgIdRef.current) {
                const intId = activeStreamMsgIdRef.current;
                setTranscripts((prev) =>
                  prev.map((m) => (m.id === intId ? { ...m, streaming: false, interrupted: true } : m))
                );
                activeStreamMsgIdRef.current = null;
              }
              pushDebug('interrupt', msg.reason || 'barge_in');
              break;

            case 'rag_sources':
              setRagSources(Array.isArray(msg.sources) ? msg.sources : []);
              pushDebug(
                'rag_sources',
                (msg.sources || []).map((s: RagSourceItem) => `${s.file} (${s.score})`).join(', ') || 'none'
              );
              break;

            case 'tool_confirm':
              setPendingConfirm({
                confirm_id: msg.confirm_id,
                tool_name: msg.tool_name,
                arguments: msg.arguments || {},
              });
              pushDebug('tool_confirm', `Awaiting confirmation for ${msg.tool_name}`);
              break;

            case 'tool_call': {
              const tc: ToolCallLog = {
                name: msg.name,
                arguments: msg.arguments || {},
                result: msg.result || {},
                duration_ms: msg.duration_ms || 0,
              };
              setToolCalls((prev) => [tc, ...prev.slice(0, 19)]);
              setTranscripts((prev) => [
                ...prev,
                {
                  id: `tool-${Date.now()}-${Math.random()}`,
                  role: 'assistant',
                  text: `Tool: ${tc.name}(${JSON.stringify(tc.arguments)}) -> ${JSON.stringify(tc.result)}`,
                },
              ]);
              pushDebug('tool_call', `${tc.name} (${tc.duration_ms}ms)`);
              break;
            }

            case 'turn_metrics': {
              const targetId = activeStreamMsgIdRef.current;
              if (targetId) {
                setTranscripts((prev) =>
                  prev.map((m) =>
                    m.id === targetId
                      ? {
                          ...m,
                          streaming: false,
                          metrics: {
                            stt_latency_ms: msg.stt_latency_ms,
                            llm_first_token_ms: msg.llm_first_token_ms,
                            tts_first_audio_ms: msg.tts_first_audio_ms,
                            e2e_latency_ms: msg.e2e_latency_ms,
                          },
                        }
                      : m
                  )
                );
              }
              activeStreamMsgIdRef.current = null;
              pushDebug(
                'turn_metrics',
                `STT=${msg.stt_latency_ms}ms LLM_TTFT=${msg.llm_first_token_ms}ms TTS=${msg.tts_first_audio_ms}ms E2E=${msg.e2e_latency_ms}ms`
              );
              break;
            }

            case 'utterance_dropped':
              pushDebug('utterance_dropped', `Dropped (${msg.reason || 'noise'}) ${msg.audio_duration_ms || 0}ms`);
              break;

            case 'error':
              setWsError({ code: msg.code, message: msg.message });
              if (activeStreamMsgIdRef.current) {
                const failedId = activeStreamMsgIdRef.current;
                setTranscripts((prev) =>
                  prev.map((m) => (m.id === failedId ? { ...m, streaming: false } : m))
                );
                activeStreamMsgIdRef.current = null;
              }
              pushDebug('error', `${msg.code}: ${msg.message}`);
              break;
          }
        } catch {
          // ignore malformed event
        }
      };

      ws.onclose = (ev) => {
        pushDebug('ws.close', `Closed (${ev.code}) ${ev.reason || ''}`);
        void cleanupCall();
      };

      ws.onerror = () => {
        setWsError({ code: 'WS_ERROR', message: 'WebSocket connection failed. Check backend health & auth.' });
        void cleanupCall();
      };
    } catch (err: any) {
      setWsError({ code: 'MIC_DENIED', message: err.message || 'Microphone access denied' });
      void cleanupCall();
    }
  };

  const toggleMute = () => {
    const nextMuted = !isMuted;
    setIsMuted(nextMuted);
    workletNodeRef.current?.port.postMessage({ type: 'mute', muted: nextMuted });
    pushDebug('mic', nextMuted ? 'Muted' : 'Unmuted');
  };

  const sendEndUtterance = () => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'end_utterance' }));
      pushDebug('control', 'Sent end_utterance');
    }
  };

  const sendInterrupt = () => {
    playerRef.current?.stopAndClear();
    sentenceChunksRef.current = [];
    activeStreamMsgIdRef.current = null;
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'interrupt' }));
      pushDebug('control', 'Sent interrupt');
    }
  };

  const handleSilenceChange = (ms: number) => {
    setSilenceThresholdMs(ms);
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'config', silence_threshold_ms: ms }));
    }
  };

  const handleNoiseSensitivityChange = (level: 'low' | 'medium' | 'high') => {
    setNoiseSensitivity(level);
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'config', ...NOISE_PRESETS[level] }));
      pushDebug('config', `Noise sensitivity=${level}`);
    }
  };

  const sendToolConfirm = (approved: boolean) => {
    if (!pendingConfirm) return;
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(
        JSON.stringify({
          type: 'tool_confirm_response',
          confirm_id: pendingConfirm.confirm_id,
          approved,
        })
      );
      pushDebug('tool_confirm_response', `${pendingConfirm.tool_name}: ${approved ? 'confirmed' : 'cancelled'}`);
    }
    setPendingConfirm(null);
  };

  // Compute running averages
  const assistantTurnsWithMetrics = transcripts.filter(
    (t) => t.role === 'assistant' && t.metrics && t.metrics.e2e_latency_ms !== undefined
  );
  const avg = (key: keyof NonNullable<TranscriptItem['metrics']>) => {
    if (!assistantTurnsWithMetrics.length) return 0;
    const sum = assistantTurnsWithMetrics.reduce((acc, t) => acc + (t.metrics?.[key] || 0), 0);
    return Math.round(sum / assistantTurnsWithMetrics.length);
  };

  if (loading) {
    return <div className="p-16 text-center text-slate-500">Loading voice playground...</div>;
  }

  if (loadError || !agent) {
    return <div className="p-12 text-center text-red-400">{loadError || 'Agent not found'}</div>;
  }

  const stateBadgeColors: Record<OrchestratorState, string> = {
    IDLE: 'bg-slate-800 text-slate-300 border-slate-700',
    LISTENING: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/40',
    THINKING: 'bg-amber-500/15 text-amber-300 border-amber-500/40',
    SPEAKING: 'bg-purple-500/15 text-purple-300 border-purple-500/40',
  };

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <Link
            href={`/dashboard/agents/${agentId}`}
            className="p-2 rounded-lg bg-slate-900 border border-slate-800 text-slate-400 hover:text-white transition"
          >
            <ArrowLeft className="w-5 h-5" />
          </Link>
          <div>
            <div className="flex items-center gap-2.5">
              <h1 className="text-2xl font-bold text-white tracking-tight">{agent.name} — Voice Playground</h1>
              <span className={`px-2.5 py-0.5 rounded-full border text-xs font-mono font-semibold ${stateBadgeColors[voiceState]}`}>
                {voiceState}
              </span>
            </div>
            <p className="text-xs text-slate-400 mt-0.5">
              {agent.llm_provider} ({agent.llm_model}) • STT: {agent.stt_provider} • TTS: {agent.tts_voice}
            </p>
          </div>
        </div>

        <button
          onClick={() => setShowDebug((s) => !s)}
          className="inline-flex items-center gap-2 px-3 py-2 rounded-xl bg-slate-900 border border-slate-800 text-slate-300 hover:text-white text-xs font-medium transition"
        >
          <Terminal className="w-4 h-4 text-sky-400" />
          {showDebug ? 'Hide Debug Panel' : 'Show Debug Panel'}
        </button>
      </div>

      {/* Error Banner */}
      {wsError && (
        <div className="p-4 rounded-xl bg-red-500/10 border border-red-500/30 text-red-300 text-sm flex items-center justify-between gap-4">
          <div className="flex items-center gap-2.5">
            <AlertCircle className="w-5 h-5 text-red-400 shrink-0" />
            <span>{wsError.message}</span>
          </div>
          {wsError.code === 'MISSING_API_KEY' && (
            <Link
              href="/dashboard/vault"
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-red-500/20 hover:bg-red-500/30 text-white text-xs font-semibold shrink-0"
            >
              <Key className="w-3.5 h-3.5" />
              Configure API Key Vault
            </Link>
          )}
        </div>
      )}

      {/* Latency Summary Strip */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="p-3.5 rounded-xl bg-slate-900/70 border border-slate-800">
          <span className="text-[11px] uppercase tracking-wider text-slate-500 block">Avg STT Latency</span>
          <span className="text-lg font-bold font-mono text-emerald-400">{avg('stt_latency_ms')} ms</span>
        </div>
        <div className="p-3.5 rounded-xl bg-slate-900/70 border border-slate-800">
          <span className="text-[11px] uppercase tracking-wider text-slate-500 block">Avg LLM First Token</span>
          <span className="text-lg font-bold font-mono text-sky-400">{avg('llm_first_token_ms')} ms</span>
        </div>
        <div className="p-3.5 rounded-xl bg-slate-900/70 border border-slate-800">
          <span className="text-[11px] uppercase tracking-wider text-slate-500 block">Avg TTS First Audio</span>
          <span className="text-lg font-bold font-mono text-purple-400">{avg('tts_first_audio_ms')} ms</span>
        </div>
        <div className="p-3.5 rounded-xl bg-slate-900/70 border border-slate-800">
          <span className="text-[11px] uppercase tracking-wider text-slate-500 block">Avg End-to-End</span>
          <span className="text-lg font-bold font-mono text-amber-300">{avg('e2e_latency_ms')} ms</span>
        </div>
      </div>

      <div className={`grid grid-cols-1 ${showDebug ? 'lg:grid-cols-3' : ''} gap-6`}>
        {/* Left/Main Panel: Call Console & Live Transcript */}
        <div className={`${showDebug ? 'lg:col-span-2' : ''} flex flex-col gap-4`}>
          {/* Call Control Bar */}
          <div className="p-5 rounded-2xl bg-slate-900/70 border border-slate-800 space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                {!isCalling ? (
                  <button
                    onClick={startCall}
                    className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-emerald-500 hover:bg-emerald-600 text-slate-950 font-semibold text-sm transition shadow-lg shadow-emerald-500/20"
                  >
                    <PhoneCall className="w-4 h-4" />
                    Start Voice Call
                  </button>
                ) : (
                  <button
                    onClick={() => void cleanupCall()}
                    className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-red-500 hover:bg-red-600 text-white font-semibold text-sm transition shadow-lg shadow-red-500/20"
                  >
                    <PhoneOff className="w-4 h-4" />
                    End Call
                  </button>
                )}

                {isCalling && (
                  <>
                    <button
                      onClick={toggleMute}
                      className={`inline-flex items-center gap-1.5 px-3.5 py-2.5 rounded-xl border text-xs font-semibold transition ${
                        isMuted
                          ? 'bg-red-500/15 border-red-500/40 text-red-300'
                          : 'bg-slate-800 border-slate-700 text-slate-200 hover:bg-slate-700'
                      }`}
                    >
                      {isMuted ? <MicOff className="w-4 h-4" /> : <Mic className="w-4 h-4 text-emerald-400" />}
                      {isMuted ? 'Unmute' : 'Mute'}
                    </button>

                    <button
                      onClick={sendEndUtterance}
                      disabled={voiceState !== 'LISTENING'}
                      title="Force send current speech buffer immediately"
                      className="inline-flex items-center gap-1.5 px-3.5 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 text-xs font-semibold transition disabled:opacity-40"
                    >
                      <Send className="w-3.5 h-3.5 text-sky-400" />
                      Send Utterance
                    </button>

                    <button
                      onClick={sendInterrupt}
                      disabled={voiceState !== 'THINKING' && voiceState !== 'SPEAKING'}
                      className="inline-flex items-center gap-1.5 px-3.5 py-2.5 rounded-xl bg-amber-500/15 hover:bg-amber-500/25 border border-amber-500/30 text-amber-300 text-xs font-semibold transition disabled:opacity-40"
                    >
                      <Square className="w-3.5 h-3.5" />
                      Interrupt
                    </button>
                  </>
                )}
              </div>

              <div className="flex items-center gap-2 text-xs text-slate-400">
                <span className={`w-2.5 h-2.5 rounded-full ${isConnected ? 'bg-emerald-400 animate-pulse' : 'bg-slate-600'}`} />
                <span>{isConnected ? 'WebSocket Live' : 'Disconnected'}</span>
              </div>
            </div>

            {/* Mic Energy Meter, VAD Probability & Noise Sensitivity */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 pt-2 border-t border-slate-800/80">
              <div className="space-y-1.5">
                <div className="flex items-center justify-between text-xs">
                  <span className="text-slate-400 flex items-center gap-1.5">
                    <Activity className="w-3.5 h-3.5 text-emerald-400" />
                    Mic Level / VAD Prob
                  </span>
                  <span className={`text-[11px] font-mono ${vadSpeechActive ? 'text-emerald-400 font-semibold' : 'text-slate-500'}`}>
                    {vadSpeechActive ? 'SPEECH' : 'SILENCE'} ({Math.round(vadProb * 100)}%)
                  </span>
                </div>
                <div className="space-y-1">
                  <div className="h-2 bg-slate-950 rounded-full overflow-hidden border border-slate-800">
                    <div
                      className={`h-full transition-all duration-75 ${vadSpeechActive ? 'bg-emerald-400' : 'bg-sky-500/70'}`}
                      style={{ width: `${micLevel}%` }}
                    />
                  </div>
                  <div className="h-1.5 bg-slate-950 rounded-full overflow-hidden border border-slate-800" title="Live VAD Speech Probability">
                    <div
                      className={`h-full transition-all duration-75 ${vadProb >= NOISE_PRESETS[noiseSensitivity].speech_start_threshold ? 'bg-amber-400' : 'bg-purple-500/60'}`}
                      style={{ width: `${Math.min(100, Math.round(vadProb * 100))}%` }}
                    />
                  </div>
                </div>
              </div>

              <div className="space-y-1.5">
                <div className="flex items-center justify-between text-xs">
                  <span className="text-slate-400">Noise Filtering <span className="text-[10px] text-slate-500">(High = reject more noise)</span></span>
                  <span className="font-mono text-[11px] text-slate-500 capitalize">{noiseSensitivity}</span>
                </div>
                <div className="grid grid-cols-3 gap-1 bg-slate-950 p-1 rounded-xl border border-slate-800">
                  {(['low', 'medium', 'high'] as const).map((lvl) => (
                    <button
                      key={lvl}
                      type="button"
                      onClick={() => handleNoiseSensitivityChange(lvl)}
                      className={`py-1 rounded-lg text-xs font-semibold capitalize transition ${
                        noiseSensitivity === lvl
                          ? 'bg-sky-500/20 text-sky-300 border border-sky-500/40'
                          : 'text-slate-400 hover:text-slate-200'
                      }`}
                    >
                      {lvl}
                    </button>
                  ))}
                </div>
              </div>

              <div className="space-y-1.5">
                <div className="flex items-center justify-between text-xs">
                  <span className="text-slate-400 flex items-center gap-1.5">
                    <Sliders className="w-3.5 h-3.5 text-sky-400" />
                    End-of-Turn Silence
                  </span>
                  <span className="font-mono text-sky-400">{silenceThresholdMs} ms</span>
                </div>
                <input
                  type="range"
                  min={300}
                  max={1500}
                  step={50}
                  value={silenceThresholdMs}
                  onChange={(e) => handleSilenceChange(Number(e.target.value))}
                  className="w-full accent-sky-400"
                />
              </div>
            </div>
          </div>

          {/* Live Conversation Transcript */}
          <div className="h-[460px] rounded-2xl bg-slate-900/70 border border-slate-800 flex flex-col overflow-hidden">
            <div className="px-5 py-3 bg-slate-950/70 border-b border-slate-800 flex items-center justify-between">
              <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">Live Voice Transcript</span>
              {runtimeInfo.sessionId && (
                <span className="text-[11px] font-mono text-slate-500">Session: {runtimeInfo.sessionId.slice(0, 8)}</span>
              )}
            </div>

            <div className="flex-1 overflow-y-auto p-5 space-y-4">
              {transcripts.length === 0 ? (
                <div className="h-full flex flex-col items-center justify-center text-center text-slate-500 space-y-2">
                  <Volume2 className="w-10 h-10 text-slate-700" />
                  <p className="text-sm font-medium text-slate-300">Click &ldquo;Start Voice Call&rdquo; and start speaking</p>
                  <p className="text-xs max-w-md">
                    Your browser captures 16kHz mono PCM16 via AudioWorklet. Server-side VAD segments speech, faster-whisper transcribes it, LLM streams tokens, and Edge-TTS streams gapless sentence audio back.
                  </p>
                </div>
              ) : (
                transcripts.map((item) => (
                  <div
                    key={item.id}
                    className={`flex flex-col ${item.role === 'user' ? 'items-end' : 'items-start'}`}
                  >
                    <div
                      className={`max-w-[85%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
                        item.role === 'user'
                          ? 'bg-emerald-500 text-slate-950 font-medium rounded-br-none'
                          : 'bg-slate-800 text-slate-100 border border-slate-700/60 rounded-bl-none'
                      }`}
                    >
                      <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider opacity-70 mb-1">
                        {item.role === 'user' ? <Mic className="w-3 h-3" /> : <Bot className="w-3 h-3" />}
                        <span>{item.role}</span>
                        {item.interrupted && (
                          <span className="ml-1 px-1.5 py-0.2 rounded bg-amber-500/20 text-amber-300 font-semibold">
                            interrupted
                          </span>
                        )}
                      </div>
                      <p className="whitespace-pre-wrap">{item.text}</p>
                    </div>

                    {item.role === 'assistant' && item.metrics && item.metrics.e2e_latency_ms !== undefined && (
                      <div className="flex flex-wrap items-center gap-3 mt-1.5 px-1 text-[10px] font-mono text-slate-400">
                        <span className="text-emerald-400">STT: {item.metrics.stt_latency_ms}ms</span>
                        <span className="text-sky-400 flex items-center gap-1">
                          <Zap className="w-3 h-3" />
                          LLM TTFT: {item.metrics.llm_first_token_ms}ms
                        </span>
                        <span className="text-purple-400">TTS First: {item.metrics.tts_first_audio_ms}ms</span>
                        <span className="text-amber-300 flex items-center gap-1">
                          <Clock className="w-3 h-3" />
                          E2E: {item.metrics.e2e_latency_ms}ms
                        </span>
                      </div>
                    )}
                  </div>
                ))
              )}
              <div ref={transcriptsEndRef} />
            </div>
          </div>
        </div>

        {/* Right Panel: Pipeline Diagnostics & Event Inspector */}
        {showDebug && (
          <div className="rounded-2xl bg-slate-900/70 border border-slate-800 flex flex-col h-[615px] overflow-hidden">
            <div className="px-4 py-3 bg-slate-950/70 border-b border-slate-800">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-300 flex items-center gap-2">
                <Terminal className="w-3.5 h-3.5 text-sky-400" />
                Voice Pipeline Inspector
              </h3>
            </div>

            <div className="p-4 border-b border-slate-800 space-y-2 text-xs">
              <div className="flex justify-between">
                <span className="text-slate-500">State Machine</span>
                <span className="font-mono text-emerald-400">{voiceState}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500">VAD Engine</span>
                <span className="font-mono text-slate-200">{runtimeInfo.vadBackend || 'silero-onnx / webrtcvad'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500">Rate Limiter Backend</span>
                <span className="font-mono text-sky-400">{runtimeInfo.rateLimiterBackend || 'redis'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500">Max Session Duration</span>
                <span className="font-mono text-slate-300">
                  {runtimeInfo.maxSessionSeconds ? `${runtimeInfo.maxSessionSeconds}s` : '900s'}
                </span>
              </div>
              {ragSources.length > 0 && (
                <div className="pt-2 border-t border-slate-800/80 space-y-1">
                  <span className="text-[10px] uppercase tracking-wider text-sky-400 font-semibold">
                    Last RAG Sources
                  </span>
                  {ragSources.map((src, i) => (
                    <div key={`${src.file}-${src.chunk_index}-${i}`} className="flex justify-between text-[11px] font-mono">
                      <span className="text-slate-300 truncate max-w-[180px]">{src.file} #{src.chunk_index}</span>
                      <span className="text-emerald-400">{src.score.toFixed(3)}</span>
                    </div>
                  ))}
                </div>
              )}
              {toolCalls.length > 0 && (
                <div className="pt-2 border-t border-slate-800/80 space-y-1.5">
                  <span className="text-[10px] uppercase tracking-wider text-amber-400 font-semibold">
                    Tool Calls ({toolCalls.length})
                  </span>
                  {toolCalls.slice(0, 4).map((tc, i) => (
                    <div key={`${tc.name}-${i}`} className="p-2 rounded-lg bg-slate-950 border border-slate-800 text-[10px] font-mono space-y-0.5">
                      <div className="flex justify-between">
                        <span className="text-amber-300 font-bold">{tc.name}</span>
                        <span className="text-slate-500">{tc.duration_ms}ms</span>
                      </div>
                      <div className="text-slate-400 truncate">args: {JSON.stringify(tc.arguments)}</div>
                      <div className="text-emerald-400 truncate">res: {JSON.stringify(tc.result)}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="flex-1 overflow-y-auto p-3 space-y-1.5 font-mono text-[11px]">
              {debugLogs.length === 0 ? (
                <div className="text-slate-600 text-center py-8">No WebSocket events yet.</div>
              ) : (
                debugLogs.map((ev) => (
                  <div key={ev.id} className="p-2 rounded-lg bg-slate-950/70 border border-slate-800/70">
                    <div className="flex items-center justify-between text-[10px] text-slate-500">
                      <span className="text-sky-400 font-semibold">{ev.type}</span>
                      <span>{ev.time}</span>
                    </div>
                    <p className="text-slate-300 break-words mt-0.5">{ev.summary}</p>
                  </div>
                ))
              )}
            </div>
          </div>
        )}
      </div>

      {/* Sensitive Tool Confirmation Modal */}
      {pendingConfirm && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="w-full max-w-md rounded-2xl bg-slate-900 border border-amber-500/40 p-6 space-y-4 shadow-2xl">
            <div className="flex items-center gap-2 text-amber-400">
              <AlertCircle className="w-5 h-5" />
              <h3 className="text-base font-bold text-white">Confirm Sensitive Tool</h3>
            </div>
            <p className="text-sm text-slate-300">
              The agent wants to execute <code className="text-amber-300 font-mono">{pendingConfirm.tool_name}</code>:
            </p>
            <pre className="p-3 rounded-xl bg-slate-950 border border-slate-800 text-xs font-mono text-emerald-300 overflow-x-auto">
              {JSON.stringify(pendingConfirm.arguments, null, 2)}
            </pre>
            <div className="flex justify-end gap-3 pt-2">
              <button
                onClick={() => sendToolConfirm(false)}
                className="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 text-sm font-semibold"
              >
                Cancel
              </button>
              <button
                onClick={() => sendToolConfirm(true)}
                className="px-5 py-2 rounded-xl bg-emerald-500 hover:bg-emerald-600 text-slate-950 text-sm font-semibold"
              >
                Confirm
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
