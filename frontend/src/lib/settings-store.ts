import { create } from "zustand";
import { persist } from "zustand/middleware";

/**
 * Connection settings, persisted to localStorage (never cookies — the key
 * must not ride along on requests to other origins).
 */

export const DEFAULT_API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export const SETTINGS_STORAGE_KEY = "pandu-settings";

interface SettingsState {
  apiBaseUrl: string;
  apiKey: string;
  setApiBaseUrl: (url: string) => void;
  setApiKey: (key: string) => void;
}

export const useSettings = create<SettingsState>()(
  persist(
    (set) => ({
      apiBaseUrl: DEFAULT_API_BASE_URL,
      apiKey: "",
      setApiBaseUrl: (apiBaseUrl) => set({ apiBaseUrl: apiBaseUrl.trim() }),
      setApiKey: (apiKey) => set({ apiKey: apiKey.trim() }),
    }),
    { name: SETTINGS_STORAGE_KEY },
  ),
);
