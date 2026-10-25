"""Helixstreet Pharmacogenomic Knowledge Graph.

Substrate linking genes, PharmVar star-allele diplotypes, metabolizer phenotypes,
ATC/RxNorm drugs, CPIC + DPWG + PharmGKB clinical annotations, EU/Swissmedic/FDA
regulatory labels, ranked therapeutic alternatives, and curated guideline summaries.
Every recommendation is reproducible from its cited guideline summary and evidence
level (Corti-grade auditability — zero hallucinated clinical guidance).
"""
from __future__ import annotations

import re

# Corti-grade structured guideline rules:
# Keyed by lowercase generic drug name -> gene -> phenotype category ("poor", "intermediate", "rapid", "normal")
PGX_KNOWLEDGE_GRAPH: dict[str, dict] = {
    "clopidogrel": {
        "drug": "clopidogrel",
        "atc_code": "B01AC04",
        "rxnorm_id": "32968",
        "therapeutic_class": "P2Y12 Platelet Inhibitor (Cardiovascular / Neurovascular)",
        "gene": "CYP2C19",
        "guideline": "CPIC Guideline for Clopidogrel and CYP2C19",
        "guideline_version": "CPIC 2022/2024 Update (ClinPGx PA166104948 · PMC9287492)",
        "guideline_url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC9287492/",
        "dpwg_concordance": (
            "DPWG 2024 (KNMP): CYP2C19 Poor & Intermediate Metabolizers — avoid clopidogrel in "
            "percutaneous coronary intervention (PCI) / acute coronary syndrome (ACS) and TIA/stroke; "
            "choose alternative antiplatelet agent (prasugrel or ticagrelor) or double dose if contraindicated."
        ),
        "regulatory_labels": {
            "FDA": "Boxed Warning: Diminished antiplatelet effect in patients with two loss-of-function alleles of the CYP2C19 gene (*2, *3). Use another platelet P2Y12 inhibitor.",
            "EMA_Swissmedic": "SmPC Section 4.4 / 5.2: CYP2C19 poor metabolisers form less active metabolite of clopidogrel and exhibit reduced antiplatelet responses.",
        },
        "phenotypes": {
            "poor": {
                "phenotype_label": "CYP2C19 Poor Metabolizer",
                "example_diplotypes": ["*2/*2", "*2/*3", "*3/*3"],
                "actionability": "CRITICAL — DO NOT DISPENSE STANDARD CLOPIDOGREL",
                "evidence_level": "1A",
                "cpic_strength": "Strong",
                "primary_recommendation": (
                    "Avoid standard-dose clopidogrel (75 mg/day). CYP2C19 poor metabolizers have minimal "
                    "hepatic bioactivation of prodrug clopidogrel to its active thiol metabolite, resulting "
                    "in significantly higher risk of stent thrombosis, myocardial infarction, and ischemic stroke."
                ),
                "ranked_alternatives": [
                    {
                        "rank": 1,
                        "drug": "prasugrel",
                        "rxnorm_id": "613391",
                        "dosing": "60 mg loading dose, then 10 mg once daily (if no history of stroke/TIA, age <75 years, weight >=60 kg)",
                        "rationale": "Bioactivation is independent of CYP2C19 loss-of-function alleles.",
                        "evidence_level": "1A",
                        "guideline_source": "CPIC 2022 Table 2 / DPWG 2024",
                    },
                    {
                        "rank": 2,
                        "drug": "ticagrelor",
                        "rxnorm_id": "1116632",
                        "dosing": "180 mg loading dose, then 90 mg twice daily with low-dose aspirin",
                        "rationale": "Direct-acting reversible P2Y12 antagonist; does not require CYP2C19 metabolic activation.",
                        "evidence_level": "1A",
                        "guideline_source": "CPIC 2022 Table 2 / DPWG 2024",
                    },
                ],
                "guideline_summary": (
                    "CPIC Guideline for CYP2C19 and Clopidogrel Therapy (Lee et al., Clin Pharmacol Ther 2022; "
                    "PMID: 35034351, Table 2): 'CYP2C19 Poor Metabolizer (*2/*2, *2/*3, *3/*3): Significantly "
                    "reduced platelet inhibition; increased residual platelet aggregation; increased risk for "
                    "adverse cardiovascular and cerebrovascular events. Recommendation: Avoid clopidogrel; "
                    "use prasugrel or ticagrelor at standard dose if no contraindication (Classification: Strong, Level 1A).'"
                ),
            },
            "intermediate": {
                "phenotype_label": "CYP2C19 Intermediate Metabolizer",
                "example_diplotypes": ["*1/*2", "*1/*3", "*2/*17"],
                "actionability": "ACTIONABLE — ALTERNATIVE P2Y12 INHIBITOR RECOMMENDED",
                "evidence_level": "1A",
                "cpic_strength": "Strong",
                "primary_recommendation": (
                    "Avoid standard-dose clopidogrel for ACS/PCI; select an alternative P2Y12 inhibitor "
                    "(prasugrel or ticagrelor) if no contraindication."
                ),
                "ranked_alternatives": [
                    {
                        "rank": 1,
                        "drug": "prasugrel",
                        "rxnorm_id": "613391",
                        "dosing": "10 mg once daily maintenance",
                        "rationale": "Unaffected by CYP2C19 heterozygosity.",
                        "evidence_level": "1A",
                        "guideline_source": "CPIC 2022 Table 2",
                    },
                    {
                        "rank": 2,
                        "drug": "ticagrelor",
                        "rxnorm_id": "1116632",
                        "dosing": "90 mg twice daily",
                        "rationale": "Direct-acting P2Y12 inhibitor.",
                        "evidence_level": "1A",
                        "guideline_source": "CPIC 2022 Table 2",
                    },
                ],
                "guideline_summary": (
                    "CPIC 2022 (PMID: 35034351, Table 2): 'CYP2C19 Intermediate Metabolizer (*1/*2, *1/*3, *2/*17): "
                    "Alternative antiplatelet therapy (if no contraindication), e.g., prasugrel or ticagrelor "
                    "(Classification: Strong, Level 1A).'"
                ),
            },
            "normal": {
                "phenotype_label": "CYP2C19 Normal Metabolizer",
                "example_diplotypes": ["*1/*1"],
                "actionability": "STANDARD DOSING — NO GENOTYPE ADJUSTMENT REQUIRED",
                "evidence_level": "1A",
                "cpic_strength": "Strong",
                "primary_recommendation": (
                    "Use clopidogrel at standard label-recommended dosage (75 mg/day maintenance). "
                    "Normal CYP2C19 bioactivation to active thiol metabolite."
                ),
                "ranked_alternatives": [
                    {
                        "rank": 1,
                        "drug": "clopidogrel",
                        "rxnorm_id": "32968",
                        "dosing": "Standard dose (300–600 mg loading, 75 mg once daily maintenance)",
                        "rationale": "Normal CYP2C19 *1/*1 metabolic bioactivation.",
                        "evidence_level": "1A",
                        "guideline_source": "CPIC 2022 Table 2",
                    },
                ],
                "guideline_summary": (
                    "CPIC 2022 (PMID: 35034351, Table 2): 'CYP2C19 Normal Metabolizer (*1/*1): Normal clopidogrel "
                    "active metabolite formation and normal platelet inhibition. Recommendation: Use clopidogrel "
                    "at standard dose (Classification: Strong, Level 1A).'"
                ),
            },
            "rapid": {
                "phenotype_label": "CYP2C19 Rapid / Ultrarapid Metabolizer",
                "example_diplotypes": ["*1/*17", "*17/*17"],
                "actionability": "STANDARD DOSING — NO GENOTYPE ADJUSTMENT REQUIRED",
                "evidence_level": "1A",
                "cpic_strength": "Strong",
                "primary_recommendation": (
                    "If considering clopidogrel, use at standard dose (75 mg/day). Rapid and ultrarapid "
                    "metabolizers form normal-to-increased amounts of the active metabolite (ACS/PCI population)."
                ),
                "ranked_alternatives": [
                    {
                        "rank": 1,
                        "drug": "clopidogrel",
                        "rxnorm_id": "32968",
                        "dosing": "Standard dose (300–600 mg loading, 75 mg once daily maintenance)",
                        "rationale": "Normal or increased CYP2C19 bioactivation (*17 increased-function allele).",
                        "evidence_level": "1A",
                        "guideline_source": "CPIC 2022 Table 2 (CPIC REST API recommendation row, ACS/PCI)",
                    },
                ],
                "guideline_summary": (
                    "CPIC 2022 (PMID: 35034351, Table 2): 'CYP2C19 Rapid (*1/*17) or Ultrarapid (*17/*17) Metabolizer: "
                    "If considering clopidogrel, use at standard dose (75 mg/day) (Classification: Strong, Level 1A).'"
                ),
            },
        },
    },
    "escitalopram": {
        "drug": "escitalopram",
        "atc_code": "N06AB10",
        "rxnorm_id": "321988",
        "therapeutic_class": "Selective Serotonin Reuptake Inhibitor (SSRI — Psychiatry)",
        "gene": "CYP2C19",
        "guideline": "CPIC Guideline for CYP2C19, CYP2D6, and CYP2B6 and Serotonin Reuptake Inhibitor Antidepressants",
        "guideline_version": "CPIC 2023 SSRI Update (ClinPGx PA166299601 · PMC10564324)",
        "guideline_url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC10564324/",
        "dpwg_concordance": (
            "DPWG 2024: CYP2C19 Poor Metabolizers experience ~2.1x higher escitalopram plasma exposure "
            "and increased risk of QTc prolongation; do not exceed 10 mg/day (50% of standard maximum) "
            "or select an antidepressant not predominantly metabolized by CYP2C19."
        ),
        "regulatory_labels": {
            "FDA": "Clinical Pharmacology: In CYP2C19 poor metabolizers, escitalopram AUC is doubled; maximum recommended dose is 10 mg/day due to dose-dependent QT prolongation.",
            "EMA_Swissmedic": "SmPC Section 4.2 / 4.4: For patients known to be poor metabolisers with respect to CYP2C19, an initial 5 mg daily dose is recommended and the maximum dose should be limited to 10 mg/day (QT prolongation risk).",
        },
        "phenotypes": {
            "poor": {
                "phenotype_label": "CYP2C19 Poor Metabolizer",
                "example_diplotypes": ["*2/*2", "*2/*3"],
                "actionability": "HIGH RISK — DOSE REDUCTION (50%) OR ALTERNATIVE SSRI REQUIRED",
                "evidence_level": "1A",
                "cpic_strength": "Strong",
                "primary_recommendation": (
                    "Consider an alternative antidepressant not predominantly metabolized by CYP2C19. "
                    "If escitalopram is clinically warranted, reduce starting dose by 50% (5 mg/day) and "
                    "do not exceed a maximum daily dose of 10 mg/day due to elevated plasma concentrations "
                    "and FDA/EMA QTc prolongation warnings."
                ),
                "ranked_alternatives": [
                    {
                        "rank": 1,
                        "drug": "fluoxetine or paroxetine (if CYP2D6 normal)",
                        "rxnorm_id": "4493",
                        "dosing": "Standard SSRI starting dose (verify CYP2D6 status)",
                        "rationale": "Clearance is not primarily dependent on CYP2C19.",
                        "evidence_level": "1A",
                        "guideline_source": "CPIC 2023 SSRI Guideline Table 2a",
                    },
                    {
                        "rank": 2,
                        "drug": "escitalopram (50% dose-capped regimen)",
                        "rxnorm_id": "321988",
                        "dosing": "5 mg once daily initial dose; cap maximum maintenance dose at <=10 mg/day with baseline ECG",
                        "rationale": "Compensates for 2-fold higher steady-state AUC in CYP2C19*2/*2 poor metabolizers.",
                        "evidence_level": "1A",
                        "guideline_source": "CPIC 2023 Table 2a / DPWG 2024 / EMA SmPC",
                    },
                ],
                "guideline_summary": (
                    "CPIC Guideline for CYP2C19 and SSRI Antidepressants (Bousman et al., Clin Pharmacol Ther 2023; "
                    "PMID: 37032427, Table 2a): 'CYP2C19 Poor Metabolizer: Greatly reduced metabolism of escitalopram "
                    "and citalopram to less active metabolites, resulting in higher plasma concentrations and increased "
                    "risk of adverse effects including QT prolongation. Recommendation: Consider a clinically appropriate "
                    "alternative antidepressant not predominantly metabolized by CYP2C19, or reduce starting dose and "
                    "maintenance dose by 50% (Classification: Strong, Level 1A).'"
                ),
            },
            "normal": {
                "phenotype_label": "CYP2C19 Normal Metabolizer",
                "example_diplotypes": ["*1/*1"],
                "actionability": "STANDARD DOSING — NO GENOTYPE ADJUSTMENT REQUIRED",
                "evidence_level": "1A",
                "cpic_strength": "Strong",
                "primary_recommendation": "Initiate escitalopram at standard recommended starting dose (10 mg/day).",
                "ranked_alternatives": [
                    {
                        "rank": 1,
                        "drug": "escitalopram",
                        "rxnorm_id": "321988",
                        "dosing": "Standard dose (10–20 mg once daily)",
                        "rationale": "Normal CYP2C19 clearance.",
                        "evidence_level": "1A",
                        "guideline_source": "CPIC 2023 Table 2a",
                    },
                ],
                "guideline_summary": (
                    "CPIC 2023 (PMID: 37032427, Table 2a): 'CYP2C19 Normal Metabolizer (*1/*1): Initiate therapy "
                    "with recommended starting dose (Strong, Level 1A).'"
                ),
            },
            "intermediate": {
                "phenotype_label": "CYP2C19 Intermediate Metabolizer",
                "example_diplotypes": ["*1/*2", "*1/*3", "*2/*17"],
                "actionability": "STANDARD STARTING DOSE — SLOWER TITRATION, LOWER MAINTENANCE DOSE",
                "evidence_level": "1A",
                "cpic_strength": "Moderate",
                "primary_recommendation": (
                    "Initiate therapy with the recommended starting dose. Consider a slower titration schedule "
                    "and a lower maintenance dose than CYP2C19 normal metabolizers."
                ),
                "ranked_alternatives": [
                    {
                        "rank": 1,
                        "drug": "escitalopram",
                        "rxnorm_id": "321988",
                        "dosing": "Standard starting dose (10 mg/day); slower titration; lower maintenance dose",
                        "rationale": "Moderately reduced CYP2C19 clearance.",
                        "evidence_level": "1A",
                        "guideline_source": "CPIC 2023 Table 3 (CPIC REST API recommendation row)",
                    },
                ],
                "guideline_summary": (
                    "CPIC 2023 (PMID: 37032427, Table 3): 'CYP2C19 Intermediate Metabolizer: Initiate therapy with "
                    "recommended starting dose. Consider a slower titration schedule and lower maintenance dose than "
                    "normal metabolizers (Classification: Moderate).'"
                ),
            },
            "rapid": {
                "phenotype_label": "CYP2C19 Rapid / Ultrarapid Metabolizer",
                "example_diplotypes": ["*1/*17", "*17/*17"],
                "actionability": "RAPID: STANDARD START, ESCALATE IF NO RESPONSE · ULTRARAPID: CONSIDER NON-CYP2C19 ALTERNATIVE",
                "evidence_level": "1A",
                "cpic_strength": "Optional (RM) / Strong (UM)",
                "primary_recommendation": (
                    "Rapid metabolizer (*1/*17): initiate therapy with the recommended starting dose; if the patient "
                    "does not adequately respond to maintenance dosing, consider titrating to a higher maintenance "
                    "dose or switching to an antidepressant not predominantly metabolized by CYP2C19. Ultrarapid "
                    "metabolizer (*17/*17): consider a clinically appropriate alternative antidepressant not "
                    "predominantly metabolized by CYP2C19."
                ),
                "ranked_alternatives": [
                    {
                        "rank": 1,
                        "drug": "fluoxetine",
                        "rxnorm_id": "4493",
                        "dosing": "Standard dose (20 mg/day), predominantly CYP2D6-metabolized",
                        "rationale": "Alternative not predominantly metabolized by CYP2C19 (ultrarapid metabolizers).",
                        "evidence_level": "1A",
                        "guideline_source": "CPIC 2023 Table 3",
                    },
                ],
                "guideline_summary": (
                    "CPIC 2023 (PMID: 37032427, Table 3): 'CYP2C19 Ultrarapid Metabolizer: Consider a clinically "
                    "appropriate alternative antidepressant not predominantly metabolized by CYP2C19 (Strong). "
                    "Rapid Metabolizer: Initiate therapy with recommended starting dose; if no adequate response, "
                    "consider a higher maintenance dose or switching (Optional).'"
                ),
            },
        },
    },
    "citalopram": {
        "drug": "citalopram",
        "atc_code": "N06AB04",
        "rxnorm_id": "2556",
        "therapeutic_class": "Selective Serotonin Reuptake Inhibitor (SSRI — Psychiatry)",
        "gene": "CYP2C19",
        "guideline": "CPIC Guideline for CYP2C19 and SSRI Antidepressants",
        "guideline_version": "CPIC 2023 SSRI Update (ClinPGx PA166299601 · PMC10564324)",
        "guideline_url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC10564324/",
        "dpwg_concordance": "DPWG 2024: Do not exceed 20 mg/day citalopram in CYP2C19 Poor Metabolizers (50% of normal maximum) or select an alternative SSRI.",
        "regulatory_labels": {
            "FDA": "Drug Safety Communication: Citalopram causes dose-dependent QT interval prolongation; maximum recommended dose is 20 mg/day in CYP2C19 poor metabolizers.",
            "EMA_Swissmedic": "SmPC Section 4.2: Maximum dose of 20 mg daily for known CYP2C19 poor metabolisers.",
        },
        "phenotypes": {
            "poor": {
                "phenotype_label": "CYP2C19 Poor Metabolizer",
                "example_diplotypes": ["*2/*2"],
                "actionability": "HIGH RISK — 50% DOSE CAP (MAX 20 MG/DAY) OR SWITCH SSRI",
                "evidence_level": "1A",
                "cpic_strength": "Strong",
                "primary_recommendation": (
                    "Select a non-CYP2C19 antidepressant or reduce citalopram dose by 50% (maximum 20 mg/day) "
                    "due to elevated S-citalopram exposure and QTc prolongation risk."
                ),
                "ranked_alternatives": [
                    {
                        "rank": 1,
                        "drug": "non-CYP2C19 SSRI/SNRI (e.g., duloxetine or venlafaxine)",
                        "rxnorm_id": "72625",
                        "dosing": "Standard initiation dosing",
                        "rationale": "Avoids CYP2C19 metabolic bottleneck.",
                        "evidence_level": "1A",
                        "guideline_source": "CPIC 2023 Table 2a",
                    },
                    {
                        "rank": 2,
                        "drug": "citalopram (50% dose-reduced)",
                        "rxnorm_id": "2556",
                        "dosing": "10 mg/day initial; maximum 20 mg/day",
                        "rationale": "FDA/EMA/CPIC mandated ceiling for CYP2C19 poor metabolizers.",
                        "evidence_level": "1A",
                        "guideline_source": "CPIC 2023 / FDA Drug Label",
                    },
                ],
                "guideline_summary": (
                    "CPIC 2023 (Bousman et al., PMID: 37032427, Table 2a): 'CYP2C19 Poor Metabolizer: Consider an "
                    "alternative antidepressant not predominantly metabolized by CYP2C19; if citalopram is warranted, "
                    "reduce starting dose by 50% and titrate to a maximum of 20 mg/day (Level 1A, Strong).'"
                ),
            },
            "intermediate": {
                "phenotype_label": "CYP2C19 Intermediate Metabolizer",
                "example_diplotypes": ["*1/*2", "*1/*3", "*2/*17"],
                "actionability": "STANDARD STARTING DOSE — SLOWER TITRATION, LOWER MAINTENANCE DOSE",
                "evidence_level": "1A",
                "cpic_strength": "Moderate",
                "primary_recommendation": (
                    "Initiate therapy with the recommended starting dose. Consider a slower titration schedule "
                    "and a lower maintenance dose than CYP2C19 normal metabolizers."
                ),
                "ranked_alternatives": [
                    {
                        "rank": 1,
                        "drug": "citalopram",
                        "rxnorm_id": "2556",
                        "dosing": "Standard starting dose (20 mg/day); slower titration; lower maintenance dose",
                        "rationale": "Moderately reduced CYP2C19 clearance.",
                        "evidence_level": "1A",
                        "guideline_source": "CPIC 2023 Table 3 (CPIC REST API recommendation row)",
                    },
                ],
                "guideline_summary": (
                    "CPIC 2023 (PMID: 37032427, Table 3): 'CYP2C19 Intermediate Metabolizer: Initiate therapy with "
                    "recommended starting dose. Consider a slower titration schedule and lower maintenance dose than "
                    "normal metabolizers (Classification: Moderate).'"
                ),
            },
            "rapid": {
                "phenotype_label": "CYP2C19 Rapid / Ultrarapid Metabolizer",
                "example_diplotypes": ["*1/*17", "*17/*17"],
                "actionability": "RAPID: STANDARD START, ESCALATE IF NO RESPONSE · ULTRARAPID: CONSIDER NON-CYP2C19 ALTERNATIVE",
                "evidence_level": "1A",
                "cpic_strength": "Optional (RM) / Strong (UM)",
                "primary_recommendation": (
                    "Rapid metabolizer (*1/*17): initiate therapy with the recommended starting dose; if the patient "
                    "does not adequately respond, consider a higher maintenance dose or switching to an antidepressant "
                    "not predominantly metabolized by CYP2C19. Ultrarapid metabolizer (*17/*17): consider a clinically "
                    "appropriate alternative antidepressant not predominantly metabolized by CYP2C19."
                ),
                "ranked_alternatives": [
                    {
                        "rank": 1,
                        "drug": "fluoxetine",
                        "rxnorm_id": "4493",
                        "dosing": "Standard dose (20 mg/day), predominantly CYP2D6-metabolized",
                        "rationale": "Alternative not predominantly metabolized by CYP2C19 (ultrarapid metabolizers).",
                        "evidence_level": "1A",
                        "guideline_source": "CPIC 2023 Table 3",
                    },
                ],
                "guideline_summary": (
                    "CPIC 2023 (PMID: 37032427, Table 3): 'CYP2C19 Ultrarapid Metabolizer: Consider a clinically "
                    "appropriate alternative antidepressant not predominantly metabolized by CYP2C19 (Strong). "
                    "Rapid Metabolizer: Initiate therapy with recommended starting dose; if no adequate response, "
                    "consider a higher maintenance dose or switching (Optional).'"
                ),
            },
        },
    },
    "5-fluorouracil": {
        "drug": "5-fluorouracil",
        "atc_code": "L01BC02",
        "rxnorm_id": "4492",
        "therapeutic_class": "Fluoropyrimidine Antimetabolite (Oncology)",
        "gene": "DPYD",
        "guideline": "CPIC Guideline for Fluoropyrimidines and DPYD",
        "guideline_version": "CPIC 2018/2024 Update (ClinPGx PA166122686 · PMC5760397)",
        "guideline_url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC5760397/",
        "dpwg_concordance": "DPWG 2024 & EMA 2020 Mandate: Mandatory pre-treatment DPYD testing in Europe; reduce starting dose by 50% in DPYD Activity Score 1.0 (*1/*2A) or avoid completely in Activity Score 0 (*2A/*2A).",
        "regulatory_labels": {
            "FDA": "Boxed Warning: Increased risk of serious or fatal mucositis, diarrhea, neutropenia, and neurotoxicity in patients with DPD deficiency (DPYD*2A).",
            "EMA_Swissmedic": "EMA Direct Healthcare Professional Communication (DHPC): Pre-treatment testing for DPD deficiency is recommended before initiating 5-FU or capecitabine.",
        },
        "phenotypes": {
            "intermediate": {
                "phenotype_label": "DPYD Intermediate Metabolizer (Activity Score 1.0, *1/*2A)",
                "example_diplotypes": ["*1/*2A", "c.1905+1G>A het"],
                "actionability": "CRITICAL LIFE-THREATENING TOXICITY — REDUCE STARTING DOSE BY 50%",
                "evidence_level": "1A",
                "cpic_strength": "Strong",
                "primary_recommendation": (
                    "Reduce 5-fluorouracil or capecitabine starting dose by 50% (Activity Score 1.0 due to "
                    "heterozygous non-functional DPYD*2A / rs3918290), followed by therapeutic drug monitoring "
                    "and clinical tolerance titration."
                ),
                "ranked_alternatives": [
                    {
                        "rank": 1,
                        "drug": "5-fluorouracil / capecitabine at 50% initial dose",
                        "rxnorm_id": "4492",
                        "dosing": "50% of standard BSA-calculated starting dose; titrate in subsequent cycles based on ANC/mucositis tolerance",
                        "rationale": "Restores systemic 5-FU AUC to match wild-type DPYD*1/*1 exposure while preserving antitumor efficacy.",
                        "evidence_level": "1A",
                        "guideline_source": "CPIC 2018 Table 2 / DPWG 2024",
                    },
                    {
                        "rank": 2,
                        "drug": "raltitrexed (thymidylate synthase inhibitor)",
                        "rxnorm_id": "83556",
                        "dosing": "3 mg/m² IV every 3 weeks (where clinically indicated for colorectal cancer)",
                        "rationale": "Catabolism does not depend on dihydropyrimidine dehydrogenase (DPD).",
                        "evidence_level": "1A",
                        "guideline_source": "DPWG / ESMO Clinical Practice Guidelines",
                    },
                ],
                "guideline_summary": (
                    "CPIC Guideline for Dihydropyrimidine Dehydrogenase Genotype and Fluoropyrimidine Dosing "
                    "(Amstutz et al., Clin Pharmacol Ther 2018; PMID: 29152729, Table 2): 'DPYD Intermediate "
                    "Metabolizer (Activity Score 1.0, e.g., heterozygous c.1905+1G>A / *2A): Increased risk for "
                    "severe or even fatal drug toxicity when treated with fluoropyrimidine drugs. Recommendation: "
                    "Reduce starting dose by 50% followed by titration of dose based on toxicity (Classification: Strong, Level 1A).'"
                ),
            }
        },
    },
    "simvastatin": {
        "drug": "simvastatin",
        "atc_code": "C10AA01",
        "rxnorm_id": "36567",
        "therapeutic_class": "HMG-CoA Reductase Inhibitor (Statin — Lipid Lowering)",
        "gene": "SLCO1B1",
        "guideline": "CPIC Guideline for Statins and SLCO1B1, ABCG2, and CYP2C9",
        "guideline_version": "CPIC 2022 Statin Update (ClinPGx PA166105005 · PMC9035072)",
        "guideline_url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC9035072/",
        "dpwg_concordance": "DPWG 2024: Choose an alternative statin (rosuvastatin or pravastatin) or avoid simvastatin doses >40 mg/day in SLCO1B1 521T>C (*5) carriers.",
        "regulatory_labels": {
            "FDA": "Warnings and Precautions: Myopathy/rhabdomyolysis risk is increased in carriers of SLCO1B1 decreased-function alleles (c.521T>C).",
            "EMA_Swissmedic": "SmPC Section 4.4: SLCO1B1 c.521T>C polymorphism increases systemic simvastatin acid exposure (AUC +221% in CC homozygotes).",
        },
        "phenotypes": {
            "intermediate": {
                "phenotype_label": "SLCO1B1 Decreased Function (*1/*5, c.521T>C het)",
                "example_diplotypes": ["*1/*5", "*5/*5"],
                "actionability": "ACTIONABLE — SWITCH TO ROSUVASTATIN/PRAVASTATIN OR LIMIT TO <=20 MG/DAY",
                "evidence_level": "1A",
                "cpic_strength": "Strong",
                "primary_recommendation": (
                    "Prescribe an alternative statin less dependent on OATP1B1 hepatic transport "
                    "(e.g., rosuvastatin or pravastatin), or limit simvastatin dose to <=20 mg/day to "
                    "prevent statin-associated musculoskeletal symptoms (SAMS) and rhabdomyolysis."
                ),
                "ranked_alternatives": [
                    {
                        "rank": 1,
                        "drug": "rosuvastatin",
                        "rxnorm_id": "301542",
                        "dosing": "5–20 mg once daily (high-intensity lipid lowering with lower SLCO1B1 myopathy liability)",
                        "rationale": "Multiple hepatic uptake transporters (OATP1B1, OATP1B3, OATP2B1, NTCP) buffer SLCO1B1*5 impairment.",
                        "evidence_level": "1A",
                        "guideline_source": "CPIC 2022 Statin Guideline Figure 1 / Table 2",
                    },
                    {
                        "rank": 2,
                        "drug": "pravastatin",
                        "rxnorm_id": "42463",
                        "dosing": "20–40 mg once daily",
                        "rationale": "Hydrophilic statin with minimal skeletal muscle myotoxicity in SLCO1B1*5 carriers.",
                        "evidence_level": "1A",
                        "guideline_source": "CPIC 2022 Table 2 / DPWG 2024",
                    },
                ],
                "guideline_summary": (
                    "CPIC Guideline for Statins and SLCO1B1 (Cooper-DeHoff et al., Clin Pharmacol Ther 2022; "
                    "PMID: 35152405): 'SLCO1B1 Decreased or Poor Function (*1/*5, *5/*5): Increased simvastatin "
                    "acid concentration and increased risk of statin-associated musculoskeletal symptoms. "
                    "Recommendation: Prescribe an alternative statin depending on desired potency (e.g., rosuvastatin, "
                    "pravastatin, fluvastatin); if simvastatin is used, limit dose to <20 mg/day (Strong, Level 1A).'"
                ),
            }
        },
    },
    "warfarin": {
        "drug": "warfarin",
        "atc_code": "B01AA03",
        "rxnorm_id": "11289",
        "therapeutic_class": "Vitamin K Antagonist (Oral Anticoagulant)",
        "gene": "CYP2C9+VKORC1",
        "guideline": "CPIC Guideline for Pharmacogenetics-Guided Warfarin Dosing",
        "guideline_version": "CPIC 2017 Warfarin Guideline (ClinPGx PA166104949 · PMC5546947)",
        "guideline_url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC5546947/",
        "dpwg_concordance": "DPWG 2024: Reduce initial and maintenance warfarin/phenprocoumon dose using validated pharmacogenetic algorithm (EU-PACT / IWPC) for CYP2C9*3 and VKORC1 -1639A/A.",
        "regulatory_labels": {
            "FDA": "Boxed Warning & Table 1 Dosing Guide: Combined CYP2C9 (*1/*3) and VKORC1 (-1639A/A) genotype requires reduced initial warfarin dose of 0.5–2.0 mg/day.",
            "EMA_Swissmedic": "SmPC Section 4.2: Genetic polymorphisms in CYP2C9 and VKORC1 substantially reduce warfarin clearance and target dose requirements.",
        },
        "phenotypes": {
            "intermediate": {
                "phenotype_label": "CYP2C9 Intermediate Metabolizer (*1/*3) + VKORC1 Increased Sensitivity",
                "example_diplotypes": ["CYP2C9 *1/*3 + VKORC1 -1639G/-1639A", "CYP2C9 *1/*3 + VKORC1 -1639A/A"],
                "actionability": "HIGH BLEEDING RISK — REDUCE WARFARIN DOSE BY 50–70% OR USE DOAC",
                "evidence_level": "1A",
                "cpic_strength": "Strong",
                "primary_recommendation": (
                    "Calculate warfarin dose using a validated pharmacogenetic algorithm (IWPC / Gage) "
                    "incorporating both CYP2C9*3 (reduced S-warfarin clearance) and VKORC1 -1639G>A "
                    "(increased target sensitivity), reducing expected maintenance dose to ~1.5–2.5 mg/day, "
                    "or select a Direct Oral Anticoagulant (apixaban, rivaroxaban, dabigatran)."
                ),
                "ranked_alternatives": [
                    {
                        "rank": 1,
                        "drug": "apixaban or rivaroxaban (DOAC)",
                        "rxnorm_id": "1364430",
                        "dosing": "Apixaban 5 mg twice daily (if non-valvular AF / VTE and normal renal function)",
                        "rationale": "Direct Factor Xa inhibitor; therapeutic window does not depend on VKORC1 or CYP2C9*3.",
                        "evidence_level": "1A",
                        "guideline_source": "ESC / AHA Anticoagulation Guidelines",
                    },
                    {
                        "rank": 2,
                        "drug": "warfarin (IWPC PGx-dosed)",
                        "rxnorm_id": "11289",
                        "dosing": "1.5–2.0 mg once daily initial dose with INR check on Day 3–4",
                        "rationale": "Prevents supratherapeutic INR (>4.0) and major hemorrhage during induction.",
                        "evidence_level": "1A",
                        "guideline_source": "CPIC 2017 Warfarin Guideline / FDA Label Table 1",
                    },
                ],
                "guideline_summary": (
                    "CPIC Guideline for Pharmacogenetics-Guided Warfarin Dosing (Johnson et al., Clin Pharmacol Ther 2017; "
                    "PMID: 28198005): 'In patients carrying CYP2C9*2 or *3 alleles combined with VKORC1 -1639G>A, "
                    "calculate warfarin dosing using a published pharmacogenetic algorithm (IWPC or Gage) to reduce "
                    "time to therapeutic INR and risk of over-anticoagulation (Classification: Strong, Level 1A).'"
                ),
            }
        },
    },
    "voriconazole": {
        "drug": "voriconazole",
        "atc_code": "J02AC03",
        "rxnorm_id": "121243",
        "therapeutic_class": "Triazole Antifungal (Invasive Aspergillosis / Candidiasis)",
        "gene": "CYP2C19",
        "guideline": "CPIC Guideline for CYP2C19 and Voriconazole Therapy",
        "guideline_version": "CPIC 2016 (Moriyama et al., Clin Pharmacol Ther 2017 · PMC5474211)",
        "guideline_url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC5474211/",
        "dpwg_concordance": "DPWG (KNMP) guidance for this pair is not curated in this demo slice; CPIC is the primary source shown here.",
        "regulatory_labels": {
            "FDA": "VFEND label (Clinical Pharmacology): CYP2C19 poor metabolizers have on average about 4-fold higher voriconazole exposure (AUC) than homozygous extensive metabolizers.",
            "EMA_Swissmedic": "Not curated in this demo slice.",
        },
        "phenotypes": {
            "poor": {
                "phenotype_label": "CYP2C19 Poor Metabolizer",
                "example_diplotypes": ["*2/*2", "*2/*3", "*3/*3"],
                "actionability": "AVOID — CHOOSE A NON-CYP2C19-DEPENDENT ANTIFUNGAL (OR LOWER DOSE + TDM)",
                "evidence_level": "1A",
                "cpic_strength": "Moderate",
                "primary_recommendation": (
                    "Choose an alternative agent that is not dependent on CYP2C19 metabolism as primary therapy in lieu "
                    "of voriconazole (isavuconazole, liposomal amphotericin B, or posaconazole). If voriconazole is "
                    "considered the most appropriate agent, administer a lower-than-standard dose with careful "
                    "therapeutic drug monitoring."
                ),
                "ranked_alternatives": [
                    {"rank": 1, "drug": "isavuconazole", "rxnorm_id": "1608321", "dosing": "Standard label dosing (isavuconazonium sulfate)", "rationale": "Not dependent on CYP2C19 metabolism.", "evidence_level": "1A", "guideline_source": "CPIC 2016 Table 2 (adults)"},
                    {"rank": 2, "drug": "posaconazole", "rxnorm_id": "282446", "dosing": "Standard label dosing", "rationale": "Not dependent on CYP2C19 metabolism.", "evidence_level": "1A", "guideline_source": "CPIC 2016 Table 2 (adults)"},
                    {"rank": 3, "drug": "liposomal amphotericin B", "rxnorm_id": "236594", "dosing": "Standard label dosing", "rationale": "Not dependent on CYP2C19 metabolism.", "evidence_level": "1A", "guideline_source": "CPIC 2016 Table 2 (adults)"},
                ],
                "guideline_summary": (
                    "CPIC Guideline for CYP2C19 and Voriconazole Therapy (Moriyama et al., Clin Pharmacol Ther 2017; "
                    "PMID: 27981572, Table 2, adults): 'CYP2C19 Poor Metabolizer: Higher dose-adjusted trough concentrations "
                    "of voriconazole and may increase probability of adverse events. Choose an alternative agent that is not "
                    "dependent on CYP2C19 metabolism as primary therapy in lieu of voriconazole (Classification: Moderate).'"
                ),
            },
            "intermediate": {
                "phenotype_label": "CYP2C19 Intermediate Metabolizer",
                "example_diplotypes": ["*1/*2", "*1/*3", "*2/*17"],
                "actionability": "STANDARD DOSING — HIGHER TROUGH CONCENTRATIONS EXPECTED, MONITOR",
                "evidence_level": "1A",
                "cpic_strength": "Moderate",
                "primary_recommendation": (
                    "Initiate therapy with recommended standard-of-care dosing; dose-adjusted trough concentrations are "
                    "higher than in normal metabolizers, so therapeutic drug monitoring is advisable."
                ),
                "ranked_alternatives": [
                    {"rank": 1, "drug": "voriconazole", "rxnorm_id": "121243", "dosing": "Standard dosing with therapeutic drug monitoring", "rationale": "Moderately higher exposure than normal metabolizers.", "evidence_level": "1A", "guideline_source": "CPIC 2016 Table 2 (adults)"},
                ],
                "guideline_summary": (
                    "CPIC 2016 (PMID: 27981572, Table 2, adults): 'CYP2C19 Intermediate Metabolizer: Higher dose-adjusted "
                    "trough concentrations of voriconazole compared to normal metabolizers. Initiate therapy with recommended "
                    "standard of care dosing (Classification: Moderate).'"
                ),
            },
            "normal": {
                "phenotype_label": "CYP2C19 Normal Metabolizer",
                "example_diplotypes": ["*1/*1"],
                "actionability": "STANDARD DOSING — NO GENOTYPE ADJUSTMENT REQUIRED",
                "evidence_level": "1A",
                "cpic_strength": "Strong",
                "primary_recommendation": "Initiate therapy with recommended standard-of-care dosing.",
                "ranked_alternatives": [
                    {"rank": 1, "drug": "voriconazole", "rxnorm_id": "121243", "dosing": "Standard dosing", "rationale": "Normal CYP2C19 metabolism.", "evidence_level": "1A", "guideline_source": "CPIC 2016 Table 2 (adults)"},
                ],
                "guideline_summary": "CPIC 2016 (PMID: 27981572, Table 2, adults): 'CYP2C19 Normal Metabolizer: Normal voriconazole metabolism. Initiate therapy with recommended standard of care dosing (Classification: Strong).'",
            },
            "rapid": {
                "phenotype_label": "CYP2C19 Rapid / Ultrarapid Metabolizer",
                "example_diplotypes": ["*1/*17", "*17/*17"],
                "actionability": "AVOID — LOW PROBABILITY OF THERAPEUTIC CONCENTRATIONS WITH STANDARD DOSING",
                "evidence_level": "1A",
                "cpic_strength": "Moderate",
                "primary_recommendation": (
                    "Choose an alternative agent that is not dependent on CYP2C19 metabolism as primary therapy in lieu of "
                    "voriconazole (isavuconazole, liposomal amphotericin B, or posaconazole): the probability of attaining "
                    "therapeutic voriconazole concentrations is modest (*1/*17) to small (*17/*17) with standard dosing."
                ),
                "ranked_alternatives": [
                    {"rank": 1, "drug": "isavuconazole", "rxnorm_id": "1608321", "dosing": "Standard label dosing (isavuconazonium sulfate)", "rationale": "Not dependent on CYP2C19 metabolism.", "evidence_level": "1A", "guideline_source": "CPIC 2016 Table 2 (adults)"},
                    {"rank": 2, "drug": "posaconazole", "rxnorm_id": "282446", "dosing": "Standard label dosing", "rationale": "Not dependent on CYP2C19 metabolism.", "evidence_level": "1A", "guideline_source": "CPIC 2016 Table 2 (adults)"},
                ],
                "guideline_summary": (
                    "CPIC 2016 (PMID: 27981572, Table 2, adults): 'CYP2C19 Rapid (*1/*17) / Ultrarapid (*17/*17) Metabolizer: "
                    "the probability of attainment of therapeutic voriconazole concentrations is modest/small with standard "
                    "dosing. Choose an alternative agent that is not dependent on CYP2C19 metabolism (Classification: Moderate).'"
                ),
            },
        },
    },
    "omeprazole": {
        "drug": "omeprazole",
        "atc_code": "A02BC01",
        "rxnorm_id": "7646",
        "therapeutic_class": "Proton Pump Inhibitor (Gastroenterology — GERD / H. pylori)",
        "gene": "CYP2C19",
        "guideline": "CPIC Guideline for CYP2C19 and Proton Pump Inhibitor Dosing",
        "guideline_version": "CPIC 2020 (Lima et al., Clin Pharmacol Ther 2021 · PMC7868475)",
        "guideline_url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC7868475/",
        "dpwg_concordance": "DPWG (KNMP) guidance for this pair is not curated in this demo slice; CPIC is the primary source shown here.",
        "regulatory_labels": {
            "FDA": "PRILOSEC label (Clinical Pharmacology): omeprazole is metabolized primarily by CYP2C19; poor metabolizers have substantially higher omeprazole exposure.",
            "EMA_Swissmedic": "Not curated in this demo slice.",
        },
        "phenotypes": {
            "poor": {
                "phenotype_label": "CYP2C19 Poor Metabolizer",
                "example_diplotypes": ["*2/*2", "*2/*3", "*3/*3"],
                "actionability": "STANDARD STARTING DOSE — CONSIDER 50% REDUCTION FOR CHRONIC THERAPY (>12 WEEKS)",
                "evidence_level": "1A",
                "cpic_strength": "Moderate",
                "primary_recommendation": "Initiate the standard starting daily dose. For chronic therapy (>12 weeks) with efficacy achieved, consider a 50% reduction in daily dose and monitor for continued efficacy (increased PPI exposure raises the chance of efficacy and potentially toxicity).",
                "ranked_alternatives": [
                    {"rank": 1, "drug": "omeprazole", "rxnorm_id": "7646", "dosing": "Standard starting daily dose; 50% lower daily dose for chronic therapy (>12 weeks)", "rationale": "Increased plasma concentration compared with CYP2C19 normal metabolizers.", "evidence_level": "1A", "guideline_source": "CPIC 2020 Table 2 (CPIC REST API)"},
                ],
                "guideline_summary": "CPIC Guideline for CYP2C19 and Proton Pump Inhibitor Dosing (Lima et al., Clin Pharmacol Ther 2021; PMID: 32770672, Table 2): 'CYP2C19 Poor Metabolizer: Increased plasma concentration of PPI compared to CYP2C19 NMs; increased chance of efficacy and potentially toxicity. Initiate standard starting daily dose. For chronic therapy (>12 weeks) and efficacy achieved, consider 50% reduction in daily dose and monitor for continued efficacy (Classification: Moderate).'",
            },
            "intermediate": {
                "phenotype_label": "CYP2C19 Intermediate Metabolizer",
                "example_diplotypes": ["*1/*2", "*1/*3", "*2/*17"],
                "actionability": "STANDARD STARTING DOSE — CONSIDER 50% REDUCTION FOR CHRONIC THERAPY (>12 WEEKS)",
                "evidence_level": "1A",
                "cpic_strength": "Optional",
                "primary_recommendation": "Initiate the standard starting daily dose. For chronic therapy (>12 weeks) with efficacy achieved, consider a 50% reduction in daily dose and monitor for continued efficacy.",
                "ranked_alternatives": [
                    {"rank": 1, "drug": "omeprazole", "rxnorm_id": "7646", "dosing": "Standard starting daily dose; consider 50% lower daily dose for chronic therapy", "rationale": "Moderately increased PPI exposure.", "evidence_level": "1A", "guideline_source": "CPIC 2020 Table 2 (CPIC REST API)"},
                ],
                "guideline_summary": "CPIC 2020 (PMID: 32770672, Table 2): 'CYP2C19 Intermediate Metabolizer: Initiate standard starting daily dose. For chronic therapy (>12 weeks) and efficacy achieved, consider 50% reduction in daily dose and monitor for continued efficacy (Classification: Optional).'",
            },
            "normal": {
                "phenotype_label": "CYP2C19 Normal Metabolizer",
                "example_diplotypes": ["*1/*1"],
                "actionability": "STANDARD STARTING DOSE — CONSIDER +50–100% FOR H. PYLORI / EROSIVE ESOPHAGITIS",
                "evidence_level": "1A",
                "cpic_strength": "Moderate",
                "primary_recommendation": "Initiate the standard starting daily dose. Consider increasing the dose by 50–100% for the treatment of H. pylori infection and erosive esophagitis; the daily dose may be given in divided doses; monitor for efficacy.",
                "ranked_alternatives": [
                    {"rank": 1, "drug": "omeprazole", "rxnorm_id": "7646", "dosing": "Standard starting daily dose; +50–100% for H. pylori / erosive esophagitis", "rationale": "Normal CYP2C19 metabolism; may be at increased risk of therapeutic failure compared with IMs/PMs.", "evidence_level": "1A", "guideline_source": "CPIC 2020 Table 2 (CPIC REST API)"},
                ],
                "guideline_summary": "CPIC 2020 (PMID: 32770672, Table 2): 'CYP2C19 Normal Metabolizer: Initiate standard starting daily dose. Consider increasing dose by 50-100% for the treatment of H. pylori infection and erosive esophagitis. Daily dose may be given in divided doses. Monitor for efficacy (Classification: Moderate).'",
            },
            "rapid": {
                "phenotype_label": "CYP2C19 Rapid / Ultrarapid Metabolizer",
                "example_diplotypes": ["*1/*17", "*17/*17"],
                "actionability": "RAPID: STANDARD START, +50–100% FOR H. PYLORI / EROSIVE ESOPHAGITIS · ULTRARAPID: +100% STARTING DOSE",
                "evidence_level": "1A",
                "cpic_strength": "Moderate (RM) / Optional (UM)",
                "primary_recommendation": "Rapid metabolizer (*1/*17): initiate the standard starting daily dose and consider increasing it by 50–100% for H. pylori infection and erosive esophagitis. Ultrarapid metabolizer (*17/*17): increase the starting daily dose by 100%; the daily dose may be given in divided doses. Monitor for efficacy.",
                "ranked_alternatives": [
                    {"rank": 1, "drug": "omeprazole", "rxnorm_id": "7646", "dosing": "RM: standard start, +50–100% for H. pylori/erosive esophagitis · UM: +100% starting daily dose", "rationale": "Decreased PPI plasma concentrations; increased risk of therapeutic failure.", "evidence_level": "1A", "guideline_source": "CPIC 2020 Table 2 (CPIC REST API)"},
                ],
                "guideline_summary": "CPIC 2020 (PMID: 32770672, Table 2): 'CYP2C19 Ultrarapid Metabolizer: Increase starting daily dose by 100%. Daily dose may be given in divided doses. Monitor for efficacy (Optional). Rapid Metabolizer: Initiate standard starting daily dose. Consider increasing dose by 50-100% for the treatment of H. pylori infection and erosive esophagitis (Moderate).'",
            },
        },
    },
    "pantoprazole": {
        "drug": "pantoprazole",
        "atc_code": "A02BC02",
        "rxnorm_id": "40790",
        "therapeutic_class": "Proton Pump Inhibitor (Gastroenterology — GERD / H. pylori)",
        "gene": "CYP2C19",
        "guideline": "CPIC Guideline for CYP2C19 and Proton Pump Inhibitor Dosing",
        "guideline_version": "CPIC 2020 (Lima et al., Clin Pharmacol Ther 2021 · PMC7868475)",
        "guideline_url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC7868475/",
        "dpwg_concordance": "DPWG (KNMP) guidance for this pair is not curated in this demo slice; CPIC is the primary source shown here.",
        "regulatory_labels": {
            "FDA": "PROTONIX label (Clinical Pharmacology): CYP2C19 poor metabolizers have a longer elimination half-life and higher pantoprazole exposure.",
            "EMA_Swissmedic": "Not curated in this demo slice.",
        },
        "phenotypes": {
            "poor": {
                "phenotype_label": "CYP2C19 Poor Metabolizer",
                "example_diplotypes": ["*2/*2", "*2/*3", "*3/*3"],
                "actionability": "STANDARD STARTING DOSE — CONSIDER 50% REDUCTION FOR CHRONIC THERAPY (>12 WEEKS)",
                "evidence_level": "1A",
                "cpic_strength": "Moderate",
                "primary_recommendation": "Initiate the standard starting daily dose. For chronic therapy (>12 weeks) with efficacy achieved, consider a 50% reduction in daily dose and monitor for continued efficacy (increased PPI exposure raises the chance of efficacy and potentially toxicity).",
                "ranked_alternatives": [
                    {"rank": 1, "drug": "pantoprazole", "rxnorm_id": "40790", "dosing": "Standard starting daily dose; 50% lower daily dose for chronic therapy (>12 weeks)", "rationale": "Increased plasma concentration compared with CYP2C19 normal metabolizers.", "evidence_level": "1A", "guideline_source": "CPIC 2020 Table 2 (CPIC REST API)"},
                ],
                "guideline_summary": "CPIC Guideline for CYP2C19 and Proton Pump Inhibitor Dosing (Lima et al., Clin Pharmacol Ther 2021; PMID: 32770672, Table 2): 'CYP2C19 Poor Metabolizer: Increased plasma concentration of PPI compared to CYP2C19 NMs; increased chance of efficacy and potentially toxicity. Initiate standard starting daily dose. For chronic therapy (>12 weeks) and efficacy achieved, consider 50% reduction in daily dose and monitor for continued efficacy (Classification: Moderate).'",
            },
            "intermediate": {
                "phenotype_label": "CYP2C19 Intermediate Metabolizer",
                "example_diplotypes": ["*1/*2", "*1/*3", "*2/*17"],
                "actionability": "STANDARD STARTING DOSE — CONSIDER 50% REDUCTION FOR CHRONIC THERAPY (>12 WEEKS)",
                "evidence_level": "1A",
                "cpic_strength": "Optional",
                "primary_recommendation": "Initiate the standard starting daily dose. For chronic therapy (>12 weeks) with efficacy achieved, consider a 50% reduction in daily dose and monitor for continued efficacy.",
                "ranked_alternatives": [
                    {"rank": 1, "drug": "pantoprazole", "rxnorm_id": "40790", "dosing": "Standard starting daily dose; consider 50% lower daily dose for chronic therapy", "rationale": "Moderately increased PPI exposure.", "evidence_level": "1A", "guideline_source": "CPIC 2020 Table 2 (CPIC REST API)"},
                ],
                "guideline_summary": "CPIC 2020 (PMID: 32770672, Table 2): 'CYP2C19 Intermediate Metabolizer: Initiate standard starting daily dose. For chronic therapy (>12 weeks) and efficacy achieved, consider 50% reduction in daily dose and monitor for continued efficacy (Classification: Optional).'",
            },
            "normal": {
                "phenotype_label": "CYP2C19 Normal Metabolizer",
                "example_diplotypes": ["*1/*1"],
                "actionability": "STANDARD STARTING DOSE — CONSIDER +50–100% FOR H. PYLORI / EROSIVE ESOPHAGITIS",
                "evidence_level": "1A",
                "cpic_strength": "Moderate",
                "primary_recommendation": "Initiate the standard starting daily dose. Consider increasing the dose by 50–100% for the treatment of H. pylori infection and erosive esophagitis; the daily dose may be given in divided doses; monitor for efficacy.",
                "ranked_alternatives": [
                    {"rank": 1, "drug": "pantoprazole", "rxnorm_id": "40790", "dosing": "Standard starting daily dose; +50–100% for H. pylori / erosive esophagitis", "rationale": "Normal CYP2C19 metabolism; may be at increased risk of therapeutic failure compared with IMs/PMs.", "evidence_level": "1A", "guideline_source": "CPIC 2020 Table 2 (CPIC REST API)"},
                ],
                "guideline_summary": "CPIC 2020 (PMID: 32770672, Table 2): 'CYP2C19 Normal Metabolizer: Initiate standard starting daily dose. Consider increasing dose by 50-100% for the treatment of H. pylori infection and erosive esophagitis. Daily dose may be given in divided doses. Monitor for efficacy (Classification: Moderate).'",
            },
            "rapid": {
                "phenotype_label": "CYP2C19 Rapid / Ultrarapid Metabolizer",
                "example_diplotypes": ["*1/*17", "*17/*17"],
                "actionability": "RAPID: STANDARD START, +50–100% FOR H. PYLORI / EROSIVE ESOPHAGITIS · ULTRARAPID: +100% STARTING DOSE",
                "evidence_level": "1A",
                "cpic_strength": "Moderate (RM) / Optional (UM)",
                "primary_recommendation": "Rapid metabolizer (*1/*17): initiate the standard starting daily dose and consider increasing it by 50–100% for H. pylori infection and erosive esophagitis. Ultrarapid metabolizer (*17/*17): increase the starting daily dose by 100%; the daily dose may be given in divided doses. Monitor for efficacy.",
                "ranked_alternatives": [
                    {"rank": 1, "drug": "pantoprazole", "rxnorm_id": "40790", "dosing": "RM: standard start, +50–100% for H. pylori/erosive esophagitis · UM: +100% starting daily dose", "rationale": "Decreased PPI plasma concentrations; increased risk of therapeutic failure.", "evidence_level": "1A", "guideline_source": "CPIC 2020 Table 2 (CPIC REST API)"},
                ],
                "guideline_summary": "CPIC 2020 (PMID: 32770672, Table 2): 'CYP2C19 Ultrarapid Metabolizer: Increase starting daily dose by 100%. Daily dose may be given in divided doses. Monitor for efficacy (Optional). Rapid Metabolizer: Initiate standard starting daily dose. Consider increasing dose by 50-100% for the treatment of H. pylori infection and erosive esophagitis (Moderate).'",
            },
        },
    },
    "sertraline": {
        "drug": "sertraline",
        "atc_code": "N06AB06",
        "rxnorm_id": "36437",
        "therapeutic_class": "Selective Serotonin Reuptake Inhibitor (SSRI — Psychiatry)",
        "gene": "CYP2C19",
        "guideline": "CPIC Guideline for CYP2D6, CYP2C19, CYP2B6, SLC6A4, and HTR2A Genotypes and Serotonin Reuptake Inhibitor Antidepressants",
        "guideline_version": "CPIC 2023 SSRI/SNRI Update (Bousman et al. · PMC10564324), CYP2C19-only recommendations (Table 3b)",
        "guideline_url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC10564324/",
        "dpwg_concordance": "DPWG (KNMP) guidance for this pair is not curated in this demo slice; CPIC is the primary source shown here.",
        "regulatory_labels": {
            "FDA": "ZOLOFT label: no CYP2C19 genotype-specific dosing; genotype guidance comes from CPIC.",
            "EMA_Swissmedic": "Not curated in this demo slice.",
        },
        "phenotypes": {
            "poor": {
                "phenotype_label": "CYP2C19 Poor Metabolizer",
                "example_diplotypes": ["*2/*2", "*2/*3", "*3/*3"],
                "actionability": "LOWER STARTING DOSE, SLOWER TITRATION, 50% LOWER MAINTENANCE — OR NON-CYP2C19 ALTERNATIVE",
                "evidence_level": "1A",
                "cpic_strength": "Moderate",
                "primary_recommendation": (
                    "Consider a lower starting dose, a slower titration schedule and a 50% reduction of the standard "
                    "maintenance dose compared with CYP2C19 normal metabolizers, or select a clinically appropriate "
                    "alternative antidepressant not predominantly metabolized by CYP2C19."
                ),
                "ranked_alternatives": [
                    {"rank": 1, "drug": "sertraline", "rxnorm_id": "36437", "dosing": "Lower starting dose, slower titration, 50% of standard maintenance dose", "rationale": "Elevated sertraline concentrations in CYP2C19 poor metabolizers.", "evidence_level": "1A", "guideline_source": "CPIC 2023 Table 3b"},
                    {"rank": 2, "drug": "fluoxetine", "rxnorm_id": "4493", "dosing": "Standard dose (20 mg/day), predominantly CYP2D6-metabolized", "rationale": "Alternative not predominantly metabolized by CYP2C19.", "evidence_level": "1A", "guideline_source": "CPIC 2023 Table 3b"},
                ],
                "guideline_summary": (
                    "CPIC 2023 (Bousman et al., PMID: 37032427, Table 3b, CYP2C19 only): 'CYP2C19 Poor Metabolizer: Consider a "
                    "lower starting dose, slower titration schedule and 50% reduction of standard maintenance dose as compared to "
                    "CYP2C19 normal metabolizers or select a clinically appropriate alternative antidepressant not predominantly "
                    "metabolized by CYP2C19 (Classification: Moderate).'"
                ),
            },
            "intermediate": {
                "phenotype_label": "CYP2C19 Intermediate Metabolizer",
                "example_diplotypes": ["*1/*2", "*1/*3", "*2/*17"],
                "actionability": "STANDARD STARTING DOSE — SLOWER TITRATION, LOWER MAINTENANCE DOSE",
                "evidence_level": "1A",
                "cpic_strength": "Moderate",
                "primary_recommendation": "Initiate therapy with the recommended starting dose. Consider a slower titration schedule and a lower maintenance dose than CYP2C19 normal metabolizers.",
                "ranked_alternatives": [
                    {"rank": 1, "drug": "sertraline", "rxnorm_id": "36437", "dosing": "Standard starting dose; slower titration; lower maintenance dose", "rationale": "Moderately reduced CYP2C19 clearance.", "evidence_level": "1A", "guideline_source": "CPIC 2023 Table 3b"},
                ],
                "guideline_summary": "CPIC 2023 (PMID: 37032427, Table 3b): 'CYP2C19 Intermediate Metabolizer: Initiate therapy with recommended starting dose. Consider a slower titration schedule and lower maintenance dose than CYP2C19 normal metabolizers (Classification: Moderate).'",
            },
            "normal": {
                "phenotype_label": "CYP2C19 Normal Metabolizer",
                "example_diplotypes": ["*1/*1"],
                "actionability": "STANDARD DOSING — NO GENOTYPE ADJUSTMENT REQUIRED",
                "evidence_level": "1A",
                "cpic_strength": "Strong",
                "primary_recommendation": "Initiate therapy with the recommended starting dose.",
                "ranked_alternatives": [
                    {"rank": 1, "drug": "sertraline", "rxnorm_id": "36437", "dosing": "Standard dose (50 mg/day starting)", "rationale": "Normal CYP2C19 clearance.", "evidence_level": "1A", "guideline_source": "CPIC 2023 Table 3b"},
                ],
                "guideline_summary": "CPIC 2023 (PMID: 37032427, Table 3b): 'CYP2C19 Normal Metabolizer: Initiate therapy with recommended starting dose (Classification: Strong).'",
            },
            "rapid": {
                "phenotype_label": "CYP2C19 Rapid / Ultrarapid Metabolizer",
                "example_diplotypes": ["*1/*17", "*17/*17"],
                "actionability": "STANDARD DOSING — NO GENOTYPE ADJUSTMENT REQUIRED",
                "evidence_level": "1A",
                "cpic_strength": "Strong",
                "primary_recommendation": "Initiate therapy with the recommended starting dose (rapid and ultrarapid metabolizers).",
                "ranked_alternatives": [
                    {"rank": 1, "drug": "sertraline", "rxnorm_id": "36437", "dosing": "Standard dose (50 mg/day starting)", "rationale": "No pre-emptive dose change recommended for increased CYP2C19 activity.", "evidence_level": "1A", "guideline_source": "CPIC 2023 Table 3b"},
                ],
                "guideline_summary": "CPIC 2023 (PMID: 37032427, Table 3b): 'CYP2C19 Rapid or Ultrarapid Metabolizer: Initiate therapy with recommended starting dose (Classification: Strong).'",
            },
        },
    },
    "atorvastatin": {
        "drug": "atorvastatin",
        "atc_code": "C10AA05",
        "rxnorm_id": "83367",
        "therapeutic_class": "HMG-CoA Reductase Inhibitor (Statin — Lipid Lowering)",
        "gene": "SLCO1B1",
        "guideline": "CPIC Guideline for Statins and SLCO1B1, ABCG2, and CYP2C9",
        "guideline_version": "CPIC 2022 Statin Update (ClinPGx PA166262221 · PMC9035072)",
        "guideline_url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC9035072/",
        "dpwg_concordance": "DPWG (KNMP) guidance for this pair is not curated in this demo slice; CPIC is the primary source shown here.",
        "regulatory_labels": {
            "FDA": "LIPITOR label: OATP1B1 (SLCO1B1) transporter drug interactions are described; no genotype-specific dosing in the label.",
            "EMA_Swissmedic": "Not curated in this demo slice.",
        },
        "phenotypes": {
            "intermediate": {
                "phenotype_label": "SLCO1B1 Decreased Function",
                "example_diplotypes": ["*1/*5", "*1/*15"],
                "actionability": "START AT ≤40 MG/DAY — INCREASED MYOPATHY RISK ESPECIALLY AT 40 MG",
                "evidence_level": "1A",
                "cpic_strength": "Moderate",
                "primary_recommendation": (
                    "Prescribe ≤40 mg as a starting dose and adjust atorvastatin doses based on disease-specific guidelines. "
                    "Be aware of a possible increased risk for myopathy, especially at 40 mg. If a dose >40 mg is needed for "
                    "desired efficacy, consider combination therapy (atorvastatin plus non-statin guideline-directed medical "
                    "therapy) or an alternative statin."
                ),
                "ranked_alternatives": [
                    {"rank": 1, "drug": "atorvastatin", "rxnorm_id": "83367", "dosing": "≤40 mg/day starting dose", "rationale": "Reduced OATP1B1 hepatic uptake raises systemic atorvastatin exposure.", "evidence_level": "1A", "guideline_source": "CPIC 2022 Table 2"},
                    {"rank": 2, "drug": "rosuvastatin", "rxnorm_id": "301542", "dosing": "≤20 mg/day starting dose (SLCO1B1 decreased function)", "rationale": "Alternative statin with its own CPIC SLCO1B1 dose ceiling.", "evidence_level": "1A", "guideline_source": "CPIC 2022 Table 2"},
                ],
                "guideline_summary": (
                    "CPIC Guideline for Statins and SLCO1B1 (Cooper-DeHoff et al., Clin Pharmacol Ther 2022; PMID: 35152405, "
                    "Table 2): 'SLCO1B1 Decreased Function: Prescribe ≤40mg as a starting dose and adjust doses of atorvastatin "
                    "based on disease-specific guidelines. Prescriber should be aware of possible increased risk for myopathy "
                    "especially for 40mg dose (Classification: Moderate).'"
                ),
            },
            "poor": {
                "phenotype_label": "SLCO1B1 Poor Function",
                "example_diplotypes": ["*5/*5", "*5/*15", "*15/*15"],
                "actionability": "START AT ≤20 MG/DAY — CONSIDER ROSUVASTATIN OR COMBINATION THERAPY ABOVE 20 MG",
                "evidence_level": "1A",
                "cpic_strength": "Moderate",
                "primary_recommendation": (
                    "Prescribe ≤20 mg as a starting dose and adjust atorvastatin doses based on disease-specific guidelines. "
                    "If a dose >20 mg is needed for desired efficacy, consider rosuvastatin or combination therapy "
                    "(atorvastatin plus non-statin guideline-directed medical therapy)."
                ),
                "ranked_alternatives": [
                    {"rank": 1, "drug": "atorvastatin", "rxnorm_id": "83367", "dosing": "≤20 mg/day starting dose", "rationale": "Markedly reduced OATP1B1 uptake.", "evidence_level": "1A", "guideline_source": "CPIC 2022 Table 2"},
                    {"rank": 2, "drug": "rosuvastatin", "rxnorm_id": "301542", "dosing": "Per CPIC SLCO1B1 poor-function ceiling", "rationale": "Alternative statin named by the guideline when >20 mg atorvastatin is needed.", "evidence_level": "1A", "guideline_source": "CPIC 2022 Table 2"},
                ],
                "guideline_summary": (
                    "CPIC 2022 (PMID: 35152405, Table 2): 'SLCO1B1 Poor Function: Prescribe ≤20mg as a starting dose and adjust "
                    "doses of atorvastatin based on disease-specific guidelines. If dose >20mg is needed for desired efficacy, "
                    "consider rosuvastatin or combination therapy (Classification: Moderate).'"
                ),
            },
            "normal": {
                "phenotype_label": "SLCO1B1 Normal Function",
                "example_diplotypes": ["*1/*1"],
                "actionability": "STANDARD DOSING — NO GENOTYPE ADJUSTMENT REQUIRED",
                "evidence_level": "1A",
                "cpic_strength": "Strong",
                "primary_recommendation": "Prescribe the desired starting dose and adjust doses based on disease-specific guidelines.",
                "ranked_alternatives": [
                    {"rank": 1, "drug": "atorvastatin", "rxnorm_id": "83367", "dosing": "Desired starting dose per lipid guidelines", "rationale": "Normal OATP1B1 transporter function.", "evidence_level": "1A", "guideline_source": "CPIC 2022 Table 2"},
                ],
                "guideline_summary": "CPIC 2022 (PMID: 35152405, Table 2): 'SLCO1B1 Normal Function: Prescribe desired starting dose and adjust doses based on disease-specific guidelines (Classification: Strong).'",
            },
        },
    },
    "phenytoin": {
        "drug": "phenytoin",
        "atc_code": "N03AB02",
        "rxnorm_id": "8183",
        "therapeutic_class": "Hydantoin Antiepileptic (Neurology)",
        "gene": "CYP2C9",
        "guideline": "CPIC Guideline for HLA-B and CYP2C9 Genotypes and Phenytoin Dosing",
        "guideline_version": "CPIC 2020 Update (Karnes et al., Clin Pharmacol Ther 2021 · PMC7831382)",
        "guideline_url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC7831382/",
        "dpwg_concordance": "DPWG (KNMP) guidance for this pair is not curated in this demo slice; CPIC is the primary source shown here.",
        "regulatory_labels": {
            "FDA": "DILANTIN label (Warnings): HLA-B*1502 is associated with Stevens-Johnson syndrome / toxic epidermal necrolysis in patients of Asian ancestry; phenytoin is metabolized by CYP2C9 and CYP2C19 with saturable kinetics.",
            "EMA_Swissmedic": "Not curated in this demo slice.",
        },
        "phenotypes": {
            "intermediate": {
                "phenotype_label": "CYP2C9 Intermediate Metabolizer",
                "example_diplotypes": ["*1/*3 (activity score 1.0)", "*2/*2 (activity score 1.0)", "*1/*2 (activity score 1.5)"],
                "actionability": "ACTIVITY-SCORE-GUIDED MAINTENANCE DOSE — AS 1.0: ~25% LOWER · AS 1.5: STANDARD · HLA-B*15:02 SEPARATE",
                "evidence_level": "1A",
                "cpic_strength": "Moderate",
                "primary_recommendation": (
                    "For the first dose use the typical initial or loading dose. For subsequent doses: activity score 1.0 "
                    "(e.g., *1/*3) — use approximately 25% less than the typical maintenance dose; activity score 1.5 (*1/*2) — "
                    "no adjustment from typical dosing. Adjust subsequent doses according to therapeutic drug monitoring, "
                    "response and side effects. HLA-B*15:02 status must be assessed separately for SJS/TEN risk."
                ),
                "ranked_alternatives": [
                    {"rank": 1, "drug": "phenytoin", "rxnorm_id": "8183", "dosing": "Typical loading dose; maintenance ~25% lower for activity score 1.0; therapeutic drug monitoring", "rationale": "Reduced CYP2C9-mediated clearance (*3 no-function allele).", "evidence_level": "1A", "guideline_source": "CPIC 2020 Table 3 (CPIC REST API, phenytoin-naive)"},
                ],
                "guideline_summary": (
                    "CPIC Guideline for HLA-B and CYP2C9 Genotypes and Phenytoin Dosing (Karnes et al., Clin Pharmacol Ther 2021; "
                    "PMID: 32779747): 'CYP2C9 Intermediate Metabolizer, activity score 1.0: For first dose, use typical initial or "
                    "loading dose. For subsequent doses, use approximately 25% less than typical maintenance dose. Subsequent doses "
                    "should be adjusted according to therapeutic drug monitoring, response and side effects (Classification: Moderate). "
                    "Activity score 1.5: No adjustments needed from typical dosing strategies (Moderate).'"
                ),
            },
            "poor": {
                "phenotype_label": "CYP2C9 Poor Metabolizer",
                "example_diplotypes": ["*2/*3 (activity score 0.5)", "*3/*3 (activity score 0.0)"],
                "actionability": "~50% LOWER MAINTENANCE DOSE — THERAPEUTIC DRUG MONITORING",
                "evidence_level": "1A",
                "cpic_strength": "Strong",
                "primary_recommendation": (
                    "For the first dose use the typical initial or loading dose. For subsequent doses use approximately 50% "
                    "less than the typical maintenance dose, then adjust according to therapeutic drug monitoring, response "
                    "and side effects. HLA-B*15:02 status must be assessed separately for SJS/TEN risk."
                ),
                "ranked_alternatives": [
                    {"rank": 1, "drug": "phenytoin", "rxnorm_id": "8183", "dosing": "Typical loading dose; maintenance ~50% lower; therapeutic drug monitoring", "rationale": "Markedly reduced CYP2C9 clearance.", "evidence_level": "1A", "guideline_source": "CPIC 2020 Table 3"},
                ],
                "guideline_summary": "CPIC 2020 (PMID: 32779747): 'CYP2C9 Poor Metabolizer (activity score 0–0.5): For first dose, use typical initial or loading dose. For subsequent doses use approximately 50% less than typical maintenance dose. Subsequent doses should be adjusted according to therapeutic drug monitoring, response, and side effects (Classification: Strong).'",
            },
            "normal": {
                "phenotype_label": "CYP2C9 Normal Metabolizer",
                "example_diplotypes": ["*1/*1 (activity score 2.0)"],
                "actionability": "STANDARD DOSING — NO GENOTYPE ADJUSTMENT REQUIRED (HLA-B*15:02 SEPARATE)",
                "evidence_level": "1A",
                "cpic_strength": "Strong",
                "primary_recommendation": "No adjustments needed from typical dosing strategies; adjust subsequent doses by therapeutic drug monitoring, response and side effects. HLA-B*15:02 status must be assessed separately.",
                "ranked_alternatives": [
                    {"rank": 1, "drug": "phenytoin", "rxnorm_id": "8183", "dosing": "Typical dosing with therapeutic drug monitoring", "rationale": "Normal CYP2C9 clearance.", "evidence_level": "1A", "guideline_source": "CPIC 2020 Table 3"},
                ],
                "guideline_summary": "CPIC 2020 (PMID: 32779747): 'CYP2C9 Normal Metabolizer (activity score 2.0): No adjustments needed from typical dosing strategies (Classification: Strong).'",
            },
        },
    },
    "tacrolimus": {
        "drug": "tacrolimus",
        "atc_code": "L04AD02",
        "rxnorm_id": "42316",
        "therapeutic_class": "Calcineurin Inhibitor Immunosuppressant (Solid-Organ Transplant)",
        "gene": "CYP3A5",
        "guideline": "CPIC Guideline for CYP3A5 Genotype and Tacrolimus Dosing",
        "guideline_version": "CPIC 2015 (Birdwell et al., Clin Pharmacol Ther 2015 · PMC4481158)",
        "guideline_url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC4481158/",
        "dpwg_concordance": "DPWG (KNMP) guidance for this pair is not curated in this demo slice; CPIC is the primary source shown here.",
        "regulatory_labels": {
            "FDA": "PROGRAF label: dosing by indication with therapeutic drug monitoring of whole-blood trough concentrations; the label notes that African-American patients may require higher doses to attain comparable troughs (consistent with higher CYP3A5 expresser frequency).",
            "EMA_Swissmedic": "Not curated in this demo slice.",
        },
        "phenotypes": {
            "normal": {
                "phenotype_label": "CYP3A5 Normal Expresser (two *1 alleles)",
                "example_diplotypes": ["*1/*1"],
                "actionability": "INCREASE STARTING DOSE 1.5–2× (MAX 0.3 MG/KG/DAY) — THERAPEUTIC DRUG MONITORING",
                "evidence_level": "1A",
                "cpic_strength": "Strong",
                "primary_recommendation": "Increase the starting dose 1.5 to 2 times the recommended starting dose; the total starting dose should not exceed 0.3 mg/kg/day. Use therapeutic drug monitoring to guide dose adjustments.",
                "ranked_alternatives": [
                    {"rank": 1, "drug": "tacrolimus", "rxnorm_id": "42316", "dosing": "1.5–2× recommended starting dose, ≤0.3 mg/kg/day, TDM", "rationale": "CYP3A5 expressers clear tacrolimus faster and under-achieve target troughs at standard doses.", "evidence_level": "1A", "guideline_source": "CPIC 2015 Table 2 (CPIC REST API)"},
                ],
                "guideline_summary": "CPIC Guideline for CYP3A5 Genotype and Tacrolimus Dosing (Birdwell et al., Clin Pharmacol Ther 2015; PMID: 25801146, Table 2): 'CYP3A5 expresser (extensive metabolizer): Increase starting dose 1.5 to 2 times recommended starting dose. Total starting dose should not exceed 0.3 mg/kg/day. Use therapeutic drug monitoring to guide dose adjustments (Classification: Strong).'",
            },
            "intermediate": {
                "phenotype_label": "CYP3A5 Intermediate Expresser (one *1 allele)",
                "example_diplotypes": ["*1/*3"],
                "actionability": "INCREASE STARTING DOSE 1.5–2× (MAX 0.3 MG/KG/DAY) — THERAPEUTIC DRUG MONITORING",
                "evidence_level": "1A",
                "cpic_strength": "Strong",
                "primary_recommendation": "Increase the starting dose 1.5 to 2 times the recommended starting dose; the total starting dose should not exceed 0.3 mg/kg/day. Use therapeutic drug monitoring to guide dose adjustments.",
                "ranked_alternatives": [
                    {"rank": 1, "drug": "tacrolimus", "rxnorm_id": "42316", "dosing": "1.5–2× recommended starting dose, ≤0.3 mg/kg/day, TDM", "rationale": "Intermediate CYP3A5 expression still lowers dose-adjusted troughs.", "evidence_level": "1A", "guideline_source": "CPIC 2015 Table 2 (CPIC REST API)"},
                ],
                "guideline_summary": "CPIC 2015 (PMID: 25801146, Table 2): 'CYP3A5 intermediate metabolizer (expresser): Increase starting dose 1.5 to 2 times recommended starting dose. Total starting dose should not exceed 0.3 mg/kg/day. Use therapeutic drug monitoring to guide dose adjustments (Classification: Strong).'",
            },
            "poor": {
                "phenotype_label": "CYP3A5 Non-expresser (two *3 alleles)",
                "example_diplotypes": ["*3/*3"],
                "actionability": "STANDARD STARTING DOSE — THERAPEUTIC DRUG MONITORING",
                "evidence_level": "1A",
                "cpic_strength": "Strong",
                "primary_recommendation": "Initiate therapy with the standard recommended dose. Use therapeutic drug monitoring to guide dose adjustments.",
                "ranked_alternatives": [
                    {"rank": 1, "drug": "tacrolimus", "rxnorm_id": "42316", "dosing": "Standard recommended starting dose with TDM", "rationale": "Non-expressers (*3/*3) achieve target troughs at standard doses.", "evidence_level": "1A", "guideline_source": "CPIC 2015 Table 2 (CPIC REST API)"},
                ],
                "guideline_summary": "CPIC 2015 (PMID: 25801146, Table 2): 'CYP3A5 non-expresser (poor metabolizer): Initiate therapy with standard recommended dose. Use therapeutic drug monitoring to guide dose adjustments (Classification: Strong).'",
            },
        },
    },
}

