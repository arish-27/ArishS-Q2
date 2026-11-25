/**
 * Gapless Web Audio playback scheduler for sentence-streamed TTS audio chunks.
 * Decodes each completed sentence buffer sequentially and schedules startAt = nextStartTime
 * so consecutive sentences play back-to-back with zero gaps or clicks.
 */
export class GaplessAudioPlayer {
  private ctx: AudioContext | null = null;
  private nextStartTime = 0;
  private activeSources: Set<AudioBufferSourceNode> = new Set();
  private decodeChain: Promise<void> = Promise.resolve();
  private generation = 0;
  private onDrainCallback?: () => void;

  constructor(onDrain?: () => void) {
    this.onDrainCallback = onDrain;
  }

  private ensureContext(): AudioContext {
    if (!this.ctx || this.ctx.state === 'closed') {
      const AudioCtx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      this.ctx = new AudioCtx();
    }
    if (this.ctx.state === 'suspended') {
      void this.ctx.resume();
    }
    return this.ctx;
  }

  public warmup(): void {
    this.ensureContext();
  }

  public enqueueEncodedChunks(chunks: Uint8Array[]): void {
    if (!chunks.length) return;
    const totalLength = chunks.reduce((acc, c) => acc + c.byteLength, 0);
    if (totalLength === 0) return;

    const merged = new Uint8Array(totalLength);
    let offset = 0;
    for (const chunk of chunks) {
      merged.set(chunk, offset);
      offset += chunk.byteLength;
    }

    const gen = this.generation;
    this.decodeChain = this.decodeChain.then(async () => {
      if (gen !== this.generation) return;
      try {
        const ctx = this.ensureContext();
        const audioBuffer = await ctx.decodeAudioData(merged.buffer.slice(0));
        if (gen !== this.generation) return;

        const now = ctx.currentTime;
        const startAt = Math.max(now + 0.015, this.nextStartTime);
        const source = ctx.createBufferSource();
        source.buffer = audioBuffer;
        source.connect(ctx.destination);

        this.activeSources.add(source);
        source.onended = () => {
          this.activeSources.delete(source);
          if (this.activeSources.size === 0 && gen === this.generation) {
            this.onDrainCallback?.();
          }
        };

        source.start(startAt);
        this.nextStartTime = startAt + audioBuffer.duration;
      } catch (err) {
        console.warn('GaplessAudioPlayer decode error:', err);
      }
    });
  }

  public stopAndClear(): void {
    this.generation += 1;
    this.nextStartTime = 0;
    Array.from(this.activeSources).forEach((src) => {
      try {
        src.stop();
        src.disconnect();
      } catch {
        // ignore already-stopped sources
      }
    });
    this.activeSources.clear();
  }

  public async close(): Promise<void> {
    this.stopAndClear();
    if (this.ctx && this.ctx.state !== 'closed') {
      await this.ctx.close();
      this.ctx = null;
    }
  }
}
