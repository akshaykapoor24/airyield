import { configureStore } from "@reduxjs/toolkit";
import authReducer from "./slices/authSlice";
import dealReducer from "./slices/dealSlice";
import uiReducer from "./slices/uiSlice";

export const store = configureStore({
  reducer: {
    auth: authReducer,
    deals: dealReducer,
    ui: uiReducer,
  },
});

export type RootState = ReturnType<typeof store.getState>;
export type AppDispatch = typeof store.dispatch;
