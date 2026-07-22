'use client';

import { useEffect, useState } from 'react';

interface Option {
  key: string;
  label: string;
}

interface SelectorProps {
  endpoint: string;
  responseKey: string;
  label: string;
  onSelect: (key: string) => void;
  disabled: boolean;
}

export default function Selector({
  endpoint,
  responseKey,
  label,
  onSelect,
  disabled,
}: SelectorProps) {
  const [options, setOptions] = useState<Option[]>([]);
  const [selected, setSelected] = useState('');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
    fetch(`${apiUrl}${endpoint}`)
      .then((res) => {
        if (!res.ok) throw new Error(`Request failed: ${res.status}`);
        return res.json();
      })
      .then((data) => {
        const items: Option[] = data[responseKey] ?? [];
        setOptions(items);
        if (items.length > 0) {
          setSelected(items[0].key);
          onSelect(items[0].key);
        }
      })
      .catch((err) => {
        console.error(`Failed to fetch ${endpoint}:`, err);
        setError(`Could not load ${label}. Please try refreshing the page.`);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [endpoint, responseKey]);

  const handleChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const key = e.target.value;
    setSelected(key);
    onSelect(key);
  };

  return (
    <div>
      <label className="block text-sm font-medium text-gray-700 mb-2">
        {label}
      </label>
      {error ? (
        <p className="text-sm text-red-600">{error}</p>
      ) : (
        <select
          value={selected}
          onChange={handleChange}
          disabled={disabled}
          className="disabled:opacity-50"
        >
          {options.map((o) => (
            <option key={o.key} value={o.key}>
              {o.label}
            </option>
          ))}
        </select>
      )}
    </div>
  );
}
