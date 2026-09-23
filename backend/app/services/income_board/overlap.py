"""The one cross-source de-duplication the sale total needs.

An NDC statement is the airline's own sales export, and most of what it lists also
settles through BSP. Both are real documents and both are projected, so a sale total
that simply added them would count those tickets twice —
`report_download/columns.COUNTS_IN_NET_RULES` says so in as many words: "NDC — Yes,
unless the ticket is settled through BSP in this or another upload."

WHY THIS IS NOT A ROW PREDICATE. Every other Counts-In-Net rule reads the row it is
judging: a blank footer line, a cancelled status, a payment movement with no fare. This
one reads a DIFFERENT TABLE'S rows, so it cannot be an expression inside an arm. It is
its own statement, run after either side is projected.

AND IT HAS TO RUN AFTER EITHER SIDE. Suppressing NDC only when NDC is projected would
be right exactly once — on a workspace that happens to load its BSP settlement first.
The real sequence is the other one: the airline's export arrives in the first week of
the month and the BSP settlement a fortnight later, so the suppression has to be
re-evaluated when the BSP batch lands, not only when the NDC batch does. That is why
this re-stamps every NDC row the tenant has rather than the batch just written, and why
it sets `counts_in_net` in BOTH directions — deleting a BSP upload must give the NDC
sale back.

IT JOINS ON THE DOCUMENT KEY, NOT ON `ticket_key`. `norm_tn` strips leading zeros, which
is harmless for the BSP-to-internal-ticket join it was written for and wrong here;
report_download/normalize.py's header states the requirement directly — "098 0123456789"
and "098 123456789" are different documents. Matching on the looser key would suppress
NDC sale that BSP never settled, and the symptom would be a carrier quietly worth less.

THE TYPE HAS TO MATCH TOO. `linking._NDC_TARGETS`: a refund group settles against a BSP
REFUND, everything else against a sale, an exchange or an EMD. A BSP row holding the
same ticket under some other type is not the settlement of this line — the report flags
that case `BSP_HAS_OTHER_TXN` and still counts the NDC row.
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.income_board import SOURCE_BSP, SOURCE_NDC, TXN_REFUND, TXN_SALE
from app.services.report_download.columns import NET_NDC_IN_BSP

logger = logging.getLogger(__name__)


# BSP transaction types that settle a sale. `_SALE_KINDS` in linking.py is
# {SALE, EXCHANGE, EMD} in the report's canonical vocabulary; on this board a TKTT or an
# EMD is `txn_class='sale'` while an EXCH is `adjustment`, because bsp_commission settles
# an exchange under the reissued document and counting it as a sale would book the same
# journey twice. The exchange still SETTLES the ticket, though, so it belongs here.
_SETTLES_A_SALE = (
    f"(b.txn_class = '{TXN_SALE}' OR b.txn_type = 'EXCH')"
)
_SETTLES_A_REFUND = f"b.txn_class = '{TXN_REFUND}'"


async def stamp_bsp_ndc_overlap(db: AsyncSession, *, tenant_id: int) -> int:
    """Re-evaluate every NDC row in a workspace against its BSP rows. Idempotent.

    Returns the number of rows whose verdict CHANGED — zero on a no-op re-run, which is
    what makes it safe to call after every projection.

    SCOPED TO THE TENANT, NOT THE UPLOADER, and that is deliberate. A ticket settled in
    BSP by a colleague is still settled; scoping on `created_by_id` would count it twice
    the moment two people divide the uploading between them, which is the normal case in
    a workspace big enough to care. The row keeps its reason string, so a reader who
    cannot see the BSP upload is told why the line is out rather than left with a gap.
    """
    res = await db.execute(
        text(f"""
            UPDATE income_board_rows n
               SET counts_in_net = NOT settled.found,
                   counts_in_net_reason = CASE WHEN settled.found
                                               THEN :reason ELSE NULL END
              FROM (
                    SELECT r.id,
                           EXISTS (
                               SELECT 1
                                 FROM income_board_rows b
                                WHERE b.tenant_id = r.tenant_id
                                  AND b.source = :bsp
                                  AND b.doc_code = r.doc_code
                                  AND b.doc_serial = r.doc_serial
                                  AND CASE WHEN r.txn_class = '{TXN_REFUND}'
                                           THEN {_SETTLES_A_REFUND}
                                           ELSE {_SETTLES_A_SALE} END
                           ) AS found
                      FROM income_board_rows r
                     WHERE r.tenant_id = :tid
                       AND r.source = :ndc
                       AND r.doc_code IS NOT NULL
                       AND r.doc_serial IS NOT NULL
                   ) settled
             WHERE n.id = settled.id
               AND n.counts_in_net = settled.found
        """),
        {"tid": tenant_id, "ndc": SOURCE_NDC, "bsp": SOURCE_BSP,
         "reason": NET_NDC_IN_BSP},
    )
    changed = res.rowcount or 0
    if changed:
        logger.info("income_board: re-stamped %s NDC rows against BSP for tenant %s",
                    changed, tenant_id)
    return changed


#: The two sources whose projection changes the answer above. A projection of anything
#: else cannot affect it, so the hook skips the statement rather than running a
#: workspace-wide UPDATE on every LCC upload.
OVERLAP_SOURCES = frozenset({SOURCE_BSP, SOURCE_NDC})
