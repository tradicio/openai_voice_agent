'use client';

import { useState } from 'react';
import PromptSelector from '@/components/PromptSelector';
import TimeoutSlider from '@/components/TimeoutSlider';
import ConversationButton from '@/components/ConversationButton';
import TranscriptDisplay from '@/components/TranscriptDisplay';
import { useAudioStream } from '@/hooks/useAudioStream';

export default function Home() {
  const [isRecording, setIsRecording] = useState(false);
  const [selectedPrompt, setSelectedPrompt] = useState('');
  const [timeout, setTimeout] = useState(120);

  const { messages, status } = useAudioStream(
    isRecording,
    selectedPrompt,
    timeout,
  );

  const handleStartConversation = () => {
    setIsRecording(true);
  };

  const handleStopConversation = () => {
    setIsRecording(false);
  };

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-gray-900 text-center">
        Voice Chat
      </h1>

      {status && (
        <div className="p-3 bg-blue-100 text-blue-800 rounded text-sm">
          {status}
        </div>
      )}

      <PromptSelector
        onSelect={setSelectedPrompt}
        disabled={isRecording}
      />

      <TimeoutSlider
        onchange={setTimeout}
        disabled={isRecording}
      />

      <ConversationButton
        isRecording={isRecording}
        onStart={handleStartConversation}
        onStop={handleStopConversation}
      />

      <TranscriptDisplay messages={messages} />
    </div>
  );
}
