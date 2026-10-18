#!/usr/bin/env python3
"""MedMate CLI: Medicine Alternative Suggester with Allergy Check.

A safety-first, deterministic command-line interface for:
- Suggesting bioequivalent alternatives with allergy evaluation
- Typo-tolerant medicine searching
- Inspecting formulation and excipient details
- Running automated test suites from the terminal
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional

# Enable ANSI escape sequences on Windows
# Force UTF-8 stdout/stderr on Windows/CP1252 to prevent encoding errors
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

if sys.platform == "win32":
    os.system("")

from medmate import (
    compute_differences,
    load_allergy_classes,
    load_medicines,
    normalize_form,
    normalize_strength,
    normalize_text,
    search_medicines,
    suggest,
)
from test_medmate import load_public_test_cases


# ==============================================================================
# Terminal Color & Styling Utilities
# ==============================================================================

class Color:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    ITALIC = "\033[3m"
    UNDERLINE = "\033[4m"

    # Foreground
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"

    # Background
    BG_RED = "\033[41m"
    BG_GREEN = "\033[42m"
    BG_YELLOW = "\033[43m"
    BG_BLUE = "\033[44m"
    BG_MAGENTA = "\033[45m"


def header(text: str) -> str:
    line = "=" * max(65, len(text) + 6)
    return f"\n{Color.BOLD}{Color.CYAN}{line}\n   {text}\n{line}{Color.RESET}"


def section(text: str) -> str:
    return f"\n{Color.BOLD}{Color.BLUE}--- {text} ---{Color.RESET}"


def badge(text: str, color: str = Color.CYAN) -> str:
    return f"{color}[{text}]{Color.RESET}"


# ==============================================================================
# CLI Formatters
# ==============================================================================

def print_banner() -> None:
    print(fr"""{Color.BOLD}{Color.CYAN}
  __  __          _ __  __ ate
 |  \/  | ___  __| |  \/  | __ _ _| |_ ___ 
 | |\/| |/ _ \/ _` | |\/| |/ _` | | __/ _ \
 |_|  |_|\___/\__,_|_|  |_|\__,_|_|\__\___/  {Color.RESET}{Color.DIM}v1.0 (Safety-First Medicine Engine){Color.RESET}
  {Color.YELLOW}Deterministic * 3-Tier Allergy Guard * Unit Equivalence * No Fuzzy Actives{Color.RESET}
