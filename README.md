# KiranaKart Support Ticket Resolution Assistant (MVP)

## 1. Prompt & Chain Design
To prevent a single monolithic prompt from hallucinating policies or skipping validation steps, the workflow is split into **five sequential LangChain chains** enforced by **Pydantic structured outputs** (`with_structured_output()`):
1. **Chain 1 – Ticket Understanding:** Translates Hinglish/regional complaints into clean English, classifies the primary issue into one of the 8 policy categories, extracts any secondary issue, and scores sentiment and urgency.
2. **Chain 2 – Fact Check & Root Cause:** Cross-checks the complaint against order telemetry (`Actual_Min - Promised_Min`, `Payment_Mode`, `Order_Value_INR`) to label the claim `valid`, `partial`, or `not supported` (e.g., flagging COD orders that claim a refund delay).
3. **Chain 3 – Risk & Priority Screening:** Evaluates abuse and escalation triggers (`Tickets_Last_30d >= 4` for Repeat Claimers, `Order_Value_INR > 1500` for High Value, VIP tiers, and `Expired Product` food-safety risks) to route tickets to `auto_handle` or `human_review`.
4. **Chain 4 – Resolution Decision:** Injects only the matching row from the `Refund_Policy` sheet to determine the exact action (`refund`, `credit`, `replacement`, `escalate`, `reject`), INR payout amount, and cited rule.
5. **Chain 5 – Customer Reply & Supervisor Note:** Generates an empathetic response in the customer's `Preferred_Language` without over-promising, plus a concise 3-line brief for human supervisors when escalated.

## 2. Key Assumptions
- **Primary Issue Precedence:** When a ticket contains two issues (~12% of tickets), Chain 1 prioritizes the higher-severity or policy-critical issue (e.g., `Expired Product` or `Damaged / Spoiled Item` over `Late Delivery`), while logging the second issue in `Secondary_Issue`.
- **Repeat Claimer Threshold:** Defined as `Tickets_Last_30d >= 4` based on dataset distribution and business rules.
- **Currency & Limits:** All monetary amounts are evaluated in INR (`₹`) against the `Auto_Approval_Limit` column in `Refund_Policy`.

## 3. Known Failure Modes
- **Multi-Issue Payout Calculation:** Currently, Chain 4 calculates the refund/credit based on the `Primary_Category` policy rule; if a customer has both a missing item and a >45-minute delay, secondary compensation may require manual top-up during human review.
- **Ambiguous Item-Level Values:** The dataset provides total `Order_Value_INR` rather than a line-item price breakdown, so partial-order refunds (e.g., one missing item in a multi-item cart) rely on total order value unless capped by the auto-approval limit.
- **Sarcasm / Heavy Code-Switching:** Extreme Hinglish slang or sarcastic praise ("Wah, 1 hour late, amazing service!") can occasionally be misclassified as neutral sentiment in Chain 1.

## 4. Next Three Improvements
1. **Line-Item Order Manifest Integration:** Connect Chain 2 and Chain 4 to an item-level SKU price table so missing/damaged item refunds calculate exact item prices instead of order totals.
2. **Automated Evaluation Harness:** Add an evaluation script comparing Chain 1 & Chain 3 outputs directly against the `Instructor_Key` sheet to track precision/recall on categories and repeat-claimer flags after prompt updates.
3. **Human-in-the-Loop Approval Queue:** Persist processed tickets to a database (e.g., SQLite/PostgreSQL) so support leads can click "Approve & Send" inside Streamlit to trigger actual refund APIs.
