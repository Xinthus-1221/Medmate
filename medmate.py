"""MedMate: Medicine Alternative Suggester with Allergy Check.

Core rule engine providing deterministic medicine matching, allergy checking,
safety constraint enforcement, and side-by-side difference tables.
"""

from __future__ import annotations

import csv
import difflib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


# ==============================================================================
# File Path Resolution Helpers
# ==============================================================================

def get_data_path(filename: str, override_path: Optional[str] = None) -> Path:
    """Locates a data file with multiple fallback strategies."""
    if override_path and os.path.exists(override_path):
        return Path(override_path)

    base_dir = Path(__file__).resolve().parent
    candidates = [
        Path.cwd() / filename,
        Path.cwd() / "data" / filename,
        base_dir / filename,
        base_dir / "data" / filename,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate

    return base_dir / filename


# ==============================================================================
# String and Unit Normalization
# ==============================================================================

def normalize_text(text: Optional[str]) -> str:
    """Normalizes a string by trimming whitespace and converting to lowercase."""
    return (text or "").strip().lower()


def normalize_single_strength(strength: str) -> str:
    """Normalizes a single strength component, converting equivalent units.

    Examples:
        '500 mg' -> '500 mg'
        '0.5 g'   -> '500 mg'
        '1,000 mg' -> '1000 mg'
        '250 mcg' -> '0.25 mg'
        '1000 ug' -> '1 mg'
        '10 mg / 5 ml' -> '2 mg/ml'
    """
    s = normalize_text(strength)
    if not s:
        return ""

    # Remove thousands separator commas between digits (e.g. "1,000 mg" -> "1000 mg", "1,000,000 mcg" -> "1000000 mcg")
    s = re.sub(r"(?<=\d),(?=\d{3}(?:\b|\D))", "", s)

    # Check for concentration ratio like "10 mg / 5 ml"
    ratio_match = re.match(r"^([0-9]+(?:\.[0-9]+)?)\s*mg\s*/\s*([0-9]+(?:\.[0-9]+)?)\s*ml$", s)
    if ratio_match:
        numerator = float(ratio_match.group(1))
        denominator = float(ratio_match.group(2))
        if denominator != 0:
            val = numerator / denominator
            return f"{val:g} mg/ml"

    # Match number and unit
    match = re.match(r"^([0-9]+(?:\.[0-9]+)?)\s*([a-zA-Z%µ]+)$", s)
    if not match:
        return s

    num = float(match.group(1))
    unit = match.group(2)

    # Mass conversions to standard mg
    if unit in {"g", "gram", "grams", "gm"}:
        mg = num * 1000.0
        return f"{mg:g} mg"
    elif unit in {"mg", "milligram", "milligrams"}:
        return f"{num:g} mg"
    elif unit in {"mcg", "ug", "µg", "microgram", "micrograms"}:
        mg = num / 1000.0
        return f"{mg:g} mg"
    elif unit in {"kg", "kilogram", "kilograms"}:
        mg = num * 1000000.0
        return f"{mg:g} mg"

    # Volume conversions to standard ml
    elif unit in {"l", "liter", "litres", "litre"}:
        ml = num * 1000.0
        return f"{ml:g} ml"
    elif unit in {"ml", "milliliter", "millilitres", "millilitre"}:
        return f"{num:g} ml"

    elif unit == "%":
        return f"{num:g}%"

    return f"{num:g} {unit}"


def normalize_strength(strength_str: str) -> str:
    """Normalizes potentially combined strength strings (e.g. '500 mg + 65 mg')."""
    if not strength_str:
        return ""
    parts = [p.strip() for p in strength_str.split("+") if p.strip()]
    norm_parts = [normalize_single_strength(p) for p in parts]
    return " + ".join(norm_parts)


def normalize_form(form_str: str) -> str:
    """Normalizes dosage form (tablet, capsule, syrup, etc.)."""
    f = normalize_text(form_str)
    # Explicit mapping for common plurals without stripping arbitrary trailing 's' (e.g. 'gas' stays 'gas')
    form_map = {
        "tablets": "tablet",
        "capsules": "capsule",
        "caplets": "caplet",
        "pills": "pill",
        "lozenges": "lozenge",
        "suppositories": "suppository",
        "injections": "injection",
        "ampoules": "ampoule",
        "vials": "vial",
        "patches": "patch",
    }
    return form_map.get(f, f)


def parse_active_ingredients(active_str: str) -> List[str]:
    """Splits combination active ingredients by '+' and normalizes spacing."""
    if not active_str:
        return []
    return [item.strip() for item in active_str.split("+") if item.strip()]


def parse_active_strength_map(active_str: str, strength_str: str) -> Dict[str, str]:
    """Maps each normalized active ingredient to its normalized strength component.

    Supports combination products regardless of ingredient ordering.
    """
    actives = [normalize_text(a) for a in parse_active_ingredients(active_str)]
    strengths = [normalize_single_strength(s) for s in strength_str.split("+") if s.strip()]

    if len(actives) == len(strengths):
        return dict(zip(actives, strengths))

    # Fallback if counts mismatch: map all actives to normalized overall strength string
    norm_full = normalize_strength(strength_str)
    return {a: norm_full for a in actives}


def parse_inactive_ingredients(inactive_str: Any) -> Optional[List[str]]:
    """Parses inactive ingredients string.

    Returns:
        None: If blank, empty, whitespace, or missing (UNKNOWN data).
        []: If explicitly 'NONE' (confirmed zero inactive ingredients).
        List[str]: List of individual inactive ingredients.
    """
    if inactive_str is None:
        return None
    s = str(inactive_str).strip()
    if not s:
        return None
    if s.upper() == "NONE":
        return []

    items = [item.strip() for item in s.split(";") if item.strip()]
    return items if items else None


# ==============================================================================
# Data Loaders
# ==============================================================================

def load_allergy_classes(csv_path: Optional[str] = None) -> Dict[str, str]:
    """Loads ingredient -> class mappings from allergy_classes.csv.

    Returns a dictionary mapping lowercase ingredient names to original class names.
    """
    path = get_data_path("allergy_classes.csv", csv_path)
    if not path.is_file():
        return {}

    mapping: Dict[str, str] = {}
    with open(path, mode="r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ing = normalize_text(row.get("ingredient") or row.get("active_ingredient") or "")
            cls = (row.get("class") or row.get("drug_class") or "").strip()
            if ing and cls:
                mapping[ing] = cls
    return mapping


def load_medicines(csv_path: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """Loads medicine database from medicines.csv.

    Returns a dictionary mapping lowercase medicine ID to record dictionary.
    """
    path = get_data_path("medicines.csv", csv_path)
    if not path.is_file():
        return {}

    medicines: Dict[str, Dict[str, Any]] = {}
    with open(path, mode="r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            med_id = (row.get("id") or "").strip()
            if not med_id:
                continue

            brand = (row.get("brand") or "").strip()
            active = (row.get("active_ingredients") or row.get("ingredient") or "").strip()
            strength = (row.get("strength") or "").strip()
            form = (row.get("form") or "").strip()
            inactive_raw = row.get("inactive_ingredients") if "inactive_ingredients" in row else row.get("inactive")
            mfr = (row.get("manufacturer") or row.get("maker") or "").strip()
            pack_size_raw = (row.get("pack_size") or "").strip()
            price_raw = (row.get("price_per_pack") or row.get("price") or "").strip()

            # Parse numeric fields safely
            try:
                clean_pack = re.sub(r"[^\d]", "", pack_size_raw)
                pack_size = int(clean_pack) if clean_pack else 1
            except ValueError:
                pack_size = pack_size_raw

            try:
                # Clean currency symbols like 'Rs.' if present
                clean_price = re.sub(r"[^\d.]", "", price_raw)
                price = float(clean_price) if clean_price else 0.0
            except ValueError:
                price = price_raw

            medicines[med_id.lower()] = {
                "id": med_id,
                "brand": brand,
                "active_ingredients": active,
                "strength": strength,
                "form": form,
                "inactive_ingredients": inactive_raw if inactive_raw is not None else "",
                "manufacturer": mfr,
                "pack_size": pack_size,
                "price_per_pack": price,
            }

    return medicines


# ==============================================================================
# Matching Engine & Candidate Selection
# ==============================================================================

def is_alternative_candidate(prescribed: Dict[str, Any], candidate: Dict[str, Any]) -> bool:
    """Checks whether candidate satisfies the strict matching rule.

    Matching Rule:
    1. Must NOT have the same ID.
    2. Must have exactly the same active ingredient(s).
    3. Must have exactly the same normalized strength (per ingredient).
    4. Must have exactly the same form.
    5. Brand name is NEVER used to match.
    """
    if candidate["id"].strip().lower() == prescribed["id"].strip().lower():
        return False

    # Check Form
    if normalize_form(candidate.get("form", "")) != normalize_form(prescribed.get("form", "")):
        return False

    # Check Active Ingredients (set comparison for combinations)
    presc_actives_set = set(normalize_text(a) for a in parse_active_ingredients(prescribed.get("active_ingredients", "")))
    cand_actives_set = set(normalize_text(a) for a in parse_active_ingredients(candidate.get("active_ingredients", "")))

    if presc_actives_set != cand_actives_set or not presc_actives_set:
        return False

    # Check Strength (ingredient-level mapping)
    presc_map = parse_active_strength_map(prescribed.get("active_ingredients", ""), prescribed.get("strength", ""))
    cand_map = parse_active_strength_map(candidate.get("active_ingredients", ""), candidate.get("strength", ""))

    if len(presc_map) != len(cand_map):
        return False

    for ing, presc_s in presc_map.items():
        if cand_map.get(ing) != presc_s:
            return False

    return True


# ==============================================================================
# Allergy Checker Engine
# ==============================================================================

def check_allergy_triggers_detailed(
    medicine: Dict[str, Any],
    allergies: List[str],
    allergy_classes: Dict[str, str],
) -> List[Dict[str, str]]:
    """Evaluates the three allergy trigger types strictly with case-insensitive matching:

    (1) Direct: An active ingredient of the product is on the person's allergy list.
    (2) Class: An active ingredient belongs to a drug class that is on the allergy list
               (the mapping is given in allergy_classes.csv).
    (3) Inactive: An inactive ingredient (dye, filler, coating) is on the allergy list.

    Returns a list of trigger dicts: [{'type': 'Direct'|'Class'|'Inactive', 'reason': '...', 'item': '...'}]
    """
    clean_allergies: Set[str] = {normalize_text(a) for a in allergies if a and normalize_text(a)}
    if not clean_allergies:
        return []

    detailed_triggers: List[Dict[str, str]] = []

    # (1) Direct Trigger & (2) Class Trigger
    active_ingredients = parse_active_ingredients(medicine.get("active_ingredients", ""))
    for act in active_ingredients:
        act_clean = normalize_text(act)

        # (1) Direct Trigger: Active ingredient is on the person's allergy list
        if act_clean in clean_allergies:
            detailed_triggers.append({
                "type": "Direct",
                "reason": f"active ingredient {act} is on your allergy list",
                "item": act,
            })

        # (2) Class Trigger: Active ingredient belongs to a drug class on the allergy list
        drug_class = allergy_classes.get(act_clean)
        if drug_class and normalize_text(drug_class) in clean_allergies:
            detailed_triggers.append({
                "type": "Class",
                "reason": f"active ingredient {act} belongs to drug class {drug_class} which is on your allergy list",
                "item": drug_class,
            })

    # (3) Inactive Trigger: An inactive ingredient (dye, filler, coating) is on the allergy list
    parsed_inactives = parse_inactive_ingredients(medicine.get("inactive_ingredients"))
    if parsed_inactives:  # Not None and not empty
        for inact in parsed_inactives:
            if normalize_text(inact) in clean_allergies:
                detailed_triggers.append({
                    "type": "Inactive",
                    "reason": f"inactive ingredient {inact} is on your allergy list",
                    "item": inact,
                })

    return detailed_triggers


def check_allergy_triggers(
    medicine: Dict[str, Any],
    allergies: List[str],
    allergy_classes: Dict[str, str],
) -> List[str]:
    """Evaluates the three allergy trigger types and returns list of reason strings."""
    detailed = check_allergy_triggers_detailed(medicine, allergies, allergy_classes)
    return [d["reason"] for d in detailed]


# ==============================================================================
# Difference Table Generator
# ==============================================================================

def compute_differences(prescribed: Dict[str, Any], alternative: Dict[str, Any]) -> Dict[str, Any]:
    """Computes side-by-side differences between prescribed medicine and alternative.

    Covers: inactive ingredients, manufacturer, pack size, price per pack.
    """
    presc_mfr = prescribed.get("manufacturer") or "Unknown"
    alt_mfr = alternative.get("manufacturer") or "Unknown"

    presc_pack = prescribed.get("pack_size") or "Unknown"
    alt_pack = alternative.get("pack_size") or "Unknown"

    presc_inact = (prescribed.get("inactive_ingredients") or "").strip() or "Unknown"
    alt_inact = (alternative.get("inactive_ingredients") or "").strip() or "Unknown"

    presc_price = prescribed.get("price_per_pack")
    alt_price = alternative.get("price_per_pack")

    if isinstance(presc_price, (int, float)) and isinstance(alt_price, (int, float)):
        diff = alt_price - presc_price
        sign = "+" if diff > 0 else ""
        price_diff_str = f"Rs. {alt_price:.2f} (prescribed: Rs. {presc_price:.2f}, diff: Rs. {sign}{diff:.2f})"
    else:
        price_diff_str = f"{alt_price} (prescribed: {presc_price})"

    mfr_diff = f"{alt_mfr} (prescribed: {presc_mfr})" if alt_mfr != presc_mfr else f"{alt_mfr} (same)"
    pack_diff = f"{alt_pack} (prescribed: {presc_pack})" if alt_pack != presc_pack else f"{alt_pack} (same)"
    inact_diff = f"{alt_inact} (prescribed: {presc_inact})"

    # Price per unit calculation
    try:
        presc_u = float(presc_price) / float(presc_pack)
        alt_u = float(alt_price) / float(alt_pack)
        u_diff = alt_u - presc_u
        sign_u = "+" if u_diff > 0 else ""
        unit_diff_str = f"Rs. {alt_u:.2f}/unit (prescribed: Rs. {presc_u:.2f}/unit, diff: Rs. {sign_u}{u_diff:.2f}/unit)"
    except (ValueError, TypeError, ZeroDivisionError):
        unit_diff_str = "N/A"

    return {
        "manufacturer": mfr_diff,
        "pack_size": pack_diff,
        "price": price_diff_str,
        "price_per_pack": price_diff_str,
        "price_per_unit": unit_diff_str,
        "inactive": inact_diff,
        "inactive_ingredients": inact_diff,
    }


# ==============================================================================
# Typo-Tolerant Search (Input Assist Only)
# ==============================================================================

def search_medicines(
    query: str,
    limit: int = 10,
    medicines_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Performs typo-tolerant search on medicine brand names and IDs.

    Used SOLELY to assist user input selection for the initial prescribed medicine.
    Returns ONLY matching options without showing unrelated catalog entries.
    """
    med_db = load_medicines(medicines_path)
    q = normalize_text(query)
    if not q:
        return []

    # 1. Exact ID match (case-insensitive)
    exact_id = [med for med in med_db.values() if normalize_text(med["id"]) == q]
    if exact_id:
        return exact_id

    results: List[Dict[str, Any]] = []
    seen_ids: Set[str] = set()

    # 2. Exact or substring brand / ID match
    for med in med_db.values():
        brand_clean = normalize_text(med["brand"])
        med_id_clean = normalize_text(med["id"])
        if q == brand_clean or q in brand_clean or med_id_clean.startswith(q):
            results.append(med)
            seen_ids.add(med["id"])

    if results:
        return results[:limit]

    # 3. Typo-tolerant brand match using difflib
    unique_brands = list({med["brand"] for med in med_db.values()})
    close_brands = difflib.get_close_matches(query, unique_brands, n=limit, cutoff=0.45)
    for cb in close_brands:
        for med in med_db.values():
            if med["brand"] == cb and med["id"] not in seen_ids:
                results.append(med)
                seen_ids.add(med["id"])

    # 4. Typo-tolerant ID match using difflib
    all_ids = [med["id"] for med in med_db.values()]
    close_ids = difflib.get_close_matches(query.upper(), all_ids, n=limit, cutoff=0.6)
    for cid in close_ids:
        for med in med_db.values():
            if med["id"] == cid and med["id"] not in seen_ids:
                results.append(med)
                seen_ids.add(med["id"])

    return results[:limit]


# ==============================================================================
# Required Competition Function: suggest()
# ==============================================================================

def suggest(
    medicine_id: str,
    allergies: List[str],
    do_not_substitute: bool = False,
    medicines_path: Optional[str] = None,
    allergy_classes_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Suggests verified medicine alternatives with allergy and safety checks.

    Adheres strictly to the specification schema:
    {
      "prescribed": {"id": ..., "flags": [...]},
      "alternatives": [...],
      "excluded": [...],
      "message": ...
    }

    Args:
        medicine_id: Unique product ID of the prescribed medication (e.g. 'M001').
        allergies: List of allergy strings (active ingredients, drug classes, or inactives).
        do_not_substitute: When True, prevents all substitution.
        medicines_path: Optional path to custom medicines.csv.
        allergy_classes_path: Optional path to custom allergy_classes.csv.

    Returns:
        Specification-compliant JSON-serializable dictionary.
    """
    medicines = load_medicines(medicines_path)
    allergy_classes = load_allergy_classes(allergy_classes_path)

    clean_med_id = normalize_text(medicine_id)

    # Clean input allergies list
    active_allergies = [a.strip() for a in allergies if a and a.strip()]

    # Edge Case: Unknown medicine ID
    if clean_med_id not in medicines:
        return {
            "prescribed": {
                "id": medicine_id,
                "flags": [f"Medicine ID '{medicine_id}' not found in database"],
            },
            "alternatives": [],
            "excluded": [],
            "message": f"Medicine ID '{medicine_id}' not found in the database. Please verify the medicine ID.",
        }

    prescribed = medicines[clean_med_id]

    # Rule 4: Prescribed medicine allergy evaluation
    prescribed_detailed = check_allergy_triggers_detailed(prescribed, active_allergies, allergy_classes)
    prescribed_flags: List[str] = []
    if prescribed_detailed:
        for trig in prescribed_detailed:
            prescribed_flags.append(
                f"Allergy alert ({trig['type']} trigger): {trig['reason']}. Consult your doctor before taking this prescribed medication."
            )

    # Base prescribed output structure
    prescribed_out: Dict[str, Any] = {
        "id": prescribed["id"],
        "brand": prescribed["brand"],
        "active_ingredients": prescribed["active_ingredients"],
        "strength": prescribed["strength"],
        "form": prescribed["form"],
        "inactive_ingredients": prescribed["inactive_ingredients"],
        "manufacturer": prescribed["manufacturer"],
        "pack_size": prescribed["pack_size"],
        "price_per_pack": prescribed["price_per_pack"],
        "flags": prescribed_flags,
        "triggers": prescribed_detailed,
    }

    # Rule 3: Do Not Substitute safety rule
    if do_not_substitute:
        return {
            "prescribed": prescribed_out,
            "alternatives": [],
            "excluded": [],
            "message": "Prescription is marked 'Do Not Substitute'. No alternatives permitted. Consult your doctor or pharmacist.",
        }

    # Step 1: Candidate Selection (The Matching Rule)
    # Strictly matching active ingredients, strength, and form. Never match by brand name.
    candidates: List[Dict[str, Any]] = []
    for cand_id, cand in medicines.items():
        if is_alternative_candidate(prescribed, cand):
            candidates.append(cand)

    # Step 2: Safety & Allergy Evaluation
    alternatives: List[Dict[str, Any]] = []
    excluded: List[Dict[str, str]] = []

    has_allergies = len(active_allergies) > 0

    for cand in candidates:
        cand_id = cand["id"]
        parsed_inactives = parse_inactive_ingredients(cand.get("inactive_ingredients"))

        # Step 2A: Check allergy triggers first (direct active ingredient, drug class, inactive)
        # If an active ingredient or class is allergic, it takes precedence over missing inactive data.
        detailed_triggers = check_allergy_triggers_detailed(cand, active_allergies, allergy_classes)
        if detailed_triggers:
            reason_text = "; ".join(d["reason"] for d in detailed_triggers)
            types_list = list(dict.fromkeys(d["type"] for d in detailed_triggers))
            excluded.append({
                "id": cand_id,
                "reason": reason_text,
                "trigger_type": ", ".join(types_list),
                "triggers": detailed_triggers,
            })
            continue

        # Step 2B: Missing Inactive Ingredients check (only if no allergy triggers fired)
        # If allergy list is non-empty and inactive data is unknown (None), exclude.
        # If explicitly NONE ([]), do not exclude.
        if has_allergies and parsed_inactives is None:
            excluded.append({
                "id": cand_id,
                "reason": "inactive ingredient data missing; cannot check allergies",
                "trigger_type": "Missing Data",
                "triggers": [{
                    "type": "Missing Data",
                    "reason": "inactive ingredient data missing; cannot check allergies",
                    "item": "inactive_ingredients",
                }],
            })
            continue

        # Rule 5: Never say a product is "safe". State strictly verified fact.
        diff_table = compute_differences(prescribed, cand)
        alternatives.append({
            "id": cand_id,
            "brand": cand["brand"],
            "active_ingredients": cand["active_ingredients"],
            "strength": cand["strength"],
            "form": cand["form"],
            "inactive_ingredients": cand["inactive_ingredients"],
            "manufacturer": cand["manufacturer"],
            "pack_size": cand["pack_size"],
            "price_per_pack": cand["price_per_pack"],
            "differences": diff_table,
            "safety_note": "No listed trigger found in the data provided.",
        })

    # Construct final summary message
    if not alternatives:
        message = "No alternatives could be confirmed from the data provided. Ask your pharmacist."
    else:
        message = (
            f"Found {len(alternatives)} alternative(s) matching active ingredient(s), strength, and form. "
            f"No listed trigger found in the data provided. Consult your doctor or pharmacist before making any changes."
        )

    return {
        "prescribed": prescribed_out,
        "alternatives": alternatives,
        "excluded": excluded,
        "message": message,
    }


# ==============================================================================
# CLI Entry Point
# ==============================================================================

def main() -> None:
    """Command-line interface for MedMate."""
    import argparse

    parser = argparse.ArgumentParser(description="MedMate: Medicine Alternative Suggester with Allergy Check")
    parser.add_argument("--id", "-i", type=str, default="", help="Prescribed Medicine ID (e.g. M001)")
    parser.add_argument("--name", "-n", type=str, default="", help="Prescribed Medicine Name/Brand to search with typo tolerance")
    parser.add_argument("--allergies", "-a", nargs="*", default=[], help="Allergies list (e.g. 'Dye R' 'Penicillin')")
    parser.add_argument("--dns", action="store_true", help="Do not substitute flag")
    parser.add_argument("--pretty", action="store_true", help="Pretty print JSON output")

    args = parser.parse_args()

    med_id = args.id.strip()

    # If medicine name provided instead of ID, or ID not provided, use typo-tolerant search
    if not med_id and args.name:
        matches = search_medicines(args.name)
        if not matches:
            print(f"Error: No medicines found matching '{args.name}'.", file=sys.stderr)
            sys.exit(1)
        med_id = matches[0]["id"]
    elif not med_id:
        # Prompt interactively if run without arguments
        try:
            query = input("Enter prescribed medicine name or ID: ").strip()
            if not query:
                print("Error: Medicine name or ID is required.", file=sys.stderr)
                sys.exit(1)
            matches = search_medicines(query)
            if not matches:
                print(f"No medicines found matching '{query}'.", file=sys.stderr)
                sys.exit(1)
            if len(matches) == 1:
                med_id = matches[0]["id"]
                print(f"Selected: {matches[0]['id']} - {matches[0]['brand']} ({matches[0]['strength']}, {matches[0]['form']})")
            else:
                print(f"\nMatching options for '{query}':")
                for idx, m in enumerate(matches, 1):
                    print(f"  [{idx}] {m['id']} - {m['brand']} ({m['strength']}, {m['form']}, {m['manufacturer']})")
                sel = input(f"Choose option [1-{len(matches)}] (default 1): ").strip()
                sel_idx = int(sel) - 1 if sel.isdigit() and 1 <= int(sel) <= len(matches) else 0
                med_id = matches[sel_idx]["id"]
        except (KeyboardInterrupt, EOFError):
            sys.exit(0)

    # Support comma-separated allergies inside arguments
    flat_allergies: List[str] = []
    for item in args.allergies:
        flat_allergies.extend([x.strip() for x in item.split(",") if x.strip()])

    res = suggest(med_id, flat_allergies, do_not_substitute=args.dns)
    indent = 2 if args.pretty else None
    print(json.dumps(res, indent=indent))


if __name__ == "__main__":
    main()
