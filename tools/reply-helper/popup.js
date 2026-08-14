const DEFAULT_MODELS = {
  anthropic: 'claude-haiku-4-6',
  openai: 'gpt-4o-mini',
};

const providerEl = document.getElementById('provider');
const modelEl = document.getElementById('model');
const apiKeyEl = document.getElementById('apiKey');
const toneEl = document.getElementById('tone');
const saveBtn = document.getElementById('save');
const statusEl = document.getElementById('status');

chrome.storage.sync.get(['provider', 'model', 'apiKey', 'tone'], (s) => {
  providerEl.value = s.provider || 'anthropic';
  modelEl.value = s.model || DEFAULT_MODELS[providerEl.value];
  apiKeyEl.value = s.apiKey || '';
  toneEl.value = s.tone || 'mix';
});

providerEl.addEventListener('change', () => {
  modelEl.value = DEFAULT_MODELS[providerEl.value];
});

saveBtn.addEventListener('click', () => {
  const payload = {
    provider: providerEl.value,
    model: modelEl.value.trim() || DEFAULT_MODELS[providerEl.value],
    apiKey: apiKeyEl.value.trim(),
    tone: toneEl.value,
  };
  chrome.storage.sync.set(payload, () => {
    statusEl.textContent = 'Saved ✓';
    setTimeout(() => { statusEl.textContent = ''; }, 1800);
  });
});
