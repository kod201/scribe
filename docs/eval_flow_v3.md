# Eval report -- **flow set**

> Flow set proves plumbing. These numbers are NOT a performance
> claim (PRD 12.1); sign-off metrics come from the held-out set.

| field | n | exact acc | auto-acc acc | flag rate | FN flag rate | halluc |
|---|--:|--:|--:|--:|--:|--:|
| assessment | 2 | 50% | - | 100% | - | 100% |
| chief_complaint | 2 | 0% | - | 100% | - | - |
| document_date | 23 | 78% | 94% | 26% | 6% | 17% |
| document_type | 23 | 96% | 100% | 26% | 0% | - |
| hospital_number | 23 | 87% | 100% | 30% | 0% | 0% |
| lab_clinical_details | 7 | 29% | 100% | 71% | 0% | 100% |
| lab_priority | 7 | 71% | 71% | 0% | 29% | 0% |
| medications | 7 | 14% | 50% | 71% | 50% | - |
| patient_age_years | 23 | 100% | 100% | 13% | 0% | 0% |
| patient_name | 23 | 70% | 100% | 39% | 0% | 0% |
| patient_sex | 23 | 91% | 100% | 13% | 0% | 0% |
| plan | 2 | 50% | - | 100% | - | 0% |
| prescriber_name | 7 | 86% | 100% | 57% | 0% | 0% |
| prescription_diagnosis | 7 | 100% | 100% | 29% | 0% | 0% |
| requesting_doctor | 7 | 71% | 100% | 57% | 0% | 0% |
| specimen_type | 7 | 43% | 60% | 29% | 40% | 75% |
| tests_requested | 7 | 43% | 100% | 57% | 0% | - |
| vitals | 7 | 29% | - | 100% | - | - |
| vitals_diagnosis | 7 | 71% | 71% | 0% | 29% | 0% |
| ward | 7 | 100% | 100% | 29% | 0% | 0% |
| **overall** | 221 | 76% | 95% | 34% | 5% | 12% |