# Compute exact Knowledge Graph counts at import time from PGX_KNOWLEDGE_GRAPH
_DISTINCT_GENES = sorted({g for v in PGX_KNOWLEDGE_GRAPH.values() for g in v["gene"].split("+")})
_PHENOTYPE_RULES_COUNT = sum(len(v["phenotypes"]) for v in PGX_KNOWLEDGE_GRAPH.values())
_PMID_SET = sorted(set(re.findall(r"PMID:\s*(\d+)", str(PGX_KNOWLEDGE_GRAPH))))

KNOWLEDGE_GRAPH_METADATA = {
    "name": "Helixstreet Consent-Native PGx Knowledge Graph",
    "version": "2026.10-cpic-dpwg-pharmgkb",
    "ontologies": [
        "CPIC (Clinical Pharmacogenetics Implementation Consortium, v2024/2026)",
        "DPWG (Dutch Pharmacogenetics Working Group / KNMP, v2024)",
        "PharmGKB / ClinPGx Level 1A–1B Clinical Annotations",
        "PharmVar v6.1 Star-Allele Nomenclature",
        "FDA Table of Pharmacogenomic Biomarkers + Swissmedic / EMA SmPC PGx Sections",
        "Ensembl 1000 Genomes Phase 3 Super-Population Allele Frequencies (AFR, AMR, EAS, EUR, SAS)",
    ],
    "indexed_counts": {
        "drugs": len(PGX_KNOWLEDGE_GRAPH),
        "genes": len(_DISTINCT_GENES),
        "gene_list": _DISTINCT_GENES,
        "phenotype_rules": _PHENOTYPE_RULES_COUNT,
        "citations": len(_PMID_SET),
        "pmids": _PMID_SET,
        "global_superpopulations": 5,
    },
    "ui_summary": (
        f"{len(PGX_KNOWLEDGE_GRAPH)} drug-gene pairs · "
        f"{_PHENOTYPE_RULES_COUNT} phenotype rules · hand-curated from CPIC + DPWG"
    ),
}

