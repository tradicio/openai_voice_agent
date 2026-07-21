'use client';

import { useState } from 'react';

interface TimeoutSliderProps {
  onTimeoutChange: (timeout: number) => void;
  disabled: boolean;
}

export default function TimeoutSlider({
  onTimeoutChange,
  disabled,
}: TimeoutSliderProps) {
  const [sessionTimeout, setSessionTimeout] = useState(120);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = parseInt(e.target.value);
    setSessionTimeout(value);
    onTimeoutChange(value);
  };

  return (
    <div>
      <label className="block text-sm font-medium text-gray-700 mb-2">
        Maximum conversation time: {sessionTimeout}s
      </label>
      <input
        type="range"
        min="60"
        max="300"
        step="10"
        value={sessionTimeout}
        onChange={handleChange}
        disabled={disabled}
        className="disabled:opacity-50"
      />
    </div>
  );
}
