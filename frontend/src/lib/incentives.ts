// Single source of truth for the per-incentive-type columns shown in ticket tables.
// The `key`s MUST stay byte-identical to the backend INCENTIVE_TYPE_KEYS list in
// backend/app/api/v1/tickets.py — they index the ticket's `incentive_breakdown` JSONB.
export const INCENTIVE_TYPE_COLS = [
  { key: "PLB",                    label: "PLB Inc."       },
  { key: "Super PLB",              label: "Super PLB"      },
  { key: "Transaction Fee",        label: "Trans. Fee"     },
  { key: "Deposit Incentive (DI)", label: "DI Inc."        },
  { key: "Marketing Fund",         label: "Mktg Fund"      },
  { key: "Ancillary",              label: "Ancillary Inc." },
  { key: "Frontend",               label: "Frontend Inc."  },
  { key: "Backend",                label: "Backend Inc."   },
  { key: "Cashback",               label: "Cashback"       },
  { key: "Segment Incentive",      label: "Seg. Inc."      },
  { key: "Push Action",            label: "Push Act."      },
] as const;
