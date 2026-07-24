import { create } from 'zustand';

interface AuthState {
  authenticated: boolean;
  setAuthenticated(v: boolean): void;
}

export const useAuthStore = create<AuthState>((set) => ({
  authenticated: false,
  setAuthenticated: (v) => set({ authenticated: v }),
}));