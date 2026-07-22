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
  const [sessionTimeout, setSessionTimeout] = useState(120);

  const handleStartConversation = () => {
    setIsRecording(true);
  };

  const handleStopConversation = () => {
    setIsRecording(false);
  };

  const { messages, status } = useAudioStream(
    isRecording,
    selectedPrompt,
    sessionTimeout,
    handleStopConversation,
  );

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
        onTimeoutChange={setSessionTimeout}
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
