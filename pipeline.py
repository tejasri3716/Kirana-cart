import pandas as pd
from typing import Literal, Optional
from pydantic import BaseModel, Field
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate

# ==========================================
# 1. Structured JSON Schemas for Each Chain
# ==========================================
class Chain1Output(BaseModel):
    primary_category: Literal[
        "Late Delivery", "Damaged / Spoiled Item", "Wrong Item Delivered",
        "Missing Item", "Refund Delay", "Expired Product",
        "Rude Delivery Partner", "Coupon / Offer Not Applied"
    ]
    secondary_issue: Optional[str] = Field(None, description="Second issue if mentioned, else None")
    sentiment: Literal["Positive", "Neutral", "Negative", "Angry"]
    urgency: Literal["Low", "Medium", "High", "Critical"]
    english_summary: str = Field(description="Clean English translation/summary of the complaint")

class Chain2Output(BaseModel):
    claim_verdict: Literal["valid", "partial", "not supported"]
    root_cause: str
    evidence: str = Field(description="Facts checked against Actual_Min, Promised_Min, Payment_Mode, Order_Value_INR")

class Chain3Output(BaseModel):
    risk_level: Literal["Low", "Medium", "High"]
    flags: list[str] = Field(description="E.g., Repeat Claimer, High Value, VIP Tier, Food Safety Risk")
    handling_path: Literal["auto_handle", "human_review"]

class Chain4Output(BaseModel):
    action: Literal["refund", "credit", "replacement", "escalate", "reject"]
    amount_inr: float = Field(description="Total refund or credit amount in INR (0 if none)")
    policy_rule_cited: str
    approval_needed: bool

class Chain5Output(BaseModel):
    customer_reply: str = Field(description="Empathetic reply in Preferred_Language")
    supervisor_note: str = Field(description="3-line brief if escalated/human_review, else 'N/A'")

# ==========================================
# 2. Build the 5 Sequential Chains
# ==========================================
def build_chains(api_key: str):
    llm = ChatGoogleGenerativeAI(
        model="gemini-3.5-flash-lite",
        google_api_key=api_key,
        temperature=0.1
    )

    c1 = ChatPromptTemplate.from_template(
        "Translate and analyze this KiranaKart ticket.\n"
        "Preferred Language: {Preferred_Language}\nComplaint: {Complaint_Text}"
    ) | llm.with_structured_output(Chain1Output)

    c2 = ChatPromptTemplate.from_template(
        "Fact-check the claim against order data. Note: Delay = Actual_Min - Promised_Min. COD orders have no refund-delay flow.\n"
        "Chain 1 Analysis: {c1_json}\n"
        "Order Data -> Promised: {Promised_Min}m, Actual: {Actual_Min}m, Partner: {Delivery_Partner}, "
        "Payment: {Payment_Mode}, Value: Rs {Order_Value_INR}, Item: {Main_Item}"
    ) | llm.with_structured_output(Chain2Output)

    c3 = ChatPromptTemplate.from_template(
        "Assess risk and priority. Flag Repeat Claimer if Tickets_Last_30d >= 4. "
        "Flag High Value if Order_Value_INR > 1500. Flag Food Safety Risk if Expired Product.\n"
        "Chain 1: {c1_json}\nChain 2: {c2_json}\n"
        "Customer Tier: {Customer_Tier}, Tickets Last 30d: {Tickets_Last_30d}, Order Value: Rs {Order_Value_INR}"
    ) | llm.with_structured_output(Chain3Output)

    c4 = ChatPromptTemplate.from_template(
        "Apply the exact KiranaKart Refund Policy to decide the resolution.\n"
        "Policy Rule for {primary_category}: {policy_rule} (Auto-Approval Limit: {auto_limit})\n"
        "Chain 1: {c1_json}\nChain 2: {c2_json}\nChain 3: {c3_json}\nOrder Value: Rs {Order_Value_INR}"
    ) | llm.with_structured_output(Chain4Output)

    c5 = ChatPromptTemplate.from_template(
        "Write a short, empathetic customer reply in {Preferred_Language} addressed to {Customer_Name} ({Customer_Tier} tier). "
        "Do not over-promise. If handling_path is human_review or action is escalate, write a 3-line supervisor note.\n"
        "Decision: {c4_json}\nRisk/Handling: {c3_json}\nSummary: {english_summary}"
    ) | llm.with_structured_output(Chain5Output)

    return c1, c2, c3, c4, c5

# ==========================================
# 3. Process a Single Ticket Through All 5 Chains
# ==========================================
def process_single_ticket(row: dict, policy_df: pd.DataFrame, chains: tuple) -> dict:
    c1, c2, c3, c4, c5 = chains

    # Step 1: Ticket Understanding
    out1 = c1.invoke({
        "Preferred_Language": row["Preferred_Language"],
        "Complaint_Text": row["Complaint_Text"]
    })

    # Step 2: Fact Check & Root Cause
    out2 = c2.invoke({
        "c1_json": out1.model_dump_json(),
        "Promised_Min": row["Promised_Min"],
        "Actual_Min": row["Actual_Min"],
        "Delivery_Partner": row["Delivery_Partner"],
        "Payment_Mode": row["Payment_Mode"],
        "Order_Value_INR": row["Order_Value_INR"],
        "Main_Item": row["Main_Item"]
    })

    # Step 3: Risk & Priority Screening
    out3 = c3.invoke({
        "c1_json": out1.model_dump_json(),
        "c2_json": out2.model_dump_json(),
        "Customer_Tier": row["Customer_Tier"],
        "Tickets_Last_30d": row["Tickets_Last_30d"],
        "Order_Value_INR": row["Order_Value_INR"]
    })

    # Lookup matching policy row for Chain 4
    policy_row = policy_df[policy_df["Issue_Category"] == out1.primary_category].iloc[0]

    # Step 4: Resolution Decision
    out4 = c4.invoke({
        "primary_category": out1.primary_category,
        "policy_rule": policy_row["Policy_Rule"],
        "auto_limit": policy_row["Auto_Approval_Limit"],
        "c1_json": out1.model_dump_json(),
        "c2_json": out2.model_dump_json(),
        "c3_json": out3.model_dump_json(),
        "Order_Value_INR": row["Order_Value_INR"]
    })

    # Step 5: Customer Reply & Supervisor Note
    out5 = c5.invoke({
        "Preferred_Language": row["Preferred_Language"],
        "Customer_Name": row["Customer_Name"],
        "Customer_Tier": row["Customer_Tier"],
        "c4_json": out4.model_dump_json(),
        "c3_json": out3.model_dump_json(),
        "english_summary": out1.english_summary
    })

    return {
        "Primary_Category": out1.primary_category,
        "Secondary_Issue": out1.secondary_issue,
        "Sentiment": out1.sentiment,
        "Urgency": out1.urgency,
        "English_Summary": out1.english_summary,
        "Claim_Verdict": out2.claim_verdict,
        "Root_Cause": out2.root_cause,
        "Evidence": out2.evidence,
        "Risk_Level": out3.risk_level,
        "Risk_Flags": ", ".join(out3.flags),
        "Handling_Path": out3.handling_path,
        "Action": out4.action,
        "Refund_Amount_INR": out4.amount_inr,
        "Policy_Rule_Cited": out4.policy_rule_cited,
        "Approval_Needed": out4.approval_needed,
        "Customer_Reply": out5.customer_reply,
        "Supervisor_Note": out5.supervisor_note
    }