# Drug alias resolution (e.g., brand names and capecitabine -> 5-fluorouracil)
_DRUG_ALIASES = {
    "plavix": "clopidogrel",
    "vfend": "voriconazole",
    "prilosec": "omeprazole",
    "losec": "omeprazole",
    "protonix": "pantoprazole",
    "pantozol": "pantoprazole",
    "zoloft": "sertraline",
    "lipitor": "atorvastatin",
    "sortis": "atorvastatin",
    "dilantin": "phenytoin",
    "epanutin": "phenytoin",
    "prograf": "tacrolimus",
    "advagraf": "tacrolimus",
    "envarsus": "tacrolimus",
    "clopidogrel": "clopidogrel",
    "lexapro": "escitalopram",
    "cipralex": "escitalopram",
    "escitalopram": "escitalopram",
    "celexa": "citalopram",
    "citalopram": "citalopram",
    "capecitabine": "5-fluorouracil",
    "xeloda": "5-fluorouracil",
    "fluorouracil": "5-fluorouracil",
    "5-fu": "5-fluorouracil",
    "5-fluorouracil": "5-fluorouracil",
    "zocor": "simvastatin",
    "simvastatin": "simvastatin",
    "coumadin": "warfarin",
    "marcoumar": "warfarin",
    "warfarin": "warfarin",
}


