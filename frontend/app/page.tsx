'use client';

import { useState } from 'react';
import Selector from '@/components/Selector';
import ConversationButton from '@/components/ConversationButton';
import TranscriptDisplay from '@/components/TranscriptDisplay';
import { useAudioStream } from '@/hooks/useAudioStream';

export default function Home() {
  const [isRecording, setIsRecording] = useState(false);
  const [selectedPrompt, setSelectedPrompt] = useState('');
  const [selectedModel, setSelectedModel] = useState('');
  const [selectedVoice, setSelectedVoice] = useState('');

  const handleStartConversation = () => {
    setIsRecording(true);
  };

  const handleStopConversation = () => {
    setIsRecording(false);
  };

  const { messages, status } = useAudioStream(
    isRecording,
    selectedPrompt,
    selectedModel,
    selectedVoice,
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

      <Selector
        endpoint="/api/prompts"
        responseKey="prompts"
        label="Assistant Prompt"
        onSelect={setSelectedPrompt}
        disabled={isRecording}
      />

      <Selector
        endpoint="/api/models"
        responseKey="models"
        label="Model"
        onSelect={setSelectedModel}
        disabled={isRecording}
      />

      <Selector
        endpoint="/api/voices"
        responseKey="voices"
        label="Voice"
        onSelect={setSelectedVoice}
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
