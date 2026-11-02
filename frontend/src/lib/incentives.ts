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
  { key: "NDC",                    label: "NDC"            },
] as const;

// Types a deal can carry that the engine pays nothing on, ticket by ticket: what their tabs
// save is a deposit or a period target, with no rate to apply to one fare. So their columns
// stay empty and they are not part of Expected — said in the column's tooltip, so an empty
// column does not read as "the deal paid nothing". Pinned by
// backend/tests/test_incentive_types_priced.py; change the two together.
export const NOT_PRICED_PER_TICKET: Record<string, string> = {
  "Deposit Incentive (DI)": "Earned on a deposit rather than on a ticket, so it is not calculated per ticket and is not part of Expected.",
  "Cashback":               "A Cashback tab saves a period target and no per-ticket rate, so it is not calculated per ticket and is not part of Expected.",
  "Segment Incentive":      "Its slabs depend on segments flown over a period, so it is not calculated per ticket and is not part of Expected.",
};
