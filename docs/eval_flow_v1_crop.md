# Eval report -- **flow set**

> Flow set proves plumbing. These numbers are NOT a performance
> claim (PRD 12.1); sign-off metrics come from the held-out set.

| field | n | exact acc | auto-acc acc | flag rate | FN flag rate | halluc |
|---|--:|--:|--:|--:|--:|--:|
| assessment | 2 | 0% | 0% | 0% | 100% | 100% |
| chief_complaint | 2 | 0% | 0% | 0% | 100% | - |
| document_date | 23 | 78% | 83% | 22% | 17% | 17% |
| document_type | 23 | 96% | 100% | 22% | 0% | - |
| hospital_number | 23 | 65% | 62% | 9% | 38% | 0% |
| lab_clinical_details | 7 | 43% | 50% | 14% | 50% | 100% |
| lab_priority | 7 | 71% | 71% | 0% | 29% | 0% |
| medications | 7 | 14% | 14% | 0% | 86% | - |
| patient_age_years | 23 | 96% | 95% | 4% | 5% | 0% |
| patient_name | 23 | 65% | 64% | 4% | 36% | 0% |
| patient_sex | 23 | 91% | 100% | 9% | 0% | 0% |
| plan | 2 | 0% | 0% | 0% | 100% | 100% |
| prescriber_name | 7 | 43% | 43% | 0% | 57% | 0% |
| prescription_diagnosis | 7 | 57% | 57% | 0% | 43% | 67% |
| requesting_doctor | 7 | 57% | 33% | 57% | 67% | 0% |
| specimen_type | 7 | 43% | 50% | 14% | 50% | 75% |
| tests_requested | 7 | 43% | 43% | 0% | 57% | - |
| vitals | 7 | 29% | 67% | 57% | 33% | - |
| vitals_diagnosis | 7 | 86% | 83% | 14% | 17% | 0% |
| ward | 7 | 100% | 100% | 29% | 0% | 0% |
| **overall** | 221 | 70% | 71% | 13% | 29% | 18% |
