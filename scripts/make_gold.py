"""Hand-curated gold set for the flow pages -> samples/flow/gold.csv.

AMR ships free-text transcriptions, not field/value pairs, so projecting them
onto amr_flow_v1 is a judgement call per page. Those judgements live here, in
one reviewable place, rather than being buried in a regex.

Curation rules applied uniformly:
  * A value is gold only if it is actually written on the page. Nothing is
    inferred from context -- sex is not guessed from a name, and an age is not
    guessed from "Ad" or "5 month old" (both are null).
  * document_date is the date identifying the document. Observation dates
    inside a vitals table do not count, so several charts have a null date.
  * Dates are normalised to DD/MM/YYYY; the schema keeps the written form in
    raw_transcription instead.
  * Free-text fields are the transcription's wording, whitespace-collapsed.

Every value is JSON-encoded so null is unambiguous and table fields round-trip.

    uv run python scripts/make_gold.py
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

OUT = Path("samples/flow/gold.csv")

N = None


def vit(d, t, temp, pulse, resp, bp=N):
    return {"obs_date": d, "obs_time": t, "temp_c": temp,
            "pulse_bpm": pulse, "resp_rate_cpm": resp, "blood_pressure": bp}


def med(name, dose=N, freq=N, dur=N):
    return {"drug_name": name, "dose": dose, "frequency": freq, "duration": dur}


def tests(*names):
    return [{"test_name": n} for n in names]


GOLD: dict[str, dict] = {

    # ---------------- vitals charts ----------------
    "AMR_001": {
        "document_type": "vitals_chart",
        "patient_name": "E.J", "patient_age_years": 41, "patient_sex": "female",
        "hospital_number": "2023/BF/057",
        "document_date": N,          # chart carries observation dates only
        "ward": "Female medical ward",
        "vitals_diagnosis": "Acute Kidney Injury (AKI)",
        "vitals": [
            vit("29/12/2023", "4:00pm", 39.2, 112, 26),
            vit("29/12/2023", "8:00pm", 38.7, 109, 24),
            vit("30/12/2023", "12:00am", 38.2, 108, 23),
            vit("30/12/2023", "8:00am", 37.9, 100, 20),
            vit("30/12/2023", "12:00pm", 37.5, 97, 20),
        ],
    },
    "AMR_005": {
        "document_type": "vitals_chart",
        "patient_name": N, "patient_age_years": N, "patient_sex": N,
        "hospital_number": "7431742", "document_date": N,
        "ward": N, "vitals_diagnosis": N,
        "vitals": [vit(N, N, 38.2, 68, 38, "119/79")],
    },
    "AMR_008": {
        "document_type": "vitals_chart",
        "patient_name": N, "patient_age_years": N, "patient_sex": N,
        "hospital_number": "2374101", "document_date": N,
        "ward": N, "vitals_diagnosis": N,
        "vitals": [vit(N, N, 37.1, 78, 18, "123/81")],
    },
    "AMR_015": {
        "document_type": "vitals_chart",
        "patient_name": "Miss J.I", "patient_age_years": 12,
        "patient_sex": "female", "hospital_number": N, "document_date": N,
        "ward": "Paediatric ward", "vitals_diagnosis": "Acute kidney injury",
        "vitals": [
            vit("10/03/2026", "12:00", 38.2, 85, 20, "150/100"),
            vit("10/03/2026", "16:00", 38.4, 88, 20, "148/96"),
            vit("10/03/2026", "20:00", 38.1, 90, 21, "134/95"),
            vit("11/03/2026", "08:00", 38.1, 88, 19, "140/94"),
            vit("11/03/2026", "12:00", 37.9, 90, 20, "136/90"),
            vit("11/03/2026", "16:00", 37.9, 86, 20, "130/90"),
            vit("11/03/2026", "20:00", 37.6, 84, 18, "132/86"),
            vit("12/03/2026", "08:00", 37.7, 86, 20, "130/88"),
            vit("12/03/2026", "12:00", 37.4, 82, 18, "126/84"),
            vit("12/03/2026", "16:00", 37.1, 84, 16, "128/80"),
            vit("12/03/2026", "20:00", 36.9, 80, 18, "120/78"),
        ],
    },
    "AMR_017": {
        "document_type": "vitals_chart",
        "patient_name": "F.O", "patient_age_years": 19, "patient_sex": "male",
        "hospital_number": "2026/SC/015", "document_date": N,
        "ward": "Male medical ward",
        "vitals_diagnosis": "Vaso-occlusive crisis [SCD]",
        "vitals": [
            vit("12/03/2026", "08:00", 38.5, 102, 24),
            vit("12/03/2026", "12:00", 38.2, 100, 23),
            vit("12/03/2026", "16:00", 37.8, 96, 22),
            vit("12/03/2026", "20:00", 37.5, 90, 20),
            vit("13/03/2026", "08:00", 37.2, 84, 18),
        ],
    },
    "AMR_021": {
        "document_type": "vitals_chart",
        "patient_name": "Amina Bello", "patient_age_years": N, "patient_sex": N,
        "hospital_number": "MED/002/26", "document_date": "23/03/2026",
        "ward": N, "vitals_diagnosis": N,
        "vitals": [
            vit(N, "8:00 AM", 37.2, 78, 18, "110/70"),
            vit(N, "12:00 PM", 37.5, 82, 20, "115/75"),
            vit(N, "4:00 PM", 37.3, 80, 18, "112/72"),
            vit(N, "8:00 PM", 37.0, 76, 17, "110/70"),
        ],
    },

    # ---------------- prescriptions ----------------
    "AMR_003": {
        "document_type": "prescription",
        "patient_name": "J.D",
        "patient_age_years": N,       # written "AD"
        "patient_sex": "female", "hospital_number": "70079",
        "document_date": "23/02/2025",
        "prescriber_name": "Dr Joan Riz", "prescription_diagnosis": N,
        "medications": [
            med("Cefuroxime", "500mg", "bd", "x 5/7"),
            med("Strepsils throat lozenges", N, "Tqds", "x 5/7"),
            med("Vitamin C (Calgorit)", "1000mg", N, "x 20/7"),
        ],
    },
    "AMR_006": {
        "document_type": "prescription",
        "patient_name": "Usamatu Amaka", "patient_age_years": N,
        "patient_sex": "female", "hospital_number": "7401911",
        "document_date": "10/10/2025",
        "prescriber_name": "Dr. H Sani", "prescription_diagnosis": N,
        "medications": [
            med("Tab omeprazole", "20mg", "PO tds"),
            med("Cap Amoxicillin", "500mg", "bds", "14/7"),
            med("Tab Clarithromycin", "250mg", "bds"),
        ],
    },
    "AMR_007": {
        "document_type": "prescription",
        "patient_name": "Isabel Shehu", "patient_age_years": N,
        "patient_sex": "female", "hospital_number": "4040914",
        "document_date": "24/07/2024",
        "prescriber_name": N,          # signature line only
        "prescription_diagnosis": N,
        "medications": [med("Mannitol IV", "10%")],
    },
    "AMR_014": {
        "document_type": "prescription",
        "patient_name": "Miss J.I", "patient_age_years": 12,
        "patient_sex": "female", "hospital_number": "2026/PD/1266",
        "document_date": "10/03/2026",
        "prescriber_name": "Dr Naya Iyare",
        "prescription_diagnosis": (
            "Oliguria 2/52, vomiting 2/52, generalized edema 1/52, fever 1/52, "
            "abdominal pain 2/7. Suspected AKI with nephrotic syndrome overlap?"
        ),
        "medications": [
            med("Furosemide", "2 mg/kg/dose IV"),
            med("Oral nifedipine", "0.3 mg/kg/day", "in divided doses", "2 days"),
            med("Tab Paracetamol", "10 mg/kg/dose", "6 hourly", "3 days"),
        ],
    },
    "AMR_019": {
        "document_type": "prescription",
        "patient_name": "F. O", "patient_age_years": 19, "patient_sex": "male",
        "hospital_number": "2026/SC/015", "document_date": "12/03/2026",
        "prescriber_name": N,
        "prescription_diagnosis":
            "Vaso-occlusive crisis secondary to Sickle cell disease",
        "medications": [
            med("Tab Paracetamol", "500mg", "1 tablet every 8 hours", "x 3/7"),
            med("Tab Ibuprofen", "400mg", "1 tablet every 12 hours", "× 3/7"),
            med("Tab Folic acid", "5mg", "1 tablet daily", "30 days"),
            med("IV Normal Saline 0.9%", "1 litre", "over 8 hours"),
            med("IM Diclofenac", "75mg"),
        ],
    },
    "AMR_022": {
        "document_type": "prescription",
        "patient_name": "Blessing Ehiakhamen", "patient_age_years": 22,
        "patient_sex": "female", "hospital_number": "MED/003/26",
        "document_date": "23/03/2026",
        "prescriber_name": "Dr. A. Johnson", "prescription_diagnosis": "Malaria",
        "medications": [
            med("Artemether/Lumefantrine", "4 tabs",
                "stat, 4 tabs after 8 hrs, then 4 tabs BD", "2 days"),
            med("Paracetamol", "500 mg", "1 tab every 8 hrs", "3 days"),
            med("ORS", N, "as needed"),
        ],
    },

    # ---------------- lab requests ----------------
    "AMR_004": {
        "document_type": "lab_request",
        "patient_name": "E.R", "patient_age_years": N, "patient_sex": "male",
        "hospital_number": "20067", "document_date": "17/07/2024",
        "requesting_doctor": "Dr Oloro Rafi",
        "specimen_type": N,           # sample-type row present, none ticked
        "lab_priority": N,
        "lab_clinical_details": N,    # Comments/Notes left blank
        "tests_requested": [],        # printed options only, no tick marks
    },
    "AMR_010": {
        "document_type": "lab_request",
        "patient_name": "Emeka Sani", "patient_age_years": N,
        "patient_sex": "male", "hospital_number": "5830682",
        "document_date": "12/05/2026",
        "requesting_doctor": N, "specimen_type": "sputum", "lab_priority": N,
        "lab_clinical_details": "?? TB",
        "tests_requested": tests("GeneXpert"),
    },
    "AMR_011": {
        "document_type": "lab_request",
        "patient_name": "Waleed Adenuga", "patient_age_years": N,
        "patient_sex": "male", "hospital_number": "5836082",
        "document_date": "12/03/2026",
        "requesting_doctor": N, "specimen_type": "urine", "lab_priority": N,
        "lab_clinical_details": "?? UTI",
        "tests_requested": tests("M/C/S"),
    },
    "AMR_012": {
        "document_type": "lab_request",
        "patient_name": "Miss J.I", "patient_age_years": 12,
        "patient_sex": "female", "hospital_number": "2026/PD/1266",
        "document_date": "10/03/2026",
        "requesting_doctor": "Dr Naya Iyare", "specimen_type": N,
        "lab_priority": "urgent",
        "lab_clinical_details": (
            "Oliguria 2/52, vomiting 2/52, generalized edema 1/52, fever 1/52, "
            "abdominal pain 2/7. Suspected AKI with nephrotic overlap -?"
        ),
        "tests_requested": tests(
            "Complete Blood Count",
            "Renal Function Test (urea, creatinine, eGFR)",
            "Electrolytes", "Urinalysis", "Serum Albumin",
            "Urine Protein / Creatinine Ratio",
        ),
    },
    "AMR_016": {
        "document_type": "lab_request",
        "patient_name": "F. O", "patient_age_years": 19, "patient_sex": "male",
        "hospital_number": "2026/SC/015", "document_date": "12/03/2026",
        "requesting_doctor": N, "specimen_type": N, "lab_priority": N,
        "lab_clinical_details": (
            "Known HbSS patient presenting with: Generalized body pain, Fever, "
            "Weakness. ? Vaso-occlusive crisis ? Underlying infection"
        ),
        "tests_requested": tests(
            "Full Blood Count", "Reticulocyte count", "Peripheral blood film",
            "Malaria parasite test",
            "Serum electrolytes, Urea and Creatinine",
        ),
    },
    "AMR_023": {
        "document_type": "lab_request",
        "patient_name": "Samuel Ogunleye", "patient_age_years": 35,
        "patient_sex": "male", "hospital_number": "MED/004/26",
        "document_date": "23/03/2026",
        "requesting_doctor": "Dr. A. Johnson", "specimen_type": "blood",
        "lab_priority": "routine",
        "lab_clinical_details": "Fever for 5 days, weakness, headache",
        "tests_requested": tests("FBC", "Malaria Parasite Test", "Widal Test",
                                 "Blood Culture"),
    },

    # ---------------- visit notes ----------------
    "AMR_009": {
        "document_type": "visit_note",
        "patient_name": N,
        "patient_age_years": N,       # "5 month old" -- months, so null
        "patient_sex": "female", "hospital_number": N,
        "document_date": "18/12/2024",
        "chief_complaint": (
            "Head swelling from birth due to management of opening on the back. "
            "Child is not active and always in pain evidenced by constant cries "
            "even after feeding"
        ),
        "assessment": N, "plan": N,
    },
    "AMR_020": {
        "document_type": "visit_note",
        "patient_name": "Chinedu Okafor", "patient_age_years": 28,
        "patient_sex": "male", "hospital_number": "MED/001/26",
        "document_date": "23/03/2026",
        "chief_complaint": "Burning chest pain for 3 days",
        "assessment": "Likely GERD",
        "plan": "Omeprazole 20 mg daily. Lifestyle modification. Review in 1 week",
    },

    # ---------------- synthetic smoke tests ----------------
    "SYN_001": {
        "document_type": "prescription",
        "patient_name": "Ngozi Abara", "patient_age_years": 34,
        "patient_sex": "female", "hospital_number": "SYN/001/26",
        "document_date": "14/04/2026",
        "prescriber_name": "Dr. Ifeoma Nwosu",
        "prescription_diagnosis": "Community acquired pneumonia",
        "medications": [
            med("Tab Amoxicillin", "500mg", "tds", "x 7/7"),
            med("Tab Paracetamol", "500mg", "qds", "x 5/7"),
            med("Syr Ascorbic acid", "100mg", "daily", "x 10/7"),
        ],
    },
    "SYN_002": {
        "document_type": "vitals_chart",
        "patient_name": "Tunde Balogun", "patient_age_years": 57,
        "patient_sex": "male", "hospital_number": "SYN/002/26",
        "document_date": N,
        "ward": "Male medical ward",
        "vitals_diagnosis": "Congestive cardiac failure",
        "vitals": [
            vit("14/04/2026", "08:00", 38.6, 104, 24),
            vit("14/04/2026", "12:00", N, 98, 22),    # temp smudged illegible
            vit("14/04/2026", "16:00", 37.8, N, 20),  # pulse left blank
            vit("14/04/2026", "20:00", 37.4, 88, 19),
            vit("15/04/2026", "08:00", 37.1, 84, 18),
        ],
    },
    "SYN_003": {
        "document_type": "lab_request",
        "patient_name": "Chidi Eze",
        "patient_age_years": N,        # written "Ad"
        "patient_sex": "male", "hospital_number": "SYN/003/26",
        "document_date": "15/04/2026",
        "requesting_doctor": "Dr. K. Musa",
        "specimen_type": N,            # four boxes, none ticked
        "lab_priority": N,
        "lab_clinical_details": "Fever 4/7, headache, joint pains. ?? Malaria",
        "tests_requested": tests(
            "Full Blood Count", "Malaria parasite test",
            "Serum electrolytes, urea & creatinine",
        ),
    },
}


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for pair_id in sorted(GOLD):
        for field_name, value in GOLD[pair_id].items():
            rows.append({
                "pair_id": pair_id,
                "page_no": 1,
                "field_name": field_name,
                "gold_json": json.dumps(value, ensure_ascii=False),
            })
    with OUT.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["pair_id", "page_no", "field_name",
                                           "gold_json"])
        w.writeheader()
        w.writerows(rows)

    nulls = sum(1 for r in rows if r["gold_json"] == "null")
    print(f"wrote {OUT}")
    print(f"  {len(GOLD)} pages, {len(rows)} field values")
    print(f"  {nulls} legitimately null ({nulls / len(rows):.0%}) -- these must "
          f"reach the review queue, not be guessed")


if __name__ == "__main__":
    main()
