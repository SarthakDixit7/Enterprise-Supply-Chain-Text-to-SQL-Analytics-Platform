from __future__ import annotations

import os
from html import escape
from typing import Any

import httpx
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

from logisql.export import sanitize_csv_cell

load_dotenv(override=False)

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")
MAX_HISTORY_ITEMS = 12

st.set_page_config(
    page_title="LogiSQL-Agent",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded",
)

CUSTOM_CSS = """
<style>
  :root {
    --ink: #0f172a;
    --muted: #64748b;
    --line: #e2e8f0;
    --teal: #0f766e;
    --teal-soft: #ccfbf1;
    --orange: #f97316;
    --bg: #f8fafc;
  }
  .block-container { padding-top: 2.2rem; padding-bottom: 7rem; max-width: 1180px; }
  header[data-testid="stHeader"] { background: transparent; }
  .hero {
    border: 1px solid var(--line);
    background:
      radial-gradient(circle at 92% 12%, rgba(249, 115, 22, .12), transparent 28%),
      radial-gradient(circle at 8% 90%, rgba(15, 118, 110, .12), transparent 32%),
      #ffffff;
    border-radius: 22px;
    padding: 2.4rem 2.6rem;
    margin-bottom: 1.3rem;
    box-shadow: 0 18px 55px rgba(15, 23, 42, .06);
  }
  .hero .eyebrow {
    color: var(--teal);
    font-size: .74rem;
    font-weight: 800;
    letter-spacing: .16em;
    text-transform: uppercase;
    margin-bottom: .65rem;
  }
  .hero h1 {
    color: var(--ink);
    font-size: 2.55rem;
    line-height: 1.08;
    letter-spacing: -.04em;
    margin: 0 0 .8rem 0;
  }
  .hero p {
    color: var(--muted);
    font-size: 1.03rem;
    line-height: 1.6;
    max-width: 760px;
    margin: 0;
  }
  .pill-row { display: flex; flex-wrap: wrap; gap: .5rem; margin-top: 1.25rem; }
  .pill {
    border: 1px solid var(--line);
    background: #fff;
    border-radius: 999px;
    color: #334155;
    font-size: .76rem;
    font-weight: 650;
    padding: .38rem .7rem;
  }
  .pill.good { background: var(--teal-soft); border-color: #99f6e4; color: #115e59; }
  .pill.bad { background: #fff1f2; border-color: #fecdd3; color: #be123c; }
  .section-label {
    color: var(--muted);
    font-size: .72rem;
    font-weight: 800;
    letter-spacing: .14em;
    text-transform: uppercase;
    margin: 1.1rem 0 .4rem 0;
  }
  .finding {
    color: var(--ink);
    font-size: 1.32rem;
    font-weight: 750;
    letter-spacing: -.02em;
    line-height: 1.25;
    margin-bottom: .35rem;
  }
  .summary { color: #334155; font-size: .98rem; line-height: 1.65; }
  .metric-card {
    border: 1px solid var(--line);
    border-radius: 14px;
    background: #fff;
    padding: .85rem 1rem;
  }
  .metric-card .label {
    color: var(--muted);
    font-size: .68rem;
    font-weight: 800;
    letter-spacing: .1em;
    text-transform: uppercase;
  }
  .metric-card .value {
    color: var(--ink);
    font-size: 1.35rem;
    font-weight: 780;
    letter-spacing: -.02em;
  }
  div[data-testid="stSidebar"] { border-right: 1px solid var(--line); }
  div[data-testid="stSidebar"] .block-container { padding-top: 1.3rem; }
  .sql-note { color: var(--muted); font-size: .8rem; }
  .sidebar-brand {
    color: var(--ink);
    font-size: 1.18rem;
    font-weight: 800;
    letter-spacing: -.02em;
    margin-bottom: .15rem;
  }
  .sidebar-sub { color: var(--muted); font-size: .78rem; margin-bottom: 1rem; }
  div[data-testid="stChatMessage"] {
    border: 1px solid var(--line);
    border-radius: 16px;
    background: #fff;
    padding: .55rem .75rem;
  }
  div[data-testid="stChatMessage"]:has(div[data-testid="chatAvatarIcon-user"]) {
    background: #f8fafc;
  }
  .stButton > button {
    border-radius: 10px;
    border: 1px solid var(--line);
    font-weight: 650;
  }
  .stButton > button:hover { border-color: var(--teal); color: var(--teal); }
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


class APIError(RuntimeError):
    pass


@st.cache_data(ttl=20, show_spinner=False)
def fetch_health(base_url: str) -> dict[str, Any] | None:
    try:
        response = httpx.get(f"{base_url}/api/v1/health", timeout=4)
        response.raise_for_status()
        return response.json()
    except Exception:
        return None


@st.cache_data(ttl=60, show_spinner=False)
def fetch_schema(base_url: str) -> dict[str, Any] | None:
    try:
        response = httpx.get(f"{base_url}/api/v1/schema", timeout=15)
        response.raise_for_status()
        return response.json()
    except Exception:
        return None


@st.cache_data(ttl=300, show_spinner=False)
def fetch_examples(base_url: str) -> list[dict[str, str]]:
    try:
        response = httpx.get(f"{base_url}/api/v1/examples", timeout=5)
        response.raise_for_status()
        return response.json().get("examples", [])
    except Exception:
        return []


@st.cache_data(ttl=60, show_spinner=False)
def fetch_overview(base_url: str) -> dict[str, Any] | None:
    try:
        response = httpx.get(f"{base_url}/api/v1/overview", timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception:
        return None


def run_query(question: str, row_limit: int) -> dict[str, Any]:
    try:
        response = httpx.post(
            f"{API_BASE_URL}/api/v1/query",
            json={"question": question, "row_limit": row_limit},
            timeout=360,
        )
    except httpx.RequestError as exc:
        raise APIError(f"Could not reach the FastAPI backend at {API_BASE_URL}.") from exc

    if response.status_code >= 400:
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        raise APIError(str(detail))
    return response.json()


def _metric(label: str, value: str) -> None:
    st.markdown(
        f'<div class="metric-card"><div class="label">{label}</div>'
        f'<div class="value">{value}</div></div>',
        unsafe_allow_html=True,
    )


def _compact_currency(value: float) -> str:
    if value >= 1_000_000_000:
        return f"R$ {value / 1_000_000_000:.2f}B"
    if value >= 1_000_000:
        return f"R$ {value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"R$ {value / 1_000:.1f}K"
    return f"R$ {value:,.0f}"


def render_overview(overview: dict[str, Any]) -> None:
    st.markdown('<div class="section-label">Dataset snapshot</div>', unsafe_allow_html=True)
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        _metric("Orders", f"{int(overview.get('orders') or 0):,}")
    with col2:
        _metric("Delivered", f"{int(overview.get('delivered_orders') or 0):,}")
    with col3:
        on_time = overview.get("on_time_rate")
        _metric("On-time delivery", f"{on_time * 100:.1f}%" if on_time is not None else "—")
    with col4:
        _metric("Item value", _compact_currency(float(overview.get("gross_item_value") or 0)))

    start = str(overview.get("first_order_at") or "")[:10]
    end = str(overview.get("last_order_at") or "")[:10]
    span = f"{start} → {end}" if start and end else "date range unavailable"
    st.caption(
        f"{int(overview.get('sellers') or 0):,} sellers · "
        f"{int(overview.get('products') or 0):,} products · "
        f"{int(overview.get('late_orders') or 0):,} late of "
        f"{int(overview.get('measurable_delivered') or 0):,} measured deliveries · {span}"
    )


def render_attempts(response: dict[str, Any]) -> None:
    attempts = response.get("attempts") or []
    timings = response.get("node_timings") or []
    with st.expander("Agent trace", expanded=False):
        if timings:
            timing_text = " · ".join(
                f"{item.get('node', '?')} {item.get('ms', 0):.0f} ms" for item in timings
            )
            st.caption(timing_text)
        if not attempts:
            st.caption("No attempt details were returned.")
            return
        for attempt in attempts:
            kind = str(attempt.get("kind", "event")).replace("_", " ").title()
            attempt_number = attempt.get("attempt", "?")
            st.markdown(f"**Attempt {attempt_number} · {kind}**")
            if attempt.get("error"):
                st.error(attempt["error"])
            if attempt.get("sql"):
                st.code(attempt["sql"], language="sql")
            if attempt.get("row_count") is not None:
                st.caption(f"Rows returned: {attempt['row_count']}")


def render_result(response: dict[str, Any]) -> None:
    if response.get("status") == "failed":
        st.error(response.get("error") or "The agent could not complete this request.")
        if response.get("sql"):
            st.code(response["sql"], language="sql")
        render_attempts(response)
        return

    st.markdown(
        f'<div class="finding">{escape(str(response.get("headline", "Query complete")))}</div>',
        unsafe_allow_html=True,
    )
    summary = response.get("summary") or ""
    if summary:
        st.markdown(
            f'<div class="summary">{escape(str(summary)).replace(chr(10), "<br>")}</div>',
            unsafe_allow_html=True,
        )

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        _metric("Rows", f"{response.get('row_count', 0):,}")
    with col2:
        _metric("Latency", f"{response.get('total_ms', 0) / 1000:.2f}s")
    with col3:
        _metric("Repairs", str(response.get("retry_count", 0)))
    with col4:
        _metric("Schema tables", str(response.get("schema_tables", 0)))

    takeaways = response.get("key_takeaways") or []
    if takeaways:
        st.markdown('<div class="section-label">Executive takeaways</div>', unsafe_allow_html=True)
        for takeaway in takeaways:
            st.markdown(f"- {takeaway}")

    chart = response.get("chart")
    if chart:
        st.markdown('<div class="section-label">Visual</div>', unsafe_allow_html=True)
        try:
            st.plotly_chart(
                go.Figure(chart),
                width="stretch",
                config={"displayModeBar": False, "responsive": True},
            )
        except Exception:
            st.caption("The chart specification could not be rendered.")

    rows = response.get("rows") or []
    columns = response.get("columns") or []
    if rows:
        st.markdown('<div class="section-label">Result set</div>', unsafe_allow_html=True)
        frame = pd.DataFrame(rows, columns=columns)
        export_frame = frame.copy()
        for column in export_frame.columns:
            export_frame[column] = export_frame[column].map(sanitize_csv_cell)
        st.dataframe(frame, width="stretch", hide_index=True, height=min(420, 42 + 35 * len(frame)))
        if response.get("truncated"):
            st.caption("Result truncated by the configured row limit.")
        st.download_button(
            "Download CSV",
            data=export_frame.to_csv(index=False).encode("utf-8"),
            file_name=f"logisql_{response.get('request_id', 'result')[:8]}.csv",
            mime="text/csv",
            key=f"download_{response.get('request_id', 'result')}",
        )
    elif response.get("row_count") == 0:
        st.info("The query completed successfully but returned no rows.")

    warnings = response.get("warnings") or []
    for warning in warnings:
        st.warning(warning)

    with st.expander("Generated SQL", expanded=True):
        st.code(response.get("sql") or "-- no SQL", language="sql")
        st.markdown(
            f'<div class="sql-note">Model: {escape(str(response.get("model", "unknown")))} · '
            f"Request: {escape(str(response.get('request_id', 'unknown')))}</div>",
            unsafe_allow_html=True,
        )

    render_attempts(response)


def render_history() -> None:
    for item in st.session_state.history:
        with st.chat_message("user"):
            st.markdown(item["question"])
        with st.chat_message("assistant", avatar="📦"):
            if item.get("error"):
                st.error(item["error"])
                st.caption(f"Backend: {API_BASE_URL}")
            elif item.get("response"):
                render_result(item["response"])
            else:
                st.caption("No response was recorded for this question.")


def _remember(question: str, response: dict[str, Any] | None, error: str | None) -> None:
    st.session_state.history.append(
        {"question": question, "response": response, "error": error}
    )
    # Keep the transcript bounded so reruns stay fast on long sessions.
    st.session_state.history = st.session_state.history[-MAX_HISTORY_ITEMS:]


def sidebar(health: dict[str, Any] | None) -> int:
    with st.sidebar:
        st.markdown('<div class="sidebar-brand">📦 LogiSQL-Agent</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="sidebar-sub">Guarded text-to-SQL for Olist supply-chain analytics</div>',
            unsafe_allow_html=True,
        )

        if health and health.get("database"):
            st.markdown(
                f'<span class="pill good">● API online · {escape(str(health.get("dialect", "?")))}</span>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown('<span class="pill bad">● API unavailable</span>', unsafe_allow_html=True)

        if health:
            llm_label = "Groq ready" if health.get("llm_configured") else "Groq key missing"
            st.caption(f"{llm_label} · `{health.get('model', 'unknown')}`")
            if not health.get("llm_configured"):
                st.warning("Set GROQ_API_KEY on the API and restart.")

        st.divider()
        st.markdown("**Query settings**")
        row_limit = st.slider("Row limit", min_value=25, max_value=500, value=200, step=25)

        st.divider()
        with st.expander("Schema explorer", expanded=False):
            if st.button("Refresh schema", width="stretch"):
                fetch_schema.clear()
            schema = fetch_schema(API_BASE_URL)
            if not schema:
                st.caption("Schema is unavailable while the API is offline.")
            else:
                st.caption(
                    f"{len(schema.get('tables', []))} allowlisted tables · "
                    f"{len(schema.get('relationships', []))} relationships"
                )
                for table in schema.get("tables", []):
                    with st.expander(table["name"], expanded=False):
                        frame = pd.DataFrame(
                            [
                                {
                                    "column": column["name"],
                                    "type": column["data_type"],
                                    "null": column["nullable"],
                                    "pk": column["is_primary_key"],
                                    "fk": column.get("references") or "",
                                }
                                for column in table.get("columns", [])
                            ]
                        )
                        st.dataframe(frame, width="stretch", hide_index=True)
                if schema.get("warnings"):
                    for warning in schema["warnings"]:
                        st.warning(warning)

        with st.expander("How it works", expanded=False):
            st.markdown(
                "1. **Schema node** introspects `information_schema` / SQLite metadata.  \n"
                "2. **Generate node** prompts Llama 3.3 70B on Groq.  \n"
                "3. **Guard node** parses with SQLGlot and enforces read-only SELECT.  \n"
                "4. **Execute node** runs read-only with a timeout and row cap.  \n"
                "5. **Repair node** feeds errors back to the model (max 3).  \n"
                "6. **Synthesis node** writes findings and a validated Plotly chart."
            )

        st.divider()
        st.caption(f"API: {API_BASE_URL}")
        st.markdown(f"[Open API docs]({API_BASE_URL}/docs)")

        if st.button("Clear conversation", width="stretch"):
            st.session_state.history = []
            st.session_state.pending_question = None
            st.rerun()

    return row_limit


def main() -> None:
    if "history" not in st.session_state:
        st.session_state.history = []
    if "pending_question" not in st.session_state:
        st.session_state.pending_question = None

    health = fetch_health(API_BASE_URL)
    row_limit = sidebar(health)

    st.markdown(
        """
        <div class="hero">
          <div class="eyebrow">Enterprise supply chain intelligence</div>
          <h1>Ask your Olist warehouse anything.</h1>
          <p>
            Plain-English questions become guardrailed PostgreSQL, execute against a
            relational e-commerce dataset, self-correct on failure, and return an
            executive finding with a chart.
          </p>
          <div class="pill-row">
            <span class="pill">LangGraph loop</span>
            <span class="pill">Groq · Llama 3.3 70B</span>
            <span class="pill">SQLGlot AST guardrails</span>
            <span class="pill">Read-only execution</span>
            <span class="pill">LangSmith tracing</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if not health:
        st.error(
            f"The API at `{API_BASE_URL}` is not reachable. Start it with "
            "`uvicorn logisql.api.main:app --reload` and refresh."
        )

    overview = fetch_overview(API_BASE_URL)
    if overview:
        render_overview(overview)

    if not st.session_state.history:
        examples = fetch_examples(API_BASE_URL)
        if examples:
            st.markdown('<div class="section-label">Try a question</div>', unsafe_allow_html=True)
            columns = st.columns(2)
            for index, example in enumerate(examples[:6]):
                with columns[index % 2]:
                    if st.button(
                        f"{example['category']} — {example['question']}",
                        key=f"example_{index}",
                        width="stretch",
                    ):
                        st.session_state.pending_question = example["question"]
                        st.rerun()

    render_history()

    prompt = st.chat_input(
        "e.g. Which product categories generated the most revenue in 2018?",
        disabled=not health,
    )
    if prompt:
        cleaned_prompt = prompt.strip()
        if cleaned_prompt:
            st.session_state.pending_question = cleaned_prompt

    if st.session_state.pending_question:
        question = st.session_state.pending_question
        st.session_state.pending_question = None
        with st.chat_message("user"):
            st.markdown(question)
        with st.chat_message("assistant", avatar="📦"):
            with st.spinner("Planning SQL · validating guardrails · executing · synthesizing"):
                try:
                    response = run_query(question, row_limit)
                    _remember(question, response, None)
                    render_result(response)
                except APIError as exc:
                    message = str(exc)
                    _remember(question, None, message)
                    st.error(message)
            fetch_health.clear()
            fetch_overview.clear()


if __name__ == "__main__":
    main()
