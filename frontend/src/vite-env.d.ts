/// <reference types="vite/client" />

interface ImportMetaEnv {
  // Set to "1" for the static demo build (mock.ts fixtures, no backend).
  readonly VITE_MOCK?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
