# Eval report -- **flow set**

> Flow set proves plumbing. These numbers are NOT a performance
> claim (PRD 12.1); sign-off metrics come from the held-out set.

| field | n | exact acc | auto-acc acc | flag rate | FN flag rate | halluc |
|---|--:|--:|--:|--:|--:|--:|
| assessment | 2 | 0% | 0% | 0% | 100% | 100% |
| chief_complaint | 2 | 50% | 50% | 0% | 50% | - |
| document_date | 23 | 65% | 68% | 17% | 32% | 67% |
| document_type | 23 | 96% | 100% | 17% | 0% | - |
| hospital_number | 23 | 87% | 86% | 9% | 14% | 0% |
| lab_clinical_details | 7 | 43% | 43% | 0% | 57% | 100% |
| lab_priority | 7 | 86% | 86% | 0% | 14% | 0% |
| medications | 7 | 0% | 0% | 14% | 100% | - |
| patient_age_years | 23 | 100% | 100% | 4% | 0% | 0% |
| patient_name | 23 | 70% | 70% | 0% | 30% | 0% |
| patient_sex | 23 | 100% | 100% | 0% | 0% | 0% |
| plan | 2 | 50% | 0% | 50% | 100% | 0% |
| prescriber_name | 7 | 86% | 86% | 0% | 14% | 0% |
| prescription_diagnosis | 7 | 86% | 86% | 0% | 14% | 0% |
| requesting_doctor | 7 | 57% | 25% | 43% | 75% | 0% |
| specimen_type | 7 | 57% | 57% | 0% | 43% | 75% |
| tests_requested | 7 | 29% | 29% | 0% | 71% | - |
| vitals | 7 | 14% | 25% | 43% | 75% | - |
| vitals_diagnosis | 7 | 71% | 71% | 0% | 29% | 33% |
| ward | 7 | 100% | 100% | 43% | 0% | 0% |
| **overall** | 221 | 75% | 75% | 10% | 25% | 20% |
