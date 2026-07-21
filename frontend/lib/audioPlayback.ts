const SAMPLE_RATE = 48000;
const CHANNELS = 2;

interface WindowWithWebkitAudio extends Window {
  AudioContext?: typeof AudioContext;
  webkitAudioContext?: typeof AudioContext;
}

export class AudioPlaybackManager {
  private audioContext: AudioContext | null = null;
  private nextPlayTime = 0;
  private activeSources: AudioBufferSourceNode[] = [];

  initialize() {
    const win = window as WindowWithWebkitAudio;
    const AudioContextClass = win.AudioContext || win.webkitAudioContext;
    if (!AudioContextClass) {
      throw new Error('Web Audio API is not supported in this browser');
    }
    const audioContext = new AudioContextClass();
    this.audioContext = audioContext;
    this.nextPlayTime = audioContext.currentTime;
  }

  /** Stop any audio already scheduled/playing (e.g. the user just barged in). */
  clear() {
    if (!this.audioContext) return;
    for (const source of this.activeSources) {
      try {
        source.stop();
      } catch {
        // Already stopped/ended - ignore.
      }
    }
    this.activeSources = [];
    this.nextPlayTime = this.audioContext.currentTime;
  }

  playChunk(base64Data: string) {
    if (!this.audioContext) return;

    const binary = atob(base64Data);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) {
      bytes[i] = binary.charCodeAt(i);
    }
    const view = new DataView(bytes.buffer);

    const sampleCount = Math.floor(bytes.length / 2 / CHANNELS);
    if (sampleCount <= 0) return;

    const audioBuffer = this.audioContext.createBuffer(
      CHANNELS,
      sampleCount,
      SAMPLE_RATE,
    );

    for (let channel = 0; channel < CHANNELS; channel++) {
      const channelData = audioBuffer.getChannelData(channel);
      for (let i = 0; i < sampleCount; i++) {
        const byteOffset = (i * CHANNELS + channel) * 2;
        const int16 = view.getInt16(byteOffset, true);
        channelData[i] = int16 / 0x8000;
      }
    }

    const source = this.audioContext.createBufferSource();
    source.buffer = audioBuffer;
    source.connect(this.audioContext.destination);
    source.onended = () => {
      this.activeSources = this.activeSources.filter((s) => s !== source);
    };
    this.activeSources.push(source);

    const now = this.audioContext.currentTime;
    if (this.nextPlayTime < now) {
      this.nextPlayTime = now;
    }
    source.start(this.nextPlayTime);
    this.nextPlayTime += audioBuffer.duration;
  }

  stop() {
    if (this.audioContext) {
      this.audioContext.close();
      this.audioContext = null;
    }
    this.activeSources = [];
    this.nextPlayTime = 0;
  }
}
