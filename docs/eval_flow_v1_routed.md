# Eval report -- **flow set**

> Flow set proves plumbing. These numbers are NOT a performance
> claim (PRD 12.1); sign-off metrics come from the held-out set.

| field | n | exact acc | auto-acc acc | flag rate | FN flag rate | halluc |
|---|--:|--:|--:|--:|--:|--:|
| assessment | 2 | 0% | 0% | 0% | 100% | 100% |
| chief_complaint | 2 | 50% | 50% | 0% | 50% | - |
| document_date | 23 | 78% | 89% | 22% | 11% | 17% |
| document_type | 23 | 96% | 100% | 22% | 0% | - |
| hospital_number | 23 | 87% | 86% | 9% | 14% | 0% |
| lab_clinical_details | 7 | 43% | 43% | 0% | 57% | 100% |
| lab_priority | 7 | 71% | 80% | 29% | 20% | 0% |
| medications | 7 | 14% | 14% | 0% | 86% | - |
| patient_age_years | 23 | 100% | 100% | 4% | 0% | 0% |
| patient_name | 23 | 70% | 70% | 0% | 30% | 0% |
| patient_sex | 23 | 91% | 100% | 9% | 0% | 0% |
| plan | 2 | 50% | 0% | 50% | 100% | 0% |
| prescriber_name | 7 | 86% | 86% | 0% | 14% | 0% |
| prescription_diagnosis | 7 | 86% | 86% | 0% | 14% | 0% |
| requesting_doctor | 7 | 57% | 25% | 43% | 75% | 0% |
| specimen_type | 7 | 57% | 67% | 14% | 33% | 50% |
| tests_requested | 7 | 43% | 50% | 14% | 50% | - |
| vitals | 7 | 29% | 67% | 57% | 33% | - |
| vitals_diagnosis | 7 | 71% | 71% | 0% | 29% | 33% |
| ward | 7 | 100% | 100% | 43% | 0% | 0% |
| **overall** | 221 | 76% | 79% | 14% | 21% | 12% |
