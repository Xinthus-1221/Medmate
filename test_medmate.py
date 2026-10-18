"""Pytest suite for MedMate.

Includes:
1. Automated execution of all public benchmark test cases from test_cases_public.csv.
2. Five bespoke safety edge cases verifying strict matching rules, allergy triggers,
   missing vs. NONE inactive ingredients, and combination drugs.
"""

import csv
import pytest
from pathlib import Path
from medmate import (
    suggest,
    normalize_strength,
    normalize_form,
    normalize_text,
    search_medicines,
    is_alternative_candidate,
)

BASE_DIR = Path(__file__).resolve().parent
PUBLIC_TESTS_CSV = BASE_DIR / "test_cases_public.csv"


# ==============================================================================
# Helper to Load Public Benchmark Tests
# ==============================================================================

def load_public_test_cases():
    """Loads public test cases from test_cases_public.csv."""
    test_cases = []
    if not PUBLIC_TESTS_CSV.is_file():
        return test_cases

    with open(PUBLIC_TESTS_CSV, mode="r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            test_id = row["test_id"].strip()
            med_id = row["medicine_id"].strip()
            allergies_raw = row.get("allergies", "").strip()
            allergies = [a.strip() for a in allergies_raw.split(";") if a.strip()] if allergies_raw else []
            dns = row.get("do_not_substitute", "False").strip().lower() == "true"
            expected_alts_raw = row.get("expected_alternatives", "").strip()
            expected_alts = set(a.strip() for a in expected_alts_raw.split(";") if a.strip()) if expected_alts_raw else set()
            expected_excl_raw = row.get("expected_excluded", "").strip()
            expected_excl = set(e.strip() for e in expected_excl_raw.split(";") if e.strip()) if expected_excl_raw else set()

            test_cases.append((test_id, med_id, allergies, dns, expected_alts, expected_excl, row.get("notes", "")))
    return test_cases


# ==============================================================================
# Part 1: Automated Execution of Public Benchmark Cases
# ==============================================================================

@pytest.mark.parametrize(
    "test_id,med_id,allergies,dns,expected_alts,expected_excl,notes",
    load_public_test_cases(),
)
def test_public_benchmark_cases(test_id, med_id, allergies, dns, expected_alts, expected_excl, notes):
    """Executes each public benchmark test case against suggest()."""
    result = suggest(medicine_id=med_id, allergies=allergies, do_not_substitute=dns)

    assert "prescribed" in result
    assert "alternatives" in result
    assert "excluded" in result
    assert "message" in result

    # Check Do Not Substitute rule
    if dns:
        assert len(result["alternatives"]) == 0
        assert "do not substitute" in result["message"].lower() or "not permitted" in result["message"].lower()
        return

    # Check non-existent medicine
    if med_id == "M999":
        assert len(result["alternatives"]) == 0
        assert "not found" in result["message"].lower()
        return

    # Check alternatives IDs
    actual_alt_ids = {a["id"] for a in result["alternatives"]}
    assert actual_alt_ids == expected_alts, (
        f"[{test_id}] Alternatives mismatch. Expected {expected_alts}, got {actual_alt_ids}. Note: {notes}"
    )

    # Check excluded IDs (if specified)
    actual_excl_ids = {e["id"] for e in result["excluded"]}
    if expected_excl:
        assert expected_excl.issubset(actual_excl_ids) or actual_excl_ids == expected_excl, (
            f"[{test_id}] Excluded mismatch. Expected {expected_excl}, got {actual_excl_ids}. Note: {notes}"
        )


# ==============================================================================
# Part 2: 5 Bespoke Safety Edge Cases
# ==============================================================================

def test_bespoke_1_strength_unit_equivalence():
    """Bespoke Test 1: Unit Equivalence Normalization ('500 mg' vs '0.5 g').

    Verifies:
    1. '500 mg' matches '0.5 g' and '500000 mcg'.
    2. Different strength ('250 mg') is strictly rejected from alternatives and excluded list.
    """
    assert normalize_strength("500 mg") == normalize_strength("0.5 g")
    assert normalize_strength("500mg") == normalize_strength("0.5  G")
    assert normalize_strength("250 mcg") == normalize_strength("0.25 mg")
    assert normalize_strength("1,000 mg") == normalize_strength("1000 mg")
    assert normalize_strength("1,000 mg") == normalize_strength("1 g")
    assert normalize_strength("1,000,000 mcg") == normalize_strength("1,000 mg")

    # M001 is 500 mg tablet. M005 is 0.5 g tablet. M004 is 250 mg tablet.
    result = suggest("M001", allergies=[])
    alt_ids = [a["id"] for a in result["alternatives"]]
    excl_ids = [e["id"] for e in result["excluded"]]

    # M005 must be an alternative (0.5 g == 500 mg)
    assert "M005" in alt_ids
    # M004 must NEVER be suggested and must NOT be in excluded (different strength is not an alternative)
    assert "M004" not in alt_ids
    assert "M004" not in excl_ids


def test_bespoke_2_missing_vs_none_inactive_ingredients():
    """Bespoke Test 2: Blank/Missing Inactive Ingredients vs Confirmed 'NONE'.

    Verifies:
    1. If allergies are specified, blank inactive ingredients -> EXCLUDED with exact reason:
       'inactive ingredient data missing; cannot check allergies' (M003).
    2. If allergies are specified, 'NONE' inactive ingredients -> ACCEPTED (M006).
    3. If allergies are empty, blank inactive ingredients are NOT excluded.
    """
    # With allergy present:
    res_with_allergy = suggest("M001", allergies=["Dye R"])
    excl_dict = {e["id"]: e["reason"] for e in res_with_allergy["excluded"]}
    alt_ids_with_allergy = [a["id"] for a in res_with_allergy["alternatives"]]

    # M003 has blank inactive data -> must be excluded with exact reason
    assert "M003" in excl_dict
    assert excl_dict["M003"] == "inactive ingredient data missing; cannot check allergies"

    # M006 has 'NONE' -> confirmed no inactive ingredients, so safe from missing data exclusion
    assert "M006" in alt_ids_with_allergy

    # With empty allergies:
    res_no_allergy = suggest("M001", allergies=[])
    alt_ids_no_allergy = [a["id"] for a in res_no_allergy["alternatives"]]
    # M003 must now be accepted as alternative when no allergies exist
    assert "M003" in alt_ids_no_allergy


def test_bespoke_3_drug_class_cross_mapping_and_prescribed_alert():
    """Bespoke Test 3: Drug Class Allergy Trigger and Prescribed Alert.

    Verifies:
    1. Amoxicillin belongs to drug class 'Penicillin' in allergy_classes.csv.
    2. If allergy list includes 'Penicillin', prescribed medicine M011 (Amoxicillin)
       receives an alert in prescribed.flags advising patient to check with doctor.
    3. Alternatives with Amoxicillin (M012) are excluded with drug class reason.
    """
    res = suggest("M011", allergies=["Penicillin"])

    # Prescribed medicine must have allergy flag
    assert len(res["prescribed"]["flags"]) > 0
    flag_text = res["prescribed"]["flags"][0]
    assert "penicillin" in flag_text.lower()
    assert "doctor" in flag_text.lower()

    # Both M012 and M013 must be excluded due to class allergy (not missing data)
    excl_dict = {e["id"]: e["reason"] for e in res["excluded"]}
    excl_trigger_types = {e["id"]: e.get("trigger_type", "") for e in res["excluded"]}
    assert "M012" in excl_dict
    assert "penicillin" in excl_dict["M012"].lower()
    assert "drug class" in excl_dict["M012"].lower()
    assert "M013" in excl_dict
    assert "penicillin" in excl_dict["M013"].lower()
    assert "drug class" in excl_dict["M013"].lower()
    assert "Class" in excl_trigger_types["M013"]


def test_bespoke_4_strict_matching_and_case_whitespace_insensitivity():
    """Bespoke Test 4: Strict Case & Whitespace Insensitivity, No Fuzzy Matching for Allergies.

    Verifies:
    1. '  Dye r  ' matches 'Dye R'.
    2. 'DYE Q' matches 'Dye Q'.
    3. Substring/fuzzy 'Dye' does NOT match 'Dye R' (strict matching invariant).
    """
    # 1. Whitespace and case tolerance
    res_trimmed = suggest("M001", allergies=["  dye r  "])
    excl_ids = [e["id"] for e in res_trimmed["excluded"]]
    assert "M002" in excl_ids

    # 2. Case variation on prescribed trigger
    res_case = suggest("M001", allergies=["DYE Q"])
    assert len(res_case["prescribed"]["flags"]) > 0
    assert "dye q" in res_case["prescribed"]["flags"][0].lower()

    # 3. Substring 'Dye' alone should NOT trigger exact allergy on 'Dye R'
    # Strict matching invariant: exact match only
    res_fuzzy = suggest("M001", allergies=["Dye"])
    excl_ids_fuzzy = [e["id"] for e in res_fuzzy["excluded"]]
    # M002 has 'Dye R', which is not 'Dye'
    assert "M002" not in excl_ids_fuzzy

    # 4. Explicit dosage form normalization mapping ('tablets' -> 'tablet', 'gas' stays 'gas')
    assert normalize_form("tablets") == "tablet"
    assert normalize_form("capsules") == "capsule"
    assert normalize_form("gas") == "gas"
    assert normalize_form("syrup") == "syrup"


def test_bespoke_5_combination_drugs_order_invariance():
    """Bespoke Test 5: Combination Drugs Order Invariance and Multi-Ingredient Strengths.

    Verifies:
    1. 'Paracetamol + Caffeine' (500 mg + 65 mg) matches 'Caffeine + Paracetamol' (500 mg + 65 mg).
    2. Differences table properly calculates price and pack differences.
    3. Specific inactive allergy in combination drug correctly excludes product.
    """
    # M008 is Novagesic (Paracetamol + Caffeine, 500 mg + 65 mg, Starch; Povidone)
    # M009 is Panacaf (Caffeine + Paracetamol, 500 mg + 65 mg, Microcrystalline Cellulose; Dye Yellow 6)
    # M010 is ReliefPlus (Paracetamol + Caffeine, 0.5 g + 65 mg, NONE)
    res = suggest("M008", allergies=["Dye Yellow 6"])

    alt_ids = [a["id"] for a in res["alternatives"]]
    excl_dict = {e["id"]: e["reason"] for e in res["excluded"]}

    # M009 contains Dye Yellow 6 -> must be excluded
    assert "M009" in excl_dict
    assert "dye yellow 6" in excl_dict["M009"].lower()

    # M010 has 0.5 g + 65 mg and NONE -> must be accepted
    assert "M010" in alt_ids

    # Check difference table format
    alt_m010 = next(a for a in res["alternatives"] if a["id"] == "M010")
    diffs = alt_m010["differences"]
    assert "price" in diffs or "price_per_pack" in diffs
    assert "manufacturer" in diffs
    assert "inactive" in diffs or "inactive_ingredients" in diffs
    assert alt_m010["safety_note"] == "No listed trigger found in the data provided."


# ==============================================================================
# Part 3: Typo-Tolerant Input Search Helper Verification
# ==============================================================================

def test_typo_tolerant_search():
    """Verifies typo-tolerant search for input assist."""
    # Exact ID search
    res_id = search_medicines("m001")
    assert len(res_id) == 1
    assert res_id[0]["id"] == "M001"

    # Brand typo tolerance
    res_typo = search_medicines("Zolvexn")
    assert len(res_typo) > 0
    assert any("Zolvex" in r["brand"] for r in res_typo)

    # Prefix search
    res_prefix = search_medicines("Cardi")
    assert any(r["id"] == "M016" for r in res_prefix)


def test_bespoke_6_three_allergy_trigger_types():
    """Bespoke Test 6: Verify all three explicit allergy trigger types.

    (1) Direct: An active ingredient of the product is on the allergy list.
    (2) Class: An active ingredient belongs to a drug class on the allergy list.
    (3) Inactive: An inactive ingredient (dye, filler, coating) is on the allergy list.
    """
    # 1. Direct Trigger: Active ingredient 'Amoxicillin' on allergy list
    res_direct = suggest("M011", allergies=["Amoxicillin"])
    assert any("direct trigger" in f.lower() for f in res_direct["prescribed"]["flags"])
    assert any("amoxicillin is on your allergy list" in f.lower() for f in res_direct["prescribed"]["flags"])
    # Alternatives M012, M013 also excluded with Direct trigger
    excl_direct = {e["id"]: e for e in res_direct["excluded"]}
    assert "M012" in excl_direct
    assert "Direct" in excl_direct["M012"]["trigger_type"]

    # 2. Class Trigger: Drug class 'Penicillin' on allergy list (Amoxicillin belongs to Penicillin)
    res_class = suggest("M011", allergies=["Penicillin"])
    assert any("class trigger" in f.lower() for f in res_class["prescribed"]["flags"])
    assert any("penicillin" in f.lower() for f in res_class["prescribed"]["flags"])
    excl_class = {e["id"]: e for e in res_class["excluded"]}
    assert "M012" in excl_class
    assert "Class" in excl_class["M012"]["trigger_type"]

    # 3. Inactive Trigger: Inactive ingredient 'Dye R' on allergy list
    # M001 has Filler M; Dye Q -> prescribed is NOT allergic to Dye R
    res_inact = suggest("M001", allergies=["Dye R"])
    assert len(res_inact["prescribed"]["flags"]) == 0  # Prescribed doesn't contain Dye R
    excl_inact = {e["id"]: e for e in res_inact["excluded"]}
    assert "M002" in excl_inact  # M002 contains Dye R
    assert "Inactive" in excl_inact["M002"]["trigger_type"]
    assert "inactive ingredient dye r is on your allergy list" in excl_inact["M002"]["reason"].lower()
