export interface ModelOption {
  id: string;
  name: string;
}

export interface ProviderOption {
  id: string;
  label: string;
  models: ModelOption[];
}

export const PROVIDERS: ProviderOption[] = [
  {
    id: 'gemini',
    label: '✦ Google Gemini (Free)',
    models: [
      { id: 'gemini-3.6-flash', name: 'Gemini 3.6 Flash' },
      { id: 'gemini-3.6-pro', name: 'Gemini 3.6 Pro' },
    ],
  },
  {
    id: 'groq',
    label: '⚡ Groq (Free)',
    models: [
      { id: 'qwen/qwen3.6-27b', name: 'Qwen 3.6 27B' },
      { id: 'openai/gpt-oss-120b', name: 'GPT-OSS 120B' },
      { id: 'llama-3.3-70b-versatile', name: 'Llama 3.3 70B' },
      { id: 'meta-llama/llama-4-scout-17b-16e-instruct', name: 'Llama 4 Scout' },
    ],
  },
  {
    id: 'cerebras',
    label: '🧠 Cerebras (Free)',
    models: [
      { id: 'gpt-oss-120b', name: 'GPT-OSS 120B' },
      { id: 'gemma-4-31b', name: 'Gemma 4 31B' },
    ],
  },
  {
    id: 'openai',
    label: 'OpenAI',
    models: [
      { id: 'gpt-4o-mini', name: 'GPT-4o mini' },
      { id: 'gpt-4o', name: 'GPT-4o' },
      { id: 'gpt-4.1-mini', name: 'GPT-4.1 mini' },
      { id: 'gpt-4.1', name: 'GPT-4.1' },
    ],
  },
  {
    id: 'anthropic',
    label: 'Anthropic',
    models: [
      { id: 'claude-3-5-haiku-latest', name: 'Claude 3.5 Haiku' },
      { id: 'claude-3-5-sonnet-latest', name: 'Claude 3.5 Sonnet' },
      { id: 'claude-3-7-sonnet-latest', name: 'Claude 3.7 Sonnet' },
    ],
  },
  {
    id: 'openrouter',
    label: 'OpenRouter',
    models: [
      { id: 'openai/gpt-4o-mini', name: 'GPT-4o mini' },
      { id: 'openai/gpt-4o', name: 'GPT-4o' },
      { id: 'anthropic/claude-3.5-sonnet', name: 'Claude 3.5 Sonnet' },
    ],
  },
];

export const DEFAULT_PROVIDER = 'gemini';
export const DEFAULT_MODEL = 'gemini-3.6-flash';

export function modelName(providerId: string, modelId: string): string {
  const provider = PROVIDERS.find((p) => p.id === providerId);
  const model = provider?.models.find((m) => m.id === modelId);
  return model?.name ?? modelId;
}
