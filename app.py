import io
import os
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from pipeline import build_chains, process_single_ticket

load_dotenv()

st.set_page_config(page_title="KiranaKart AI Support Assistant", page_icon="🛒", layout="wide")
st.title("🛒 KiranaKart Support Ticket Resolution Assistant")

# Sidebar Configuration
with st.sidebar:
    st.header("Configuration")
    default_key = os.getenv("GEMINI_API_KEY", "")
    api_key = st.text_input("Enter Gemini API Key", value=default_key, type="password")
    uploaded_file = st.file_uploader("Upload KiranaKart_Support_Tickets.xlsx", type=["xlsx"])
    num_rows = st.slider("Number of tickets to process (Batch)", min_value=1, max_value=250, value=10)

if not api_key:
    st.warning("👈 Please enter your Gemini API Key in the sidebar (or set it in `.env`) to begin.")
    st.stop()

chains = build_chains(api_key)

# Load Excel Data (either uploaded or local fallback if present)
tickets_df, policy_df = None, None
if uploaded_file is not None:
    tickets_df = pd.read_excel(uploaded_file, sheet_name="Tickets")
    policy_df = pd.read_excel(uploaded_file, sheet_name="Refund_Policy")
elif os.path.exists("KiranaKart_Support_Tickets.xlsx"):
    tickets_df = pd.read_excel("KiranaKart_Support_Tickets.xlsx", sheet_name="Tickets")
    policy_df = pd.read_excel("KiranaKart_Support_Tickets.xlsx", sheet_name="Refund_Policy")

tab1, tab2 = st.tabs(["📊 Batch Excel Processor & Summary", "💬 Interactive Ticket Chatbot"])

# ==========================================
# TAB 1: EXCEL IN -> EXCEL OUT + DASHBOARD
# ==========================================
with tab1:
    if tickets_df is None:
        st.info("Upload `KiranaKart_Support_Tickets.xlsx` in the sidebar to run batch processing.")
    else:
        st.write(f"Loaded **{len(tickets_df)}** tickets and **{len(policy_df)}** policy rules.")
        
        if st.button("🚀 Run 5-Chain Sequential Workflow", type="primary"):
            subset = tickets_df.head(num_rows).copy()
            results = []
            progress = st.progress(0)
            
            for idx, (_, row) in enumerate(subset.iterrows()):
                res = process_single_ticket(row.to_dict(), policy_df, chains)
                results.append(res)
                progress.progress((idx + 1) / len(subset))
            
            res_df = pd.concat([subset.reset_index(drop=True), pd.DataFrame(results)], axis=1)
            st.session_state["processed_df"] = res_df
            st.success("Batch processing complete!")

        if "processed_df" in st.session_state:
            df_out = st.session_state["processed_df"]
            
            # --- Summary View Metrics ---
            st.subheader("📈 Executive Summary")
            col1, col2, col3, col4 = st.columns(4)
            
            total = len(df_out)
            auto_count = (df_out["Handling_Path"] == "auto_handle").sum()
            human_count = total - auto_count
            total_inr = df_out["Refund_Amount_INR"].sum()
            
            col1.metric("Tickets Processed", total)
            col2.metric("Auto-Resolved %", f"{(auto_count/total)*100:.1f}%")
            col3.metric("Sent to Human %", f"{(human_count/total)*100:.1f}%")
            col4.metric("Total Refund/Credit Committed", f"₹{total_inr:,.2f}")

            c_left, c_right = st.columns(2)
            with c_left:
                st.markdown("**Tickets by Category**")
                st.bar_chart(df_out["Primary_Category"].value_counts())
            with c_right:
                st.markdown("**Escalated / Human Review Cases**")
                escalated = df_out[(df_out["Handling_Path"] == "human_review") | (df_out["Action"] == "escalate")]
                st.dataframe(
                    escalated[["Ticket_ID", "Primary_Category", "Risk_Flags", "Refund_Amount_INR", "Supervisor_Note"]],
                    use_container_width=True
                )

            # --- Full Results & Excel Download ---
            st.subheader("📋 Processed Tickets Table")
            st.dataframe(df_out, use_container_width=True)

            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
                df_out.to_excel(writer, index=False, sheet_name="Processed_Tickets")
            
            st.download_button(
                label="📥 Download Processed Excel File",
                data=buffer.getvalue(),
                file_name="KiranaKart_Resolved_Tickets.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

# ==========================================
# TAB 2: INTERACTIVE CHATBOT (DEMO & SINGLE TICKET)
# ==========================================
with tab2:
    st.subheader("Test Single Tickets or Chat with the Support Agent")
    
    if tickets_df is not None:
        selected_id = st.selectbox("Optional: Load a Ticket ID from Excel to inspect", ["Custom Input"] + tickets_df["Ticket_ID"].tolist())
        if selected_id != "Custom Input" and st.button("Analyze Selected Ticket"):
            row = tickets_df[tickets_df["Ticket_ID"] == selected_id].iloc[0].to_dict()
            with st.spinner(f"Running 5-chain workflow for {selected_id}..."):
                res = process_single_ticket(row, policy_df, chains)
            
            st.markdown(f"**Complaint ({row['Preferred_Language']}):** {row['Complaint_Text']}")
            st.json(res)

    if "messages" not in st.session_state:
        st.session_state.messages = []

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if user_prompt := st.chat_input("Paste a customer complaint (e.g., 'Mera doodh expired nikla, order value 450')..."):
        st.session_state.messages.append({"role": "user", "content": user_prompt})
        with st.chat_message("user"):
            st.markdown(user_prompt)

        with st.chat_message("assistant"):
            if policy_df is None:
                reply = "Please upload `KiranaKart_Support_Tickets.xlsx` in the sidebar first so I can load the company Refund Policy rules!"
            else:
                with st.spinner("Running 5-chain resolution pipeline..."):
                    mock_row = {
                        "Customer_Name": "Valued Customer",
                        "Preferred_Language": "Hinglish",
                        "Customer_Tier": "Regular",
                        "Main_Item": "Order Item",
                        "Order_Value_INR": 450,
                        "Payment_Mode": "UPI",
                        "Delivery_Partner": "Shadowfax",
                        "Promised_Min": 15,
                        "Actual_Min": 20,
                        "Tickets_Last_30d": 1,
                        "Complaint_Text": user_prompt
                    }
                    res = process_single_ticket(mock_row, policy_df, chains)
                    reply = (
                        f"### 🔍 5-Chain Resolution Breakdown\n"
                        f"- **Chain 1 (Category & Urgency):** `{res['Primary_Category']}` | Urgency: `{res['Urgency']}` | Sentiment: `{res['Sentiment']}`\n"
                        f"- **Chain 2 (Fact Check):** `{res['Claim_Verdict'].upper()}` — {res['Root_Cause']}\n"
                        f"- **Chain 3 (Risk & Path):** Risk: `{res['Risk_Level']}` | Path: `{res['Handling_Path']}` (Flags: {res['Risk_Flags'] or 'None'})\n"
                        f"- **Chain 4 (Policy Decision):** **{res['Action'].upper()}** (₹{res['Refund_Amount_INR']}) — *{res['Policy_Rule_Cited']}*\n"
                        f"- **Chain 5 (Customer Reply):**\n> {res['Customer_Reply']}\n"
                    )
                    if res["Supervisor_Note"] != "N/A":
                        reply += f"\n- **Supervisor Note:** {res['Supervisor_Note']}"
            
            st.markdown(reply)
            st.session_state.messages.append({"role": "assistant", "content": reply})
