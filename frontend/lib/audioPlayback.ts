const SAMPLE_RATE = 48000;
const CHANNELS = 2;

export class AudioPlaybackManager {
  private audioContext: AudioContext | null = null;
  private nextPlayTime = 0;

  initialize() {
    this.audioContext = new (window.AudioContext ||
      (window as any).webkitAudioContext)();
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
    this.nextPlayTime = 0;
  }
}
