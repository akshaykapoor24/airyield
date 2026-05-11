import { createSlice, PayloadAction } from "@reduxjs/toolkit";

interface DealState {
  selectedDealIds: number[];
  compareMode: boolean;
}

const initialState: DealState = {
  selectedDealIds: [],
  compareMode: false,
};

const dealSlice = createSlice({
  name: "deals",
  initialState,
  reducers: {
    toggleDealSelection(state, action: PayloadAction<number>) {
      const id = action.payload;
      const idx = state.selectedDealIds.indexOf(id);
      if (idx === -1) {
        if (state.selectedDealIds.length < 4) state.selectedDealIds.push(id);
      } else {
        state.selectedDealIds.splice(idx, 1);
      }
    },
    clearSelection(state) {
      state.selectedDealIds = [];
      state.compareMode = false;
    },
    setCompareMode(state, action: PayloadAction<boolean>) {
      state.compareMode = action.payload;
    },
  },
});

export const { toggleDealSelection, clearSelection, setCompareMode } = dealSlice.actions;
export default dealSlice.reducer;
