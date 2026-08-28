# Eval report -- **flow set**

> Flow set proves plumbing. These numbers are NOT a performance
> claim (PRD 12.1); sign-off metrics come from the held-out set.

| field | n | exact acc | auto-acc acc | flag rate | FN flag rate | halluc |
|---|--:|--:|--:|--:|--:|--:|
| assessment | 2 | 100% | 100% | 50% | 0% | 0% |
| chief_complaint | 2 | 0% | 0% | 50% | 100% | - |
| document_date | 23 | 83% | 100% | 26% | 0% | 0% |
| document_type | 23 | 100% | 100% | 13% | 0% | - |
| hospital_number | 23 | 87% | 100% | 30% | 0% | 0% |
| lab_clinical_details | 7 | 86% | 100% | 43% | 0% | 0% |
| lab_priority | 7 | 86% | 83% | 14% | 17% | 0% |
| medications | 7 | 14% | 100% | 86% | 0% | - |
| patient_age_years | 23 | 96% | 100% | 13% | 0% | 0% |
| patient_name | 23 | 65% | 100% | 39% | 0% | 0% |
| patient_sex | 23 | 100% | 100% | 9% | 0% | 0% |
| plan | 2 | 50% | 100% | 50% | 0% | 0% |
| prescriber_name | 7 | 86% | 100% | 43% | 0% | 0% |
| prescription_diagnosis | 7 | 71% | 100% | 57% | 0% | 33% |
| requesting_doctor | 7 | 86% | 100% | 43% | 0% | 0% |
| specimen_type | 7 | 43% | 60% | 29% | 40% | 75% |
| tests_requested | 7 | 57% | 100% | 57% | 0% | - |
| vitals | 7 | 57% | 100% | 86% | 0% | - |
| vitals_diagnosis | 7 | 71% | 83% | 14% | 17% | 0% |
| ward | 7 | 100% | 100% | 0% | 0% | 0% |
| **overall** | 221 | 81% | 97% | 30% | 3% | 8% |
