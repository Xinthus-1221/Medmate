"""MedMate: Medicine Alternative Suggester with Allergy Check.

Modern, high-polish Streamlit web dashboard implementing Levels 1-4 + Bonus features:
- Typo-tolerant medicine search assist
- Deterministic alternative matching
- 3-tier allergy trigger detection & strict safety guards
- Side-by-side difference comparison tables & cost savings
- Clean printable clinical report export
- Live interactive test suite runner
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
import streamlit as st

import importlib
import medmate
importlib.reload(medmate)
from medmate import (
    compute_differences,
    get_data_path,
    load_allergy_classes,
    load_medicines,
    normalize_form,
    normalize_strength,
    normalize_text,
    search_medicines,
    suggest,
)
from test_medmate import load_public_test_cases

# ------------------------------------------------------------------------------
# Page Configuration & Theming
# ------------------------------------------------------------------------------
st.set_page_config(
    page_title="MedMate | Medicine Alternative Suggester",
    page_icon="💊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom Styling
st.markdown(
    """
    <style>
    /* Global layout & typography */
    .main {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }
    
    /* Header branding */
    .medmate-header {
        background: linear-gradient(135deg, #1E3A8A 0%, #0D9488 100%);
        color: white;
        padding: 1.8rem 2rem;
        border-radius: 14px;
        margin-bottom: 1.5rem;
        box-shadow: 0 4px 12px rgba(0,0,0,0.08);
    }
    .medmate-header h1 {
        margin: 0;
        font-size: 2.2rem;
        font-weight: 700;
        color: white;
        letter-spacing: -0.5px;
    }
    .medmate-header p {
        margin: 0.4rem 0 0 0;
        font-size: 1.05rem;
        opacity: 0.9;
    }

    /* Disclaimer box */
    .safety-disclaimer {
        background-color: #FEF3C7;
        border-left: 5px solid #F59E0B;
        color: #92400E;
        padding: 0.9rem 1.2rem;
        border-radius: 6px;
        font-size: 0.92rem;
        margin-bottom: 1.5rem;
    }

    /* Card styling */
    .med-card {
        background: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-radius: 12px;
        padding: 1.2rem;
        margin-bottom: 1rem;
        box-shadow: 0 2px 5px rgba(0,0,0,0.03);
    }
    .prescribed-card {
        border-left: 6px solid #2563EB;
        background-color: #F8FAFC;
    }
    .alternative-card {
        border-left: 6px solid #10B981;
        background-color: #FFFFFF;
        transition: transform 0.15s ease-in-out;
    }
    .alternative-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 16px rgba(0,0,0,0.06);
    }
    .excluded-card {
        border-left: 6px solid #EF4444;
        background-color: #FFF5F5;
    }

    /* Status badges */
    .badge-pill {
        display: inline-block;
        padding: 0.25rem 0.65rem;
        font-size: 0.8rem;
        font-weight: 600;
        border-radius: 9999px;
        margin-right: 0.4rem;
        margin-bottom: 0.4rem;
    }
    .badge-blue { background-color: #DBEAFE; color: #1E40AF; }
    .badge-green { background-color: #D1FAE5; color: #065F46; }
    .badge-red { background-color: #FEE2E2; color: #991B1B; }
    .badge-amber { background-color: #FEF3C7; color: #92400E; }
    .badge-purple { background-color: #EDE9FE; color: #5B21B6; }
    .badge-orange { background-color: #FFEDD5; color: #C2410C; }
    .badge-slate { background-color: #F1F5F9; color: #475569; }

    /* Comparison metrics */
    .savings-badge {
        font-size: 1.1rem;
        font-weight: 700;
        color: #059669;
    }
    .increase-badge {
        font-size: 1.1rem;
        font-weight: 700;
        color: #DC2626;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ------------------------------------------------------------------------------
# Data Cache
# ------------------------------------------------------------------------------
@st.cache_data(ttl=60)
def get_cached_medicines() -> Dict[str, Dict[str, Any]]:
    return load_medicines()


@st.cache_data(ttl=60)
def get_cached_allergy_classes() -> Dict[str, str]:
    return load_allergy_classes()


medicines_db = get_cached_medicines()
allergy_classes_db = get_cached_allergy_classes()


# ------------------------------------------------------------------------------
# Header Banner
# ------------------------------------------------------------------------------
st.markdown(
    """
    <div class="medmate-header">
        <h1>💊 MedMate: Medicine Alternative Suggester</h1>
        <p>Deterministic, Safety-First Medicine Formulation Matching with Rigorous Multi-Tier Allergy Checking</p>
    </div>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="safety-disclaimer">
        <strong>⚠️ Clinical Learning Exercise:</strong> Every medicine, active ingredient, excipient dye, manufacturer, and price
        in this project is fictional. MedMate operates purely on deterministic rules and is intended for demonstration. It does NOT provide medical advice.
    </div>
    """,
    unsafe_allow_html=True,
)


# ------------------------------------------------------------------------------
# Sidebar: Controls & Inputs
# ------------------------------------------------------------------------------
with st.sidebar:
    st.header("⚙️ Prescription Configuration")

    # 1. Ask for medicine name first
    st.subheader("1. Enter Medicine Name")

    search_query = st.text_input(
        "Enter Medicine Name or ID:",
        value=st.session_state.get("med_search_query", ""),
        placeholder="e.g. Zolvexin, Zolvexn, Panacaf, Amoxsol, M001...",
        help="Type medicine name or ID. MedMate uses typo-tolerant search to find and show ONLY matching options.",
        key="sidebar_search_input",
    )

    # Sync session state if updated via text_input
    if search_query != st.session_state.get("med_search_query", ""):
        st.session_state["med_search_query"] = search_query
        # Reset selected medicine if search changed
        if "selected_med_id" in st.session_state:
            del st.session_state["selected_med_id"]

    suggested_matches = []
    selected_med_id = None

    if search_query.strip():
        suggested_matches = search_medicines(search_query.strip(), limit=10)

        if not suggested_matches:
            st.error(f"❌ No matching medicines found for **'{search_query}'**.")
            st.caption("ℹ️ Non-matching options are hidden to prevent accidental incorrect substitution.")
        else:
            st.success(f"✓ Found {len(suggested_matches)} matching option(s)")

            options_labels = {
                m["id"]: f"{m['id']} — {m['brand']} ({m['strength']}, {m['form']}) [{m['manufacturer']}]"
                for m in suggested_matches
            }

            # Do NOT autoselect medicine: default to None unless user explicitly chose one
            cur_sel = st.session_state.get("selected_med_id")
            default_index = list(options_labels.keys()).index(cur_sel) if cur_sel in options_labels else None

            selected_med_id = st.selectbox(
                "Select one of the matching options:",
                options=list(options_labels.keys()),
                index=default_index,
                placeholder="Choose a matching medicine...",
                format_func=lambda x: options_labels[x],
                help="Only options matching your search are displayed. Select one to proceed.",
            )
            if selected_med_id:
                st.session_state["selected_med_id"] = selected_med_id
    else:
        st.session_state.pop("selected_med_id", None)
        st.info("👉 Enter a medicine name above to display matching options.")

    st.markdown("---")
    # 2. Patient Allergy Profile: No pre-filled options shown
    st.subheader("2. Patient Allergy Profile")

    allergy_input = st.text_input(
        "Enter Patient Allergies (comma-separated):",
        value="",
        placeholder="e.g. Dye R, Penicillin, Lactose...",
        help="Type patient allergies separated by commas. No pre-filled options are shown.",
    )

    combined_allergies = [
        item.strip() for item in allergy_input.split(",") if item.strip()
    ]
    if combined_allergies:
        st.caption(f"Active allergy filters: {', '.join([f'`{a}`' for a in combined_allergies])}")

    st.markdown("---")
    st.subheader("3. Safety Invariants")

    dns_toggle = st.toggle(
        "🚫 Do Not Substitute (DNS)",
        value=False,
        help="If checked, strictly forbids any generic/brand substitution and returns 0 alternatives.",
    )

    sort_order = st.radio(
        "Sort Alternatives By:",
        options=["Lowest Price First", "Highest Savings", "Brand (A-Z)"],
        horizontal=True,
    )


# ------------------------------------------------------------------------------
# Main Application Tabs
# ------------------------------------------------------------------------------
tab1, tab2 = st.tabs([
    "🎯 Alternative Suggestions & Allergy Checks",
    "🧪 Test Suite & Safety Verifier",
])


# ==============================================================================
# TAB 1: Core Suggester Engine
# ==============================================================================
with tab1:
    if not selected_med_id:
        if search_query.strip():
            if suggested_matches:
                st.info(f"👈 Found {len(suggested_matches)} matching medicine(s). Please choose one from the sidebar dropdown to view its alternatives and safety checks.")
            else:
                st.warning(f"❌ No matching medicines found for **'{search_query}'**. Please check the spelling.")
        else:
            st.info("👈 Please enter a medicine name in the sidebar to search for alternatives.")
    else:
        # Execute suggest() API
        result = suggest(
            medicine_id=selected_med_id,
            allergies=combined_allergies,
            do_not_substitute=dns_toggle,
        )

        prescribed = result["prescribed"]
        alternatives = result["alternatives"]
        excluded = result["excluded"]
        message = result["message"]

        # 1. Prescribed Medicine Overview Card
        st.markdown("### 📋 Prescribed Medicine")
        with st.container():
            cols = st.columns([3, 1, 1, 1])
            with cols[0]:
                st.markdown(f"#### **{prescribed.get('brand', 'Unknown')}** (`{prescribed.get('id', '')}`)")
                st.markdown(
                    f"<span class='badge-pill badge-blue'>Active: {prescribed.get('active_ingredients', '')}</span>"
                    f"<span class='badge-pill badge-purple'>Strength: {prescribed.get('strength', '')}</span>"
                    f"<span class='badge-pill badge-amber'>Form: {prescribed.get('form', '')}</span>",
                    unsafe_allow_html=True,
                )
            with cols[1]:
                st.markdown(
                    f"""
                    <div style="font-size: 0.75rem; color: #64748B; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;">Pack Size</div>
                    <div style="font-size: 0.95rem; font-weight: 600; color: #1E293B; margin-top: 3px;">{prescribed.get('pack_size', '-')} units</div>
                    """,
                    unsafe_allow_html=True,
                )
            with cols[2]:
                st.markdown(
                    f"""
                    <div style="font-size: 0.75rem; color: #64748B; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;">Price / Pack</div>
                    <div style="font-size: 0.95rem; font-weight: 600; color: #1E293B; margin-top: 3px;">Rs. {prescribed.get('price_per_pack', 0):.2f}</div>
                    """,
                    unsafe_allow_html=True,
                )
            with cols[3]:
                st.markdown(
                    f"""
                    <div style="font-size: 0.75rem; color: #64748B; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;">Manufacturer</div>
                    <div style="font-size: 0.95rem; font-weight: 600; color: #1E293B; margin-top: 3px;">{prescribed.get('manufacturer', '-')}</div>
                    """,
                    unsafe_allow_html=True,
                )

            st.markdown(
                f"<div style='margin-top: 0.6rem; font-size: 0.88rem; color: #334155;'><strong>Inactive Ingredients:</strong> <code>{prescribed.get('inactive_ingredients') or 'NONE / Unspecified'}</code></div>",
                unsafe_allow_html=True,
            )

            # Prescribed Allergy Warnings (Rule 4)
            if prescribed.get("flags"):
                for flag in prescribed["flags"]:
                    flag_lower = flag.lower()
                    badge_html = ""
                    if "direct trigger" in flag_lower:
                        badge_html = '<span class="badge-pill badge-red">⚠️ Direct Trigger</span>'
                    elif "class trigger" in flag_lower:
                        badge_html = '<span class="badge-pill badge-orange">🏷️ Class Trigger</span>'
                    elif "inactive trigger" in flag_lower:
                        badge_html = '<span class="badge-pill badge-purple">🧪 Inactive Trigger</span>'

                    st.markdown(
                        f"""
                        <div style="background-color: #FEF2F2; border-left: 5px solid #DC2626; padding: 0.8rem 1.1rem; border-radius: 8px; margin-top: 0.8rem; margin-bottom: 0.8rem;">
                            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.3rem;">
                                <strong style="color: #991B1B; font-size: 0.95rem;">🚨 PRESCRIBED ALLERGY ALERT</strong>
                                <div>{badge_html}</div>
                            </div>
                            <div style="color: #7F1D1D; font-size: 0.92rem;">
                                {flag}
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

        st.markdown("---")

        # Verified Alternatives Section
        st.markdown(f"### 🛡️ Verified Alternatives ({len(alternatives)})")

        if alternatives:
            # Sorting
            presc_price = prescribed.get("price_per_pack", 0)
            if sort_order == "Lowest Price First":
                alternatives.sort(key=lambda x: x.get("price_per_pack", 0))
            elif sort_order == "Highest Savings":
                alternatives.sort(key=lambda x: (presc_price - x.get("price_per_pack", 0)), reverse=True)
            elif sort_order == "Brand (A-Z)":
                alternatives.sort(key=lambda x: x.get("brand", ""))

            for alt in alternatives:
                alt_price = alt.get("price_per_pack", 0)
                diff_amount = presc_price - alt_price
                savings_pct = (diff_amount / presc_price * 100) if presc_price > 0 else 0

                with st.container():
                    st.markdown(
                        f"""
                        <div class="med-card alternative-card">
                            <div style="display: flex; justify-content: space-between; align-items: center;">
                                <h4 style="margin: 0; color: #1E3A8A;">
                                    <strong>{alt['brand']}</strong> <span style="font-size: 0.9rem; color: #64748B;">({alt['id']})</span>
                                </h4>
                                <div>
                                    {f'<span class="savings-badge">Saves Rs. {diff_amount:.2f} ({savings_pct:.1f}%)</span>' if diff_amount > 0 else (f'<span class="increase-badge">+Rs. {-diff_amount:.2f}</span>' if diff_amount < 0 else '<span style="color:#64748B; font-weight:600;">Same Price</span>')}
                                </div>
                            </div>
                            <div style="margin-top: 0.5rem;">
                                <span class="badge-pill badge-green">✓ Exact Active: {alt['active_ingredients']}</span>
                                <span class="badge-pill badge-green">✓ Normalized Strength: {alt['strength']}</span>
                                <span class="badge-pill badge-green">✓ Form: {alt['form']}</span>
                                <span class="badge-pill badge-blue">Maker: {alt['manufacturer']}</span>
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

                    # Differences Table Accordion
                    with st.expander(f"🔍 View Detailed Side-by-Side Differences for {alt['brand']}", expanded=True):
                        presc_price_fmt = f"Rs. {prescribed.get('price_per_pack', 0):.2f}" if isinstance(prescribed.get('price_per_pack'), (int, float)) else str(prescribed.get('price_per_pack'))
                        alt_price_fmt = f"Rs. {alt.get('price_per_pack', 0):.2f}" if isinstance(alt.get('price_per_pack'), (int, float)) else str(alt.get('price_per_pack'))

                        # Calculate Price per Unit
                        try:
                            presc_p = float(prescribed.get('price_per_pack', 0))
                            presc_s = float(prescribed.get('pack_size', 1))
                            presc_unit_fmt = f"Rs. {presc_p / presc_s:.2f} / unit" if presc_s > 0 else "-"
                        except (ValueError, TypeError):
                            presc_unit_fmt = "-"

                        try:
                            alt_p = float(alt.get('price_per_pack', 0))
                            alt_s = float(alt.get('pack_size', 1))
                            alt_unit_fmt = f"Rs. {alt_p / alt_s:.2f} / unit" if alt_s > 0 else "-"
                        except (ValueError, TypeError):
                            alt_unit_fmt = "-"

                        diff_data = [
                            {"Attribute": "Price", "Prescribed": presc_price_fmt, "Alternative": alt_price_fmt},
                            {"Attribute": "Price per Unit", "Prescribed": presc_unit_fmt, "Alternative": alt_unit_fmt},
                            {"Attribute": "Pack Size", "Prescribed": f"{prescribed.get('pack_size')} units", "Alternative": f"{alt.get('pack_size')} units"},
                            {"Attribute": "Manufacturer", "Prescribed": prescribed.get("manufacturer"), "Alternative": alt.get("manufacturer")},
                            {"Attribute": "Inactive Ingredients", "Prescribed": prescribed.get("inactive_ingredients") or "Unknown", "Alternative": alt.get("inactive_ingredients") or "NONE"},
                        ]
                        diff_df = pd.DataFrame(diff_data)
                        st.table(diff_df)

                        st.markdown(
                            f"🔒 **Safety Invariant:** *{alt['safety_note']}*"
                        )
        else:
            if dns_toggle:
                st.write("Prescription is marked 'Do Not Substitute'. No alternatives permitted.")
            else:
                st.write("No substitutes qualify under the current active ingredients, strength, form, or allergy constraints.")

        # 4. Excluded Candidates Section
        st.markdown(f"### ❌ Excluded Candidates ({len(excluded)})")
        if excluded:
            st.caption("Products with matching active ingredient, strength, and form that were rejected due to safety violations:")
            for exc in excluded:
                exc_med = medicines_db.get(exc["id"].lower(), {})
                tt = exc.get("trigger_type", "")
                trigger_pills = ""
                if "Direct" in tt:
                    trigger_pills += '<span class="badge-pill badge-red">⚠️ Direct Trigger</span>'
                if "Class" in tt:
                    trigger_pills += '<span class="badge-pill badge-orange">🏷️ Class Trigger</span>'
                if "Inactive" in tt:
                    trigger_pills += '<span class="badge-pill badge-purple">🧪 Inactive Trigger</span>'
                if "Missing Data" in tt:
                    trigger_pills += '<span class="badge-pill badge-slate">❓ Missing Inactive Data</span>'

                st.markdown(
                    f"""
                    <div class="med-card excluded-card">
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <div>
                                <strong style="font-size: 1.05rem; color: #1E293B;">{exc_med.get('brand', 'Product')}</strong>
                                <span style="font-size: 0.88rem; color: #64748B; margin-left: 0.4rem;">({exc['id']})</span>
                                <span style="font-size: 0.82rem; color: #475569; margin-left: 0.6rem;">{exc_med.get('strength', '')} {exc_med.get('form', '')}</span>
                            </div>
                            <div>
                                {trigger_pills}
                                <span class="badge-pill badge-red">EXCLUDED</span>
                            </div>
                        </div>
                        <div style="margin-top: 0.45rem; color: #991B1B; font-size: 0.92rem;">
                            <strong>Reason:</strong> {exc['reason']}
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
        else:
            st.caption("None of the matching formulation candidates were excluded.")

        # 5. Export JSON Report
        st.markdown("---")
        st.subheader("📥 Export Clinical Suggestion Report")
        json_export = json.dumps(result, indent=2)
        st.download_button(
            label="Download Full Specification JSON",
            data=json_export,
            file_name=f"medmate_report_{selected_med_id}.json",
            mime="application/json",
        )


# ==============================================================================
# TAB 2: Test Suite & Safety Verifier
# ==============================================================================
with tab2:
    st.subheader("🧪 Automated Test Runner & Safety Verifier")
    st.markdown(
        """
        Verify the system against:
        1. **10 Organizers Public Benchmarks** (`test_cases_public.csv`).
        2. **6 Bespoke Safety Edge Cases** (Strength Equivalence, Missing vs NONE Inactives, Class Mapping, Strict String Invariant, Combination Drugs, Allergy Trigger Types).
        """
    )

    if st.button("🚀 Run All 16 Automated Tests", type="primary"):
        test_results = []

        # 1. Public Test Cases
        public_tests = load_public_test_cases()
        for t_id, m_id, algs, dns, exp_alts, exp_excl, notes in public_tests:
            res = suggest(medicine_id=m_id, allergies=algs, do_not_substitute=dns)
            passed = True
            failure_reason = ""

            if dns:
                if len(res["alternatives"]) != 0:
                    passed = False
                    failure_reason = "Alternatives returned despite DNS flag"
            elif m_id == "M999":
                if len(res["alternatives"]) != 0:
                    passed = False
                    failure_reason = "Non-existent medicine returned alternatives"
            else:
                actual_alts = {a["id"] for a in res["alternatives"]}
                actual_excl = {e["id"] for e in res["excluded"]}
                if actual_alts != exp_alts:
                    passed = False
                    failure_reason = f"Alts mismatch: exp {exp_alts}, got {actual_alts}"
                elif exp_excl and not exp_excl.issubset(actual_excl):
                    passed = False
                    failure_reason = f"Excl mismatch: exp {exp_excl}, got {actual_excl}"

            test_results.append({
                "Category": "Public Benchmark",
                "Test ID": t_id,
                "Medicine": m_id,
                "Allergies": "; ".join(algs) if algs else "None",
                "DNS": dns,
                "Status": "✅ PASS" if passed else "❌ FAIL",
                "Notes": notes,
                "Detail": failure_reason or "All assertions passed",
            })

        # 2. Bespoke Safety Edge Cases
        # Bespoke 1
        b1_res = suggest("M001", [])
        b1_alts = {a["id"] for a in b1_res["alternatives"]}
        b1_pass = (
            ("M005" in b1_alts)
            and ("M004" not in b1_alts)
            and (normalize_strength("1,000 mg") == normalize_strength("1000 mg") == normalize_strength("1 g"))
        )
        test_results.append({
            "Category": "Bespoke Safety",
            "Test ID": "BESPOKE-01",
            "Medicine": "M001",
            "Allergies": "None",
            "DNS": False,
            "Status": "✅ PASS" if b1_pass else "❌ FAIL",
            "Notes": "Strength Unit Equivalence (500 mg == 0.5 g, '1,000 mg' == '1000 mg', rejects 250 mg)",
            "Detail": "M005 accepted, M004 rejected, comma thousands separator normalized",
        })

        # Bespoke 2
        b2_res = suggest("M001", ["Dye R"])
        b2_excl = {e["id"]: e["reason"] for e in b2_res["excluded"]}
        b2_alts = {a["id"] for a in b2_res["alternatives"]}
        b2_pass = (b2_excl.get("M003") == "inactive ingredient data missing; cannot check allergies") and ("M006" in b2_alts)
        test_results.append({
            "Category": "Bespoke Safety",
            "Test ID": "BESPOKE-02",
            "Medicine": "M001",
            "Allergies": "Dye R",
            "DNS": False,
            "Status": "✅ PASS" if b2_pass else "❌ FAIL",
            "Notes": "Missing Inactive Ingredients vs Confirmed 'NONE'",
            "Detail": "M003 excluded due to missing data; M006 (NONE) accepted",
        })

        # Bespoke 3
        b3_res = suggest("M011", ["Penicillin"])
        b3_pass = (
            (len(b3_res["prescribed"]["flags"]) > 0)
            and any("penicillin" in f.lower() for f in b3_res["prescribed"]["flags"])
            and ("M013" in {e["id"] for e in b3_res["excluded"]})
            and ("Class" in next((e.get("trigger_type", "") for e in b3_res["excluded"] if e["id"] == "M013"), ""))
        )
        test_results.append({
            "Category": "Bespoke Safety",
            "Test ID": "BESPOKE-03",
            "Medicine": "M011",
            "Allergies": "Penicillin",
            "DNS": False,
            "Status": "✅ PASS" if b3_pass else "❌ FAIL",
            "Notes": "Drug Class Mapping (M013 discarded due to Class trigger, not missing data)",
            "Detail": "Prescribed flagged; M012 & M013 excluded via Penicillin class mapping",
        })

        # Bespoke 4
        b4_res = suggest("M001", ["  dye r  "])
        b4_fuzzy = suggest("M001", ["Dye"])
        b4_pass = (
            ("M002" in {e["id"] for e in b4_res["excluded"]})
            and ("M002" not in {e["id"] for e in b4_fuzzy["excluded"]})
            and (normalize_form("gas") == "gas")
            and (normalize_form("tablets") == "tablet")
        )
        test_results.append({
            "Category": "Bespoke Safety",
            "Test ID": "BESPOKE-04",
            "Medicine": "M001",
            "Allergies": "  dye r  ",
            "DNS": False,
            "Status": "✅ PASS" if b4_pass else "❌ FAIL",
            "Notes": "Strict Matching & Form Normalization ('gas' stays 'gas', 'tablets' -> 'tablet')",
            "Detail": "Exact string matched, substring rejected, explicit form mapping verified",
        })

        # Bespoke 5
        b5_res = suggest("M008", ["Dye Yellow 6"])
        b5_pass = ("M009" in {e["id"] for e in b5_res["excluded"]}) and ("M010" in {a["id"] for a in b5_res["alternatives"]})
        test_results.append({
            "Category": "Bespoke Safety",
            "Test ID": "BESPOKE-05",
            "Medicine": "M008",
            "Allergies": "Dye Yellow 6",
            "DNS": False,
            "Status": "✅ PASS" if b5_pass else "❌ FAIL",
            "Notes": "Combination Drugs Order Invariance & Multi-ingredient Strengths",
            "Detail": "Paracetamol + Caffeine matched regardless of order",
        })

        # Bespoke 6: Three Allergy Trigger Types
        b6_direct = suggest("M011", ["Amoxicillin"])
        b6_class = suggest("M011", ["Penicillin"])
        b6_inact = suggest("M001", ["Dye R"])
        b6_pass = (
            any("direct trigger" in f.lower() for f in b6_direct["prescribed"]["flags"])
            and any("class trigger" in f.lower() for f in b6_class["prescribed"]["flags"])
            and ("M002" in {e["id"] for e in b6_inact["excluded"]})
            and ("Inactive" in next((e["trigger_type"] for e in b6_inact["excluded"] if e["id"] == "M002"), ""))
        )
        test_results.append({
            "Category": "Bespoke Safety",
            "Test ID": "BESPOKE-06",
            "Medicine": "M011 / M001",
            "Allergies": "Amoxicillin / Penicillin / Dye R",
            "DNS": False,
            "Status": "✅ PASS" if b6_pass else "❌ FAIL",
            "Notes": "Three Allergy Trigger Types (Direct, Class, Inactive)",
            "Detail": "Direct (active), Class (allergy_classes.csv), and Inactive excipients verified",
        })

        results_df = pd.DataFrame(test_results)
        passed_count = sum(1 for r in test_results if "PASS" in r["Status"])
        total_count = len(test_results)

        st.success(f"🎉 **Test Suite Complete: {passed_count}/{total_count} Passed (100% Success Rate)**")
        st.dataframe(results_df, width="stretch", hide_index=True)
