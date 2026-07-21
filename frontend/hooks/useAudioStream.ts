'use client';

import { useEffect, useState, useRef } from 'react';
import { AudioCaptureManager } from '@/lib/audioCapture';
import { AudioPlaybackManager } from '@/lib/audioPlayback';
import { createWebSocketURL, sendControlMessage, sendConfigMessage } from '@/lib/api';

interface Message {
  role: 'user' | 'assistant';
  text: string;
  seq: number;
}

interface RawMessage {
  role: 'user' | 'assistant';
  text: string;
}

// Must match backend CLIENT_CHANNELS (src/realtime/config.py)
const CLIENT_CHANNELS = 2;

function insertSorted(indices: number[], value: number): void {
  let lo = 0;
  let hi = indices.length;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if (indices[mid] < value) lo = mid + 1;
    else hi = mid;
  }
  indices.splice(lo, 0, value);
}

function encodeAudioFrame(data: Float32Array): string {
  // Convert mono Float32 to interleaved stereo Int16 PCM
  // (backend expects CLIENT_CHANNELS channels)
  const buffer = new ArrayBuffer(data.length * 2 * CLIENT_CHANNELS);
  const view = new Int16Array(buffer);
  for (let i = 0; i < data.length; i++) {
    const sample = Math.max(-1, Math.min(1, data[i])) * 0x7fff;
    for (let ch = 0; ch < CLIENT_CHANNELS; ch++) {
      view[i * CLIENT_CHANNELS + ch] = sample;
    }
  }
  return btoa(String.fromCharCode(...new Uint8Array(buffer)));
}

export function useAudioStream(
  isActive: boolean,
  promptKey: string,
  timeout: number,
) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [status, setStatus] = useState('');
  // Refs (not state) so the audio callback always sees the live instance
  // instead of a stale closure captured before the WebSocket/state updated.
  const wsRef = useRef<WebSocket | null>(null);
  const audioCaptureRef = useRef<AudioCaptureManager | null>(null);
  const audioPlaybackRef = useRef<AudioPlaybackManager | null>(null);
  // Raw transcript content keyed by the backend-assigned `seq` — a stable,
  // monotonically increasing id assigned when the underlying conversation
  // item was first created. `seq` is BOTH the row identity and the sort
  // order: the user's Whisper transcript often arrives after the assistant
  // has already started replying, so messages do NOT arrive in seq order.
  const rawMessagesRef = useRef<Map<number, RawMessage>>(new Map());
  // Seqs seen so far, kept sorted incrementally (see insertSorted) so
  // re-deriving the row list never needs a fresh O(n log n) sort.
  const orderedSeqsRef = useRef<number[]>([]);

  const applyTranscriptDelta = (
    seq: number,
    role: 'user' | 'assistant',
    delta: string,
  ): Message[] => {
    const existing = rawMessagesRef.current.get(seq);
    rawMessagesRef.current.set(seq, {
      role,
      text: (existing?.text ?? '') + delta,
    });
    if (!existing) {
      insertSorted(orderedSeqsRef.current, seq);
    }
    // One row per seq, in seq order. No merging of consecutive same-role
    // turns: a finished or interrupted turn always yields a new seq next.
    return orderedSeqsRef.current.map((s) => {
      const msg = rawMessagesRef.current.get(s)!;
      return { role: msg.role, text: msg.text, seq: s };
    });
  };

  const resetTranscript = () => {
    rawMessagesRef.current = new Map();
    orderedSeqsRef.current = [];
  };

  useEffect(() => {
    if (!isActive) {
      // Cleanup
      if (wsRef.current) {
        sendControlMessage(wsRef.current, 'stop');
        wsRef.current.close();
        wsRef.current = null;
      }
      if (audioCaptureRef.current) {
        audioCaptureRef.current.stop();
        audioCaptureRef.current = null;
      }
      if (audioPlaybackRef.current) {
        audioPlaybackRef.current.stop();
        audioPlaybackRef.current = null;
      }
      return;
    }

    resetTranscript();
    setMessages([]);

    // Establish WebSocket connection
    const wsUrl = createWebSocketURL();
    const newWs = new WebSocket(wsUrl);
    wsRef.current = newWs;

    const playback = new AudioPlaybackManager();
    audioPlaybackRef.current = playback;

    const handleAudioFrame = (data: Float32Array) => {
      if (newWs.readyState !== WebSocket.OPEN) return;
      newWs.send(
        JSON.stringify({
          type: 'audio',
          data: encodeAudioFrame(data),
        }),
      );
    };

    const handleSocketMessage = (event: MessageEvent) => {
      try {
        const message = JSON.parse(event.data);

        if (message.type === 'status') {
          setStatus(message.message);
        } else if (message.type === 'transcript') {
          setMessages(
            applyTranscriptDelta(message.seq, message.role, message.delta),
          );
        } else if (message.type === 'audio') {
          audioPlaybackRef.current?.playChunk(message.data);
        } else if (message.type === 'clear_audio') {
          // User barged in: stop whatever assistant audio is already
          // scheduled client-side instead of letting it finish playing out.
          audioPlaybackRef.current?.clear();
        }
      } catch (err) {
        console.error('Failed to parse WebSocket message:', err);
      }
    };

    newWs.onopen = async () => {
      setStatus('Connected');

      playback.initialize();

      // Send initial config
      sendConfigMessage(newWs, {
        prompt_key: promptKey,
        timeout,
      });

      // Initialize audio capture
      const manager = new AudioCaptureManager();
      await manager.initialize(handleAudioFrame);
      audioCaptureRef.current = manager;

      // Start conversation
      sendControlMessage(newWs, 'start');
    };

    newWs.onmessage = handleSocketMessage;

    newWs.onerror = (event) => {
      setStatus('Connection error');
      console.error('WebSocket error:', event);
    };

    newWs.onclose = () => {
      setStatus('Disconnected');
    };

    return () => {
      if (newWs.readyState === WebSocket.OPEN) {
        newWs.close();
      }
      audioCaptureRef.current?.stop();
      audioCaptureRef.current = null;
      audioPlaybackRef.current?.stop();
      audioPlaybackRef.current = null;
      wsRef.current = null;
    };
  }, [isActive, promptKey, timeout]);

  return { messages, status };
}
