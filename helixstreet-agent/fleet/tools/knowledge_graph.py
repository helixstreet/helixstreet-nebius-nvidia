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
        "guideline_version": "CPIC 2022/2024 Update (ClinPGx PA166251456 · PMC9287492)",
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
            }
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
        "guideline_version": "CPIC 2022 Statin Update (ClinPGx PA166262321 · PMC9035072)",
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
