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
  // Mono Float32 -> interleaved stereo Int16 PCM (backend expects CLIENT_CHANNELS)
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
  // Refs (not state) so the audio callback sees the live instance, not a
  // stale closure.
  const wsRef = useRef<WebSocket | null>(null);
  const audioCaptureRef = useRef<AudioCaptureManager | null>(null);
  const audioPlaybackRef = useRef<AudioPlaybackManager | null>(null);
  // Transcript content keyed by backend `seq` (stable row id + sort order).
  // Messages don't arrive in seq order: the user's Whisper transcript often
  // lands after the assistant has begun replying.
  const rawMessagesRef = useRef<Map<number, RawMessage>>(new Map());
  // Seqs seen so far, kept sorted incrementally so re-deriving rows never
  // needs a fresh sort.
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
    // One row per seq, in seq order; turns are never merged.
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
          // User barged in: stop assistant audio already scheduled client-side.
          audioPlaybackRef.current?.clear();
        }
      } catch (err) {
        console.error('Failed to parse WebSocket message:', err);
      }
    };

    newWs.onopen = async () => {
      setStatus('Connected');

      playback.initialize();

      sendConfigMessage(newWs, {
        prompt_key: promptKey,
        timeout,
      });

      const manager = new AudioCaptureManager();
      await manager.initialize(handleAudioFrame);
      audioCaptureRef.current = manager;

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
