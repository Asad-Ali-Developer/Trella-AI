import { createSlice, type PayloadAction } from "@reduxjs/toolkit";

import type { User } from "@/lib/types";

export type SessionStatus = "loading" | "authenticated" | "anonymous";

interface AuthState {
  user: User | null;
  status: SessionStatus;
}

const initialState: AuthState = {
  user: null,
  status: "loading",
};

const authSlice = createSlice({
  name: "auth",
  initialState,
  reducers: {
    setAuthenticatedUser(state, action: PayloadAction<User>) {
      state.user = action.payload;
      state.status = "authenticated";
    },
    clearSession(state) {
      state.user = null;
      state.status = "anonymous";
    },
    setSessionLoading(state) {
      state.status = "loading";
    },
  },
});

export const { clearSession, setAuthenticatedUser, setSessionLoading } = authSlice.actions;
export default authSlice.reducer;