""")


def display_medicine_card(med: Dict[str, Any], title: str = "Medicine Information") -> None:
    print(section(title))
    print(f"  {Color.BOLD}Brand:{Color.RESET} {med.get('brand')}  {Color.DIM}(ID: {med.get('id')}){Color.RESET}")
    print(f"  {Color.BOLD}Active:{Color.RESET} {Color.CYAN}{med.get('active_ingredients')}{Color.RESET} | {Color.BOLD}Strength:{Color.RESET} {med.get('strength')} | {Color.BOLD}Form:{Color.RESET} {med.get('form')}")
    print(f"  {Color.BOLD}Manufacturer:{Color.RESET} {med.get('manufacturer')}")
    
    # Calculate price per unit
    try:
        p = float(med.get("price_per_pack", 0))
        s = float(med.get("pack_size", 1))
        unit_str = f"Rs. {p / s:.2f} / unit" if s > 0 else "-"
    except (ValueError, TypeError):
        unit_str = "-"
        
    print(f"  {Color.BOLD}Price / Pack:{Color.RESET} Rs. {med.get('price_per_pack', 0):.2f}  |  {Color.BOLD}Pack Size:{Color.RESET} {med.get('pack_size')} units  |  {Color.BOLD}Unit Price:{Color.RESET} {unit_str}")
    print(f"  {Color.BOLD}Inactive Inactive Excipients:{Color.RESET} {med.get('inactive_ingredients') or Color.DIM + 'NONE / Unspecified' + Color.RESET}")


def display_differences_table(prescribed: Dict[str, Any], alt: Dict[str, Any]) -> None:
    """Renders a clean CLI side-by-side table of attributes."""
    try:
        presc_p = float(prescribed.get("price_per_pack", 0))
        presc_s = float(prescribed.get("pack_size", 1))
        presc_unit = f"Rs. {presc_p / presc_s:.2f} / unit" if presc_s > 0 else "-"
    except (ValueError, TypeError):
        presc_unit = "-"

    try:
        alt_p = float(alt.get("price_per_pack", 0))
        alt_s = float(alt.get("pack_size", 1))
        alt_unit = f"Rs. {alt_p / alt_s:.2f} / unit" if alt_s > 0 else "-"
    except (ValueError, TypeError):
        alt_unit = "-"

    rows = [
        ("Price", f"Rs. {prescribed.get('price_per_pack', 0):.2f}", f"Rs. {alt.get('price_per_pack', 0):.2f}"),
        ("Price per Unit", presc_unit, alt_unit),
        ("Pack Size", f"{prescribed.get('pack_size')} units", f"{alt.get('pack_size')} units"),
        ("Manufacturer", prescribed.get("manufacturer") or "-", alt.get("manufacturer") or "-"),
        ("Inactive Ingredients", prescribed.get("inactive_ingredients") or "Unknown", alt.get("inactive_ingredients") or "NONE"),
    ]

    col1_w = 22
    col2_w = 34
    col3_w = 34

    border = f"  +{'-' * col1_w}+{'-' * col2_w}+{'-' * col3_w}+"
    print(border)
    print(f"  | {Color.BOLD}{'Attribute':<{col1_w - 2}}{Color.RESET} | {Color.BOLD}{'Prescribed (' + prescribed.get('id', '') + ')':<{col2_w - 2}}{Color.RESET} | {Color.BOLD}{'Alternative (' + alt.get('id', '') + ')':<{col3_w - 2}}{Color.RESET} |")
    print(border)
    for attr, pres_val, alt_val in rows:
        print(f"  | {attr:<{col1_w - 2}} | {pres_val:<{col2_w - 2}} | {alt_val:<{col3_w - 2}} |")
    print(border)


def display_results(result: Dict[str, Any]) -> None:
    """Formats and prints the standard suggest() output."""
    prescribed = result.get("prescribed", {})
    alternatives = result.get("alternatives", [])
    excluded = result.get("excluded", [])
    message = result.get("message", "")

    # 1. Prescribed Info Card
    display_medicine_card(prescribed, title="Prescribed Medicine")

    # Prescribed Allergy Warnings
    flags = prescribed.get("flags", [])
    if flags:
        print(f"\n  {Color.BG_RED}{Color.WHITE}{Color.BOLD} [!] PRESCRIBED ALLERGY WARNING [!] {Color.RESET}")
        for flag in flags:
            print(f"  {Color.RED}{Color.BOLD}* {flag}{Color.RESET}")

    # 2. Verified Alternatives
    print(section(f"Verified Alternatives ({len(alternatives)})"))
    if alternatives:
        presc_price = float(prescribed.get("price_per_pack", 0))
        for idx, alt in enumerate(alternatives, 1):
            alt_price = float(alt.get("price_per_pack", 0))
            diff = presc_price - alt_price
            savings_pct = (diff / presc_price * 100) if presc_price > 0 else 0

            if diff > 0:
                sav_badge = f"{Color.GREEN}{Color.BOLD}[Saves Rs. {diff:.2f} ({savings_pct:.1f}%)]"
            elif diff < 0:
                sav_badge = f"{Color.RED}[+Rs. {-diff:.2f}]"
            else:
                sav_badge = f"{Color.DIM}[Same Price]"

            print(f"\n  {Color.BOLD}{Color.GREEN}{idx}. {alt['brand']}{Color.RESET} {Color.DIM}({alt['id']}){Color.RESET} {sav_badge}{Color.RESET}")
            print(f"     Active: {alt['active_ingredients']} | Strength: {alt['strength']} | Form: {alt['form']}")
            
            # Differences Table
            display_differences_table(prescribed, alt)
            print(f"     {Color.DIM}[*] Safety Note: {alt.get('safety_note')}{Color.RESET}")
    else:
        print(f"  {Color.DIM}No verified alternatives qualify under the current constraints.{Color.RESET}")

    # 3. Excluded Candidates
    print(section(f"Excluded Candidates ({len(excluded)})"))
    if excluded:
        meds_db = load_medicines()
        for idx, exc in enumerate(excluded, 1):
            cand_id = exc.get("id", "")
            cand_med = meds_db.get(cand_id.lower(), {})
            tt = exc.get("trigger_type", "")

            # Color-coded trigger badges
            pill_text = ""
            if "Direct" in tt:
                pill_text += f"{Color.RED}{Color.BOLD}[ DIRECT TRIGGER ]{Color.RESET} "
            if "Class" in tt:
                pill_text += f"{Color.YELLOW}{Color.BOLD}[ CLASS TRIGGER ]{Color.RESET} "
            if "Inactive" in tt:
                pill_text += f"{Color.MAGENTA}{Color.BOLD}[ INACTIVE TRIGGER ]{Color.RESET} "
            if "Missing Data" in tt:
                pill_text += f"{Color.WHITE}{Color.DIM}[ MISSING INACTIVE DATA ]{Color.RESET} "

            print(f"  {idx}. {Color.BOLD}{cand_med.get('brand', 'Candidate')}{Color.RESET} {Color.DIM}({cand_id}){Color.RESET} {pill_text}")
            print(f"     {Color.RED}Reason: {exc.get('reason')}{Color.RESET}")
    else:
        print(f"  {Color.DIM}No matching formulation candidates were excluded.{Color.RESET}")

    # 4. Final Status Message
    print(f"\n  {Color.BOLD}Status Message:{Color.RESET} {message}\n")


# ==============================================================================
# CLI Commands
# ==============================================================================

def cmd_suggest(args: argparse.Namespace) -> None:
    """Executes suggest command."""
    med_id = (args.id or "").strip()

    if not med_id and args.medicine:
        matches = search_medicines(args.medicine.strip(), limit=5)
        if not matches:
            print(f"{Color.RED}Error: No medicines found matching '{args.medicine}'.{Color.RESET}", file=sys.stderr)
            sys.exit(1)
        med_id = matches[0]["id"]
        if len(matches) > 1 and not args.json:
            print(f"{Color.DIM}Multiple matches found for '{args.medicine}'; using best match: {matches[0]['brand']} ({med_id}){Color.RESET}")
    elif not med_id:
        print(f"{Color.RED}Error: Please specify medicine with --id or --medicine.{Color.RESET}", file=sys.stderr)
        sys.exit(1)

    # Process allergies
    allergies: List[str] = []
    if args.allergies:
        for item in args.allergies:
            allergies.extend([a.strip() for a in item.split(",") if a.strip()])

    result = suggest(
        medicine_id=med_id,
        allergies=allergies,
        do_not_substitute=args.dns,
    )

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print_banner()
        print(f"{Color.BOLD}Running Evaluation:{Color.RESET} Medicine={Color.CYAN}{med_id}{Color.RESET} | Allergies={Color.YELLOW}{allergies or 'None'}{Color.RESET} | DNS={args.dns}")
        display_results(result)


def cmd_search(args: argparse.Namespace) -> None:
    """Executes search command."""
    query = args.query.strip()
    matches = search_medicines(query, limit=args.limit)

    if args.json:
        print(json.dumps(matches, indent=2))
        return

    print_banner()
    print(header(f"Search Results for '{query}' ({len(matches)} found)"))
    if not matches:
        print(f"  {Color.RED}No matching medicines found for '{query}'.{Color.RESET}")
        return

    col1 = 8
    col2 = 18
    col3 = 24
    col4 = 14
    col5 = 10
    col6 = 18
    col7 = 12

    hdr = f"  | {'ID':<{col1}} | {'Brand':<{col2}} | {'Active Ingredients':<{col3}} | {'Strength':<{col4}} | {'Form':<{col5}} | {'Manufacturer':<{col6}} | {'Price':<{col7}} |"
    line = f"  +{'-' * (col1 + 2)}+{'-' * (col2 + 2)}+{'-' * (col3 + 2)}+{'-' * (col4 + 2)}+{'-' * (col5 + 2)}+{'-' * (col6 + 2)}+{'-' * (col7 + 2)}+"

    print(line)
    print(hdr)
    print(line)
    for m in matches:
        print(f"  | {m['id']:<{col1}} | {m['brand']:<{col2}} | {m['active_ingredients']:<{col3}} | {m['strength']:<{col4}} | {m['form']:<{col5}} | {m['manufacturer']:<{col6}} | Rs. {m['price_per_pack']:<{col7 - 4}.2f} |")
    print(line)
    print()


def cmd_details(args: argparse.Namespace) -> None:
    """Displays full details of a specific medicine ID."""
    med_id = args.id.strip().lower()
    meds_db = load_medicines()

    if med_id not in meds_db:
        print(f"{Color.RED}Error: Medicine ID '{args.id}' not found in database.{Color.RESET}", file=sys.stderr)
        sys.exit(1)

    med = meds_db[med_id]
    if args.json:
        print(json.dumps(med, indent=2))
    else:
        print_banner()
        display_medicine_card(med, title=f"Medicine Dossier: {med['brand']} ({med['id']})")
        print()


def cmd_test(args: argparse.Namespace) -> None:
    """Executes the test suite directly from CLI."""
    print_banner()
    print(header("MedMate Automated Clinical Test Suite (17 Tests)"))

    test_cases = load_public_test_cases()
    passed = 0
    total = len(test_cases) + 7  # 10 public + 6 bespoke + 1 search

    print(f"\n{Color.BOLD}1. Public Benchmark Test Cases (test_cases_public.csv):{Color.RESET}")
    for t_id, m_id, algs, dns, exp_alts, exp_excl, notes in test_cases:
        res = suggest(m_id, algs, do_not_substitute=dns)
        act_alts = {a["id"] for a in res["alternatives"]}
        act_excl = {e["id"] for e in res["excluded"]}

        ok = True
        if dns and len(res["alternatives"]) != 0:
            ok = False
        elif m_id == "M999" and len(res["alternatives"]) != 0:
            ok = False
        elif act_alts != exp_alts:
            ok = False
        elif exp_excl and not exp_excl.issubset(act_excl):
            ok = False

        status_str = f"{Color.GREEN}PASS{Color.RESET}" if ok else f"{Color.RED}FAIL{Color.RESET}"
        if ok:
            passed += 1
        print(f"  [{status_str}] {t_id:<5} | Med: {m_id:<4} | Algs: {str(algs):<26} | DNS: {str(dns):<5} | Alts: {len(act_alts)} | {Color.DIM}{notes}{Color.RESET}")

    print(f"\n{Color.BOLD}2. Bespoke Safety & Pharmacology Edge Cases:{Color.RESET}")
    # Bespoke 1
    b1_res = suggest("M001", [])
    b1_alts = {a["id"] for a in b1_res["alternatives"]}
    from medmate import normalize_strength
    b1_ok = ("M005" in b1_alts) and ("M004" not in b1_alts) and (normalize_strength("1,000 mg") == normalize_strength("1000 mg") == normalize_strength("1 g"))
    if b1_ok: passed += 1
    print(f"  [{Color.GREEN if b1_ok else Color.RED}{'PASS' if b1_ok else 'FAIL'}{Color.RESET}] BESPOKE-01 | Unit Equivalence (500 mg == 0.5 g, '1,000 mg' == '1000 mg', rejects 250 mg)")

    # Bespoke 2
    b2_res = suggest("M001", ["Dye R"])
    b2_excl = {e["id"]: e["reason"] for e in b2_res["excluded"]}
    b2_alts = {a["id"] for a in b2_res["alternatives"]}
    b2_ok = (b2_excl.get("M003") == "inactive ingredient data missing; cannot check allergies") and ("M006" in b2_alts)
    if b2_ok: passed += 1
    print(f"  [{Color.GREEN if b2_ok else Color.RED}{'PASS' if b2_ok else 'FAIL'}{Color.RESET}] BESPOKE-02 | Missing Inactive Excipients vs Confirmed 'NONE'")

    # Bespoke 3
    b3_res = suggest("M011", ["Penicillin"])
    b3_excl = {e["id"]: e.get("trigger_type", "") for e in b3_res["excluded"]}
    b3_ok = (len(b3_res["prescribed"]["flags"]) > 0) and ("Class" in b3_excl.get("M013", "")) and ("Class" in b3_excl.get("M012", ""))
    if b3_ok: passed += 1
    print(f"  [{Color.GREEN if b3_ok else Color.RED}{'PASS' if b3_ok else 'FAIL'}{Color.RESET}] BESPOKE-03 | Drug Class Mapping (M013 discarded due to Class trigger, not missing data)")

    # Bespoke 4
    b4_res = suggest("M001", ["  dye r  "])
    b4_fuzzy = suggest("M001", ["Dye"])
    b4_ok = (
        ("M002" in {e["id"] for e in b4_res["excluded"]})
        and ("M002" not in {e["id"] for e in b4_fuzzy["excluded"]})
        and (normalize_form("gas") == "gas")
        and (normalize_form("tablets") == "tablet")
    )
    if b4_ok: passed += 1
    print(f"  [{Color.GREEN if b4_ok else Color.RED}{'PASS' if b4_ok else 'FAIL'}{Color.RESET}] BESPOKE-04 | Strict Matching & Form Normalization ('gas' stays 'gas', 'tablets' -> 'tablet')")

    # Bespoke 5
    b5_res = suggest("M008", ["Dye Yellow 6"])
    b5_ok = ("M009" in {e["id"] for e in b5_res["excluded"]}) and ("M010" in {a["id"] for a in b5_res["alternatives"]})
    if b5_ok: passed += 1
    print(f"  [{Color.GREEN if b5_ok else Color.RED}{'PASS' if b5_ok else 'FAIL'}{Color.RESET}] BESPOKE-05 | Combination Drugs Order Invariance & Multi-ingredient Strengths")

    # Bespoke 6
    b6_direct = suggest("M011", ["Amoxicillin"])
    b6_class = suggest("M011", ["Penicillin"])
    b6_inact = suggest("M001", ["Dye R"])
    b6_ok = (
        any("direct trigger" in f.lower() for f in b6_direct["prescribed"]["flags"])
        and any("class trigger" in f.lower() for f in b6_class["prescribed"]["flags"])
        and ("M002" in {e["id"] for e in b6_inact["excluded"]})
    )
    if b6_ok: passed += 1
    print(f"  [{Color.GREEN if b6_ok else Color.RED}{'PASS' if b6_ok else 'FAIL'}{Color.RESET}] BESPOKE-06 | Three Allergy Trigger Types (Direct, Class, Inactive)")

    # Typo Search
    search_res = search_medicines("Zolvexn")
    search_ok = any(r["id"] == "M001" for r in search_res)
    if search_ok: passed += 1
    print(f"  [{Color.GREEN if search_ok else Color.RED}{'PASS' if search_ok else 'FAIL'}{Color.RESET}] BESPOKE-07 | Typo-Tolerant Search ('Zolvexn' finds 'Zolvexin')")

    print(header(f"Results: {passed}/{total} Passed ({passed/total*100:.1f}% Success Rate)"))
    print()


def cmd_interactive() -> None:
    """Guided interactive step-by-step terminal wizard."""
    print_banner()
    print(header("Interactive Prescription Suggester Wizard"))

    try:
        # Step 1: Search medicine
        print(f"{Color.BOLD}Step 1: Enter Prescribed Medicine Name or ID{Color.RESET}")
        query = input("  > ").strip()
        if not query:
            print(f"{Color.RED}Medicine input required.{Color.RESET}")
            return

        matches = search_medicines(query, limit=10)
        if not matches:
            print(f"{Color.RED}No matching medicines found for '{query}'. Please check the name.{Color.RESET}")
            return

        print(f"\n{Color.BOLD}Matching options found ({len(matches)}):{Color.RESET}")
        for idx, m in enumerate(matches, 1):
            print(f"  [{idx}] {Color.BOLD}{m['brand']}{Color.RESET} ({m['id']}) - {m['strength']}, {m['form']} [{m['manufacturer']}]")

        choice = input(f"\nChoose option [1-{len(matches)}]: ").strip()
        choice_idx = int(choice) - 1 if choice.isdigit() and 1 <= int(choice) <= len(matches) else 0
        selected_med = matches[choice_idx]
        selected_id = selected_med["id"]
        print(f"[+] Selected: {Color.GREEN}{selected_med['brand']} ({selected_id}){Color.RESET}")

        # Step 2: Allergies
        print(f"\n{Color.BOLD}Step 2: Enter Patient Allergies (comma-separated, or press Enter for None){Color.RESET}")
        alg_input = input("  > ").strip()
        allergies = [a.strip() for a in alg_input.split(",") if a.strip()]
        if allergies:
            print(f"[+] Active allergies: {Color.YELLOW}{allergies}{Color.RESET}")
        else:
            print("[+] No allergies specified.")

        # Step 3: Do Not Substitute
        print(f"\n{Color.BOLD}Step 3: Is prescription marked 'Do Not Substitute' (DNS)? [y/N]{Color.RESET}")
        dns_input = input("  > ").strip().lower()
        dns = dns_input in {"y", "yes", "true", "1"}
        if dns:
            print(f"{Color.RED}[+] 'Do Not Substitute' active: 0 alternatives permitted.{Color.RESET}")

        # Run suggest
        print(header("Computing Verified Alternatives..."))
        result = suggest(selected_id, allergies, do_not_substitute=dns)
        display_results(result)

    except (KeyboardInterrupt, EOFError):
        print("\n\nOperation cancelled by user.")
        sys.exit(0)


# ==============================================================================
# Argument Parsing Entrypoint
# ==============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="cli.py",
        description="MedMate: Deterministic Medicine Alternative Suggester with Allergy Checks",
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    # Subcommand: suggest
    p_suggest = subparsers.add_parser("suggest", help="Suggest alternatives for a prescribed medicine")
    p_suggest.add_argument("--id", "-i", type=str, default="", help="Medicine ID (e.g. M001)")
    p_suggest.add_argument("--medicine", "-m", type=str, default="", help="Medicine Brand/Name (uses typo-tolerant search)")
    p_suggest.add_argument("--allergies", "-a", nargs="*", default=[], help="Allergies (e.g. -a 'Dye R' Penicillin)")
    p_suggest.add_argument("--dns", action="store_true", help="Do Not Substitute flag")
    p_suggest.add_argument("--json", action="store_true", help="Output specification JSON")

    # Subcommand: search
    p_search = subparsers.add_parser("search", help="Typo-tolerant medicine search")
    p_search.add_argument("query", type=str, help="Search term (brand name, ID, or partial)")
    p_search.add_argument("--limit", "-l", type=int, default=10, help="Max results to return")
    p_search.add_argument("--json", action="store_true", help="Output JSON array")

    # Subcommand: details
    p_details = subparsers.add_parser("details", help="View full formulation & excipients of a medicine ID")
    p_details.add_argument("id", type=str, help="Medicine ID (e.g. M001)")
    p_details.add_argument("--json", action="store_true", help="Output JSON object")

    # Subcommand: test
    subparsers.add_parser("test", help="Run the automated test suite (17 tests)")

    # Subcommand: interactive
    subparsers.add_parser("interactive", help="Start the interactive prescription wizard")

    # Root flags if no subcommand passed
    parser.add_argument("--id", "-i", type=str, default="", help="Prescribed Medicine ID")
    parser.add_argument("--medicine", "-m", type=str, default="", help="Prescribed Medicine Name")
    parser.add_argument("--allergies", "-a", nargs="*", default=[], help="Allergies list")
    parser.add_argument("--dns", action="store_true", help="Do Not Substitute flag")
    parser.add_argument("--json", action="store_true", help="Output JSON")

    args = parser.parse_args()

    if args.subcommand == "suggest":
        cmd_suggest(args)
    elif args.subcommand == "search":
        cmd_search(args)
    elif args.subcommand == "details":
        cmd_details(args)
    elif args.subcommand == "test":
        cmd_test(args)
    elif args.subcommand == "interactive":
        cmd_interactive()
    elif args.id or args.medicine:
        cmd_suggest(args)
    else:
        # If no arguments provided at all, enter interactive wizard by default!
        cmd_interactive()


if __name__ == "__main__":
    main()
