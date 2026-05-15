"""Extracktir Streamlit UI.

Run with:
    streamlit run app.py
"""
from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import streamlit as st

from extracktir import extract_pdf, extract_to_excel


st.set_page_config(page_title="Extracktir", page_icon="📄", layout="wide")

st.title("📄 Extracktir")
st.caption("Extract values, tables, and text from PDF files into a single Excel workbook.")

with st.sidebar:
    st.header("How it works")
    st.markdown(
        "1. Upload one or more PDFs.\n"
        "2. Extracktir detects **tables** and **labeled fields** (e.g. `Invoice No: 12345`).\n"
        "3. Preview the result, then download a multi-sheet `.xlsx` file."
    )
    st.markdown("---")
    st.markdown("**Output sheets:** Summary, Key-Values, one per detected table, Text.")

uploaded = st.file_uploader(
    "Drop PDF files here",
    type=["pdf"],
    accept_multiple_files=True,
)

if not uploaded:
    st.info("Upload at least one PDF to begin.")
    st.stop()

# Extract once per file, cache results in session state keyed by name+size.
results = []
with st.spinner("Extracting..."):
    for f in uploaded:
        f.seek(0)
        result = extract_pdf(f)
        results.append((f, result))

# -- Summary -----------------------------------------------------------------
st.subheader("Summary")
summary_df = pd.DataFrame([r.summary() for _, r in results])
summary_df["source"] = summary_df["source"].apply(lambda s: Path(s).name)
st.dataframe(summary_df, use_container_width=True)

# -- Per-file preview --------------------------------------------------------
for f, result in results:
    name = Path(result.source).name
    with st.expander(f"📄 {name} — {result.page_count} page(s)", expanded=len(results) == 1):
        col_kv, col_meta = st.columns([2, 1])
        with col_kv:
            st.markdown("**Key-Values**")
            if result.key_values:
                st.dataframe(
                    pd.DataFrame(result.key_values),
                    use_container_width=True,
                    height=min(400, 38 + 28 * len(result.key_values)),
                )
            else:
                st.caption("No labeled fields detected.")
        with col_meta:
            st.metric("Tables found", len(result.tables))
            st.metric("Fields found", len(result.key_values))

        if result.tables:
            st.markdown("**Tables**")
            for tbl in result.tables:
                page = tbl.attrs.get("page", "?")
                idx = tbl.attrs.get("index", "?")
                st.markdown(f"_Page {page}, table {idx}_")
                st.dataframe(tbl, use_container_width=True)

        with st.popover("Show raw text"):
            for i, text in enumerate(result.page_texts, start=1):
                st.markdown(f"**Page {i}**")
                st.text(text or "(empty)")

# -- Download ----------------------------------------------------------------
st.markdown("---")
st.subheader("Download")

buffer = io.BytesIO()
sources = []
for f, _ in results:
    f.seek(0)
    sources.append(f)
extract_to_excel(sources, buffer)
buffer.seek(0)

default_name = (
    Path(results[0][0].name).stem + ".xlsx"
    if len(results) == 1
    else "extracktir_output.xlsx"
)

st.download_button(
    label="⬇️ Download Excel",
    data=buffer,
    file_name=default_name,
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    type="primary",
)
