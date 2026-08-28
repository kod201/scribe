# Eval report -- **flow set**

> Flow set proves plumbing. These numbers are NOT a performance
> claim (PRD 12.1); sign-off metrics come from the held-out set.

| field | n | exact acc | auto-acc acc | flag rate | FN flag rate | halluc | halluc esc. |
|---|--:|--:|--:|--:|--:|--:|--:|
| assessment | 2 | 100% | 100% | 50% | 0% | 0% | 0% |
| chief_complaint | 2 | 0% | 0% | 50% | 100% | - | - |
| document_date | 23 | 61% | 67% | 35% | 33% | 0% | 0% |
| document_type | 23 | 100% | 100% | 43% | 0% | - | - |
| hospital_number | 23 | 65% | 92% | 48% | 8% | 0% | 0% |
| lab_clinical_details | 7 | 86% | 100% | 43% | 0% | 0% | 0% |
| lab_priority | 7 | 86% | 83% | 14% | 17% | 0% | 0% |
| medications | 7 | 14% | 100% | 86% | 0% | - | - |
| patient_age_years | 23 | 100% | 100% | 26% | 0% | 0% | 0% |
| patient_name | 23 | 74% | 100% | 57% | 0% | 0% | 0% |
| patient_sex | 23 | 57% | 36% | 39% | 64% | 0% | 0% |
| plan | 2 | 50% | 100% | 50% | 0% | 0% | 0% |
| prescriber_name | 7 | 100% | 100% | 43% | 0% | 0% | 0% |
| prescription_diagnosis | 7 | 86% | 100% | 29% | 0% | 0% | 0% |
| requesting_doctor | 7 | 86% | 100% | 43% | 0% | 0% | 0% |
| specimen_type | 7 | 86% | 83% | 14% | 17% | 0% | 0% |
| tests_requested | 7 | 57% | 50% | 71% | 50% | - | - |
| vitals | 7 | 14% | - | 100% | - | - | - |
| vitals_diagnosis | 7 | 86% | 83% | 14% | 17% | 0% | 0% |
| ward | 7 | 100% | 100% | 14% | 0% | 0% | 0% |
| **overall** | 221 | 74% | 84% | 42% | 16% | 0% | 0% |
