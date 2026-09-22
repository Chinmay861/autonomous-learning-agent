/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL of the backend, e.g. https://my-backend.onrender.com (no /api suffix needed). */
  readonly VITE_API_BASE_URL?: string;
  /** Optional separate WebSocket base. Defaults to VITE_API_BASE_URL. */
  readonly VITE_WS_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
