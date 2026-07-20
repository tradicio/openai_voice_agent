export class AudioCaptureManager {
  private mediaStream: MediaStream | null = null;
  private audioContext: AudioContext | null = null;
  private processor: ScriptProcessorNode | null = null;
  private onAudioFrame: (data: Float32Array) => void = () => {};

  async initialize(onAudioFrame: (data: Float32Array) => void) {
    this.onAudioFrame = onAudioFrame;

    try {
      this.mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });

      this.audioContext = new (window.AudioContext ||
        (window as any).webkitAudioContext)();

      const source = this.audioContext.createMediaStreamSource(this.mediaStream);

      // ScriptProcessor (deprecated but simpler for minimal implementation)
      this.processor = this.audioContext.createScriptProcessor(4096, 1, 1);

      this.processor.onaudioprocess = (event) => {
        const inputData = event.inputBuffer.getChannelData(0);
        this.onAudioFrame(new Float32Array(inputData));
      };

      source.connect(this.processor);
      this.processor.connect(this.audioContext.destination);
    } catch (err) {
      console.error('Failed to initialize audio capture:', err);
      throw err;
    }
  }

  stop() {
    if (this.processor) {
      this.processor.disconnect();
    }
    if (this.mediaStream) {
      this.mediaStream.getTracks().forEach((track) => track.stop());
    }
  }
}
