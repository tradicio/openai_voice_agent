'use client';

import { useState } from 'react';
import PromptSelector from '@/components/PromptSelector';
import TimeoutSlider from '@/components/TimeoutSlider';
import ConversationButton from '@/components/ConversationButton';
import TranscriptDisplay from '@/components/TranscriptDisplay';

interface Message {
  role: 'user' | 'assistant';
  text: string;
}

export default function Home() {
  const [isRecording, setIsRecording] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [selectedPrompt, setSelectedPrompt] = useState('');
  const [timeout, setTimeout] = useState(120);

  const handleStartConversation = () => {
    setIsRecording(true);
    setMessages([]);
  };

  const handleStopConversation = () => {
    setIsRecording(false);
  };

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-gray-900 text-center">
        Voice Chat
      </h1>

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