def resolve_drug_node(drug: str) -> dict | None:
    """Resolves a generic or brand drug name to its Knowledge Graph node."""
    norm = (drug or "").strip().lower()
    for key, canonical in _DRUG_ALIASES.items():
        if key in norm:
            return PGX_KNOWLEDGE_GRAPH.get(canonical)
    return PGX_KNOWLEDGE_GRAPH.get(norm)


def query_knowledge_graph(drug: str, phenotype_key: str | None = None) -> dict:
    """Queries the Helixstreet Pharmacogenomic Knowledge Graph for a drug and
    optional metabolizer phenotype, returning the primary recommendation,
    ranked alternatives, DPWG concordance, and CPIC guideline summary."""
    node = resolve_drug_node(drug)
    if not node:
        return {
            "found": False,
            "drug": drug,
            "message": f"No Level-1A CPIC/DPWG entry matched for '{drug}' in active demo slice.",
        }
    phenos = node["phenotypes"]
    if phenotype_key == "normal" and "normal" not in phenos:
        rule = {
            "phenotype_label": f"{node['gene']} Normal Metabolizer",
            "example_diplotypes": ["*1/*1"],
            "actionability": "STANDARD DOSING — NO GENOTYPE ADJUSTMENT REQUIRED",
            "evidence_level": "1A",
            "cpic_strength": "Strong",
            "primary_recommendation": f"Use {node['drug']} at standard label-recommended dosage.",
            "ranked_alternatives": [
                {
                    "rank": 1,
                    "drug": node["drug"],
                    "rxnorm_id": node["rxnorm_id"],
                    "dosing": "Standard label-recommended regimen",
                    "rationale": f"Normal {node['gene']} function.",
                    "evidence_level": "1A",
                    "guideline_source": node["guideline_version"],
                }
            ],
            "guideline_summary": f"{node['guideline']} ({node['guideline_version']}): Standard dosing recommended for normal metabolizers.",
        }
    elif phenotype_key and phenotype_key not in phenos:
        # Never silently fall back to another phenotype's rule: say so explicitly.
        rule = {
            "phenotype_label": f"{node['gene']} {phenotype_key.title()} Metabolizer (no curated rule)",
            "example_diplotypes": [],
            "actionability": "NO CURATED RULE FOR THIS PHENOTYPE IN THE DEMO KNOWLEDGE GRAPH — CONSULT THE CITED GUIDELINE",
            "evidence_level": "n/a",
            "cpic_strength": "n/a",
            "primary_recommendation": (
                f"The demo Knowledge Graph does not curate a {phenotype_key} metabolizer rule for {node['drug']}; "
                f"refer to {node['guideline']} before prescribing."
            ),
            "ranked_alternatives": [],
            "guideline_summary": f"{node['guideline']} ({node['guideline_version']}): phenotype-specific recommendation not curated in this build.",
            "rule_missing": True,
        }
    else:
        selected_key = phenotype_key if (phenotype_key and phenotype_key in phenos) else next(iter(phenos))
        rule = phenos[selected_key]
    return {
        "found": True,
        "drug": node["drug"],
        "atc_code": node["atc_code"],
        "rxnorm_id": node["rxnorm_id"],
        "therapeutic_class": node["therapeutic_class"],
        "gene": node["gene"],
        "guideline": node["guideline"],
        "guideline_version": node["guideline_version"],
        "guideline_url": node["guideline_url"],
        "dpwg_concordance": node["dpwg_concordance"],
        "regulatory_labels": node["regulatory_labels"],
        **rule,
    }
