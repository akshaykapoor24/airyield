import { createSlice, createAsyncThunk } from "@reduxjs/toolkit";
import { setToken, setUser, getToken, getUser, clearAuth, type AuthUser } from "@/lib/auth";
import api from "@/lib/api";

interface AuthState {
  user: AuthUser | null;
  token: string | null;
  loading: boolean;
  error: string | null;
}

const initialState: AuthState = {
  user:    getUser(),
  token:   getToken(),
  loading: false,
  error:   null,
};

export const login = createAsyncThunk(
  "auth/login",
  async (credentials: { username: string; password: string }, { rejectWithValue }) => {
    try {
      const { data } = await api.post("/auth/login", {
        email:    credentials.username,
        password: credentials.password,
      });
      setToken(data.access_token);
      setUser(data.user);
      return { token: data.access_token, user: data.user };
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "Login failed";
      return rejectWithValue(msg);
    }
  }
);

export const logout = createAsyncThunk("auth/logout", async () => {
  clearAuth();
});

export const fetchMe = createAsyncThunk("auth/fetchMe", async () => {
  const { data } = await api.get<AuthUser>("/users/me");
  setUser(data);
  return data;
});

const authSlice = createSlice({
  name: "auth",
  initialState,
  reducers: {},
  extraReducers: (builder) => {
    builder
      .addCase(login.pending,   (state) => { state.loading = true;  state.error = null; })
      .addCase(login.fulfilled, (state, action) => {
        state.loading = false;
        state.token   = action.payload.token;
        state.user    = action.payload.user;
      })
      .addCase(login.rejected,  (state, action) => {
        state.loading = false;
        state.error   = action.payload as string;
      })
      .addCase(logout.fulfilled, (state) => {
        state.user  = null;
        state.token = null;
      })
      .addCase(fetchMe.fulfilled, (state, action) => {
        state.user = action.payload;
      });
  },
});

export default authSlice.reducer;
