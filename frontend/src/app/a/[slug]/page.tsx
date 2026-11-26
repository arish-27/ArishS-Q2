'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import { api } from '@/lib/api';
import { GaplessAudioPlayer } from '@/lib/audioQueue';
import { PhoneCall, PhoneOff, Bot, Activity, AlertCircle, Volume2, Mic } from 'lucide-react';

type OrchestratorState = 'IDLE' | 'LISTENING' | 'THINKING' | 'SPEAKING';

interface PublicAgent {
  id: string;
  name: string;
  slug: string;
  description?: string;
  personality?: string;
  stt_language: string;
  tts_voice: string;
  is_active: boolean;
}

interface TranscriptLine {
  id: string;
  role: 'user' | 'assistant';
  text: string;
}

const WS_BASE_URL = (process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000/api/v1/voice/stream').replace(
  /\/stream\/?$/,
  '/public'
);

export default function PublicAgentPage() {
  const params = useParams();
  const slug = params.slug as string;

  const [agent, setAgent] = useState<PublicAgent | null>(null);
  const [loading, setLoading] = useState(true);
  const [unavailable, setUnavailable] = useState(false);

  const [isCalling, setIsCalling] = useState(false);
  const [voiceState, setVoiceState] = useState<OrchestratorState>('IDLE');
  const [micLevel, setMicLevel] = useState(0);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [transcripts, setTranscripts] = useState<TranscriptLine[]>([]);

  const wsRef = useRef<WebSocket | null>(null);
  const captureCtxRef = useRef<AudioContext | null>(null);
  const workletNodeRef = useRef<AudioWorkletNode | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const playerRef = useRef<GaplessAudioPlayer | null>(null);
  const sentenceChunksRef = useRef<Uint8Array[]>([]);
  const activeStreamMsgIdRef = useRef<string | null>(null);

  useEffect(() => {
    async function loadPublic() {
      try {
        const data = await api.getPublicAgent(slug);
        if (!data || !data.is_active) {
          setUnavailable(true);
        } else {
          setAgent(data);
        }
      } catch {
        setUnavailable(true);
      } finally {
        setLoading(false);
      }
    }
    void loadPublic();
  }, [slug]);

  const cleanupCall = useCallback(async () => {
    setIsCalling(false);
    setMicLevel(0);
    setVoiceState('IDLE');

    if (workletNodeRef.current) {
      try {
        workletNodeRef.current.disconnect();
      } catch {}
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
    playerRef.current?.stopAndClear();
    if (wsRef.current) {
      try {
        if (wsRef.current.readyState === WebSocket.OPEN) {
          wsRef.current.send(JSON.stringify({ type: 'stop' }));
        }
        wsRef.current.close();
      } catch {}
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
    setErrorMsg(null);
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

      const ws = new WebSocket(`${WS_BASE_URL}/${encodeURIComponent(slug)}`);
      ws.binaryType = 'arraybuffer';
      wsRef.current = ws;
      setIsCalling(true);

      ws.onopen = async () => {
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
          ws.send(JSON.stringify({ type: 'start' }));
        } catch (err: any) {
          setErrorMsg(err.message || 'Microphone setup failed');
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
          if (msg.type === 'state') {
            setVoiceState(msg.state);
          } else if (msg.type === 'transcript') {
            if (msg.role === 'user') {
              setTranscripts((prev) => [...prev, { id: `u-${Date.now()}`, role: 'user', text: msg.text }]);
            } else if (msg.role === 'assistant') {
              const sid = activeStreamMsgIdRef.current;
              if (sid) {
                setTranscripts((prev) => prev.map((m) => (m.id === sid ? { ...m, text: msg.text } : m)));
              } else {
                const aid = `a-${Date.now()}`;
                activeStreamMsgIdRef.current = aid;
                setTranscripts((prev) => [...prev, { id: aid, role: 'assistant', text: msg.text }]);
              }
              activeStreamMsgIdRef.current = null;
            }
          } else if (msg.type === 'llm_token') {
            if (!activeStreamMsgIdRef.current) {
              const aid = `a-${Date.now()}`;
              activeStreamMsgIdRef.current = aid;
              setTranscripts((prev) => [...prev, { id: aid, role: 'assistant', text: msg.token }]);
            } else {
              const aid = activeStreamMsgIdRef.current;
              setTranscripts((prev) => prev.map((m) => (m.id === aid ? { ...m, text: m.text + msg.token } : m)));
            }
          } else if (msg.type === 'audio_start') {
            sentenceChunksRef.current = [];
          } else if (msg.type === 'audio_end') {
            if (sentenceChunksRef.current.length > 0) {
              playerRef.current?.enqueueEncodedChunks(sentenceChunksRef.current);
              sentenceChunksRef.current = [];
            }
          } else if (msg.type === 'audio_stop' || msg.type === 'interrupt') {
            playerRef.current?.stopAndClear();
            sentenceChunksRef.current = [];
            activeStreamMsgIdRef.current = null;
          } else if (msg.type === 'error') {
            setErrorMsg(msg.message || 'Voice error occurred');
            if (msg.code === 'AGENT_UNPUBLISHED') {
              setUnavailable(true);
            }
          }
        } catch {}
      };

      ws.onclose = () => void cleanupCall();
      ws.onerror = () => {
        setErrorMsg('Unable to connect to voice session.');
        void cleanupCall();
      };
    } catch (err: any) {
      setErrorMsg(err.message || 'Microphone access denied');
      void cleanupCall();
    }
  };

  if (loading) {
    return (
      <main className="min-h-screen bg-slate-950 text-slate-400 flex items-center justify-center">
        Loading voice agent...
      </main>
    );
  }

  if (unavailable || !agent) {
    return (
      <main className="min-h-screen bg-slate-950 text-white flex flex-col items-center justify-center p-6 text-center space-y-4">
        <div className="w-14 h-14 rounded-2xl bg-slate-900 border border-slate-800 flex items-center justify-center text-slate-400">
          <Bot className="w-7 h-7" />
        </div>
        <h1 className="text-2xl font-bold">Agent not available</h1>
        <p className="text-sm text-slate-400 max-w-md">
          This voice agent is either unpublished, inactive, or does not exist.
        </p>
        <Link
          href="/"
          className="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-sm font-semibold text-slate-200 transition"
        >
          Back to Home
        </Link>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-slate-950 text-white flex flex-col items-center justify-center p-6">
      <div className="w-full max-w-2xl rounded-3xl bg-slate-900/70 border border-slate-800 p-6 sm:p-8 space-y-6 shadow-2xl">
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 rounded-2xl bg-emerald-500/15 border border-emerald-500/30 flex items-center justify-center text-emerald-400">
              <Bot className="w-6 h-6" />
            </div>
            <div>
              <h1 className="text-xl font-bold text-white">{agent.name}</h1>
              <p className="text-xs text-slate-400 mt-0.5">
                {agent.description || 'Real-time AI Voice Assistant'}
              </p>
            </div>
          </div>
          <span className="px-3 py-1 rounded-full bg-slate-950 border border-slate-800 text-xs font-mono text-emerald-400">
            {voiceState}
          </span>
        </div>

        {errorMsg && (
          <div className="p-3.5 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs flex items-center gap-2">
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span>{errorMsg}</span>
          </div>
        )}

        <div className="flex flex-col sm:flex-row items-center justify-between gap-4 p-4 rounded-2xl bg-slate-950/70 border border-slate-800">
          {!isCalling ? (
            <button
              onClick={startCall}
              className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-6 py-3 rounded-xl bg-emerald-500 hover:bg-emerald-600 text-slate-950 font-semibold text-sm transition"
            >
              <PhoneCall className="w-4 h-4" />
              Start Call
            </button>
          ) : (
            <button
              onClick={() => void cleanupCall()}
              className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-6 py-3 rounded-xl bg-rose-500 hover:bg-rose-600 text-white font-semibold text-sm transition"
            >
              <PhoneOff className="w-4 h-4" />
              End Call
            </button>
          )}

          <div className="w-full sm:w-56 space-y-1.5">
            <div className="flex items-center justify-between text-[11px] text-slate-400">
              <span className="flex items-center gap-1">
                <Activity className="w-3 h-3 text-emerald-400" /> Mic Level
              </span>
              <span className="font-mono">{micLevel}%</span>
            </div>
            <div className="h-2 bg-slate-900 rounded-full overflow-hidden border border-slate-800">
              <div className="h-full bg-emerald-400 transition-all duration-75" style={{ width: `${micLevel}%` }} />
            </div>
          </div>
        </div>

        <div className="h-72 overflow-y-auto rounded-2xl bg-slate-950/60 border border-slate-800 p-4 space-y-3">
          {transcripts.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center text-slate-500 text-xs space-y-2">
              <Volume2 className="w-8 h-8 text-slate-700" />
              <p>Press &ldquo;Start Call&rdquo; and speak naturally.</p>
            </div>
          ) : (
            transcripts.map((t) => (
              <div key={t.id} className={`flex flex-col ${t.role === 'user' ? 'items-end' : 'items-start'}`}>
                <div
                  className={`max-w-[85%] rounded-2xl px-3.5 py-2 text-sm ${
                    t.role === 'user'
                      ? 'bg-emerald-500 text-slate-950 font-medium'
                      : 'bg-slate-800 text-slate-100'
                  }`}
                >
                  <span className="text-[10px] uppercase opacity-70 flex items-center gap-1 mb-0.5">
                    {t.role === 'user' ? <Mic className="w-2.5 h-2.5" /> : <Bot className="w-2.5 h-2.5" />}
                    {t.role}
                  </span>
                  {t.text}
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </main>
  );
}
