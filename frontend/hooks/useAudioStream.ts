'use client';

import { useEffect, useState, useRef } from 'react';
import { AudioCaptureManager } from '@/lib/audioCapture';
import { AudioPlaybackManager } from '@/lib/audioPlayback';
import { createWebSocketURL, sendControlMessage, sendConfigMessage } from '@/lib/api';

interface Message {
  role: 'user' | 'assistant';
  text: string;
  index: number;
}

// Must match backend CLIENT_CHANNELS (src/realtime/config.py)
const CLIENT_CHANNELS = 2;

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

    // Establish WebSocket connection
    const wsUrl = createWebSocketURL();
    const newWs = new WebSocket(wsUrl);
    wsRef.current = newWs;

    const playback = new AudioPlaybackManager();
    audioPlaybackRef.current = playback;

    const handleAudioFrame = (data: Float32Array) => {
      if (newWs.readyState !== WebSocket.OPEN) return;

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
      const base64 = btoa(String.fromCharCode(...new Uint8Array(buffer)));
      newWs.send(
        JSON.stringify({
          type: 'audio',
          data: base64,
        }),
      );
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

    newWs.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data);

        if (message.type === 'status') {
          setStatus(message.message);
        } else if (message.type === 'transcript') {
          setMessages((prev) => {
            // Same message (by index): append the delta to it directly.
            const sameMessage = prev.findIndex(
              (m) => m.index === message.index,
            );
            if (sameMessage !== -1) {
              const updated = [...prev];
              updated[sameMessage] = {
                ...updated[sameMessage],
                text: updated[sameMessage].text + message.delta,
              };
              return updated;
            }

            // New message index, but same speaker as the last bubble
            // (e.g. a response that got interrupted/restarted mid-reply):
            // keep it as one continuous bubble instead of fragmenting the
            // conversation into a new line per underlying message.
            const last = prev[prev.length - 1];
            if (last && last.role === message.role) {
              const updated = [...prev];
              updated[updated.length - 1] = {
                ...last,
                text: last.text + message.delta,
                index: message.index,
              };
              return updated;
            }

            return [
              ...prev,
              {
                role: message.role,
                text: message.delta,
                index: message.index,
              },
            ];
          });
        } else if (message.type === 'audio') {
          audioPlaybackRef.current?.playChunk(message.data);
        }
      } catch (err) {
        console.error('Failed to parse WebSocket message:', err);
      }
    };

    newWs.onerror = (event) => {
      setStatus(`Error: ${event}`);
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
