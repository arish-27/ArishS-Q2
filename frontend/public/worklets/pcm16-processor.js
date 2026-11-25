/**
 * AudioWorkletProcessor capturing microphone audio, downsampling from browser native
 * sampleRate (e.g. 48kHz/44.1kHz) to 16kHz mono PCM16, and emitting 512-sample
 * (32ms / 1024-byte) Transferable ArrayBuffers with RMS energy for the live meter.
 */
class PCM16Processor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.targetSampleRate = 16000;
    this.chunkSamples = 512; // 32ms @ 16kHz
    this.resampleOffset = 0;
    this.muted = false;
    this.outBuffer = new Int16Array(this.chunkSamples);
    this.outIndex = 0;
    this.energySum = 0;

    this.port.onmessage = (event) => {
      if (event.data && event.data.type === 'mute') {
        this.muted = Boolean(event.data.muted);
      }
    };
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || !input[0] || this.muted) {
      return true;
    }

    const channel = input[0];
    const ratio = sampleRate / this.targetSampleRate;

    while (this.resampleOffset < channel.length) {
      const idx = Math.floor(this.resampleOffset);
      const frac = this.resampleOffset - idx;
      const s0 = channel[idx];
      const s1 = idx + 1 < channel.length ? channel[idx + 1] : s0;
      const interpolated = s0 + (s1 - s0) * frac;

      const clamped = Math.max(-1, Math.min(1, interpolated));
      const int16 = clamped < 0 ? Math.round(clamped * 32768) : Math.round(clamped * 32767);

      this.outBuffer[this.outIndex] = int16;
      this.energySum += clamped * clamped;
      this.outIndex += 1;

      if (this.outIndex >= this.chunkSamples) {
        const rms = Math.sqrt(this.energySum / this.chunkSamples);
        const frame = this.outBuffer.slice(0);
        this.port.postMessage({ pcm16: frame.buffer, rms }, [frame.buffer]);
        this.outIndex = 0;
        this.energySum = 0;
      }

      this.resampleOffset += ratio;
    }

    this.resampleOffset -= channel.length;
    return true;
  }
}

registerProcessor('pcm16-processor', PCM16Processor);
