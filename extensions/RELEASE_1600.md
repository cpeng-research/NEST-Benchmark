# NEST Additions: 25 October 2026

This batch adds 100 complete source forms to the [1,500-template inventory](RELEASE_1500.md).
The combined local inventory contains 1,600 templates.

## Coverage

| Language | Added | Combined |
| --- | ---: | ---: |
| English | 0 | 449 |
| Chinese | 0 | 431 |
| French | 55 | 360 |
| Spanish | 45 | 360 |
| **Total** | **100** | **1,600** |

| Language | GovPublic | Business | Finance | Healthcare | Education | WorkplaceHR | Total |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| en | 97 | 95 | 98 | 53 | 40 | 66 | 449 |
| zh | 23 | 107 | 41 | 23 | 32 | 205 | 431 |
| fr | 61 | 58 | 57 | 69 | 74 | 41 | 360 |
| es | 59 | 53 | 61 | 76 | 78 | 33 | 360 |

## Structure

| Complexity | Added | Combined |
| --- | ---: | ---: |
| Level 1 | 20 | 109 |
| Level 2 | 23 | 261 |
| Level 3 | 57 | 1230 |

Complexity follows the existing cell-type classification in `table2_structural_statistics.py`.

## Files and Use

Batch: [2026-10-25-multilingual-v0.1](2026-10-25-multilingual-v0.1/README.md).

- Empty templates: `workflow/0-html_template/data_<language>/<ID>.html`.
- Structural annotations and synthetic filled instances: workflow stages 1-3.
- Contexts, placeholder templates and metadata: workflow stages 4-6.
- Sources, editions and retrieval dates: `SOURCE.md`, `data/provenance/`, `data/annotations/`.
- File inventory: `manifest.json` and `SHA256SUMS`.

The existing shared workflow entry point and task metrics apply. A multipage source form
is one sample. Stages 7-9 and model outputs are not part of this increment.

## Sample Index

| Language/ID | Domain | Source form | Pages | Fields |
| --- | --- | --- | ---: | ---: |
| es/800 | Education | Cambio de modalidad de dedicación a tiempo parcial | 2 | 27 |
| es/801 | Education | Solicitud de convocatoria adicional | 2 | 11 |
| es/802 | Education | Solicitud de reingreso a estudios de máster | 1 | 23 |
| es/803 | Education | Declaración jurada de autoría del Trabajo Fin de Grado | 1 | 5 |
| es/804 | Education | Declaración responsable sobre localidad de nacimiento para título oficial | 1 | 3 |
| es/805 | Education | Justificante de asistencia a una actividad académica | 1 | 13 |
| es/806 | Education | Autorización para realizar gestiones en secretarías universitarias | 1 | 7 |
| es/807 | Education | Recurso de alzada en materia académica | 1 | 31 |
| es/808 | Education | Orden de preferencia de líneas y temáticas del Trabajo Fin de Grado | 1 | 7 |
| es/809 | Education | Alteración de matrícula de máster | 1 | 49 |
| es/810 | Education | Solicitud de defensa pública del Trabajo Fin de Grado | 1 | 7 |
| es/811 | Education | Solicitud de preadmisión de estudiante de libre movilidad | 2 | 23 |
| es/812 | Education | Solicitud de evaluación por incidencia | 2 | 43 |
| es/813 | Education | Alegaciones o peticiones sobre revocación de beca de estudio | 2 | 21 |
| es/814 | Education | Visto bueno de la persona tutora para el Trabajo Fin de Grado | 1 | 5 |
| es/815 | Education | Autorización de publicación del Trabajo Fin de Grado en la web de la Facultad | 1 | 5 |
| es/816 | Education | Petición de material deportivo para prácticas docentes | 1 | 55 |
| es/817 | Education | Petición de material audiovisual para docencia | 1 | 15 |
| es/818 | Education | Prestación de consentimiento para tratamiento de datos en una solicitud académica | 1 | 9 |
| es/819 | Education | Solicitud de instalaciones para investigación, prácticas docentes y deportistas de alto nivel | 1 | 21 |
| es/820 | WorkplaceHR | Reducción extraordinaria de jornada para PTGAS mayor de 60 años | 1 | 6 |
| es/821 | WorkplaceHR | Comunicación del número de Seguridad Social para contratación | 1 | 13 |
| es/822 | WorkplaceHR | Recibí de equipos de protección individual por trabajador | 1 | 51 |
| es/823 | WorkplaceHR | Solicitud de dispositivos verticales de protección laboral | 1 | 7 |
| es/824 | WorkplaceHR | Peticiones y demandas de prevención de riesgos laborales | 1 | 10 |
| es/825 | GovPublic | Declaración de capacidad de remolque para embarcaciones no específicamente remolcadores | 1 | 20 |
| es/826 | GovPublic | Declaración de arqueo | 2 | 26 |
| es/827 | GovPublic | FSV - Formulario de solicitud de visa | 3 | 61 |
| es/828 | GovPublic | Solicitud de número EORI para no establecidos en la UE | 3 | 34 |
| es/829 | GovPublic | Solicitud de vista de las actuaciones ante la CNCE | 1 | 9 |
| es/830 | GovPublic | Declaración de construcción flotante no destinada a la navegación | 2 | 31 |
| es/831 | GovPublic | Declaración de asignación de pasajeros - Profesionales y OR | 2 | 25 |
| es/832 | GovPublic | Inspección, reparación, alteración y reconstrucción - DA 337-A | 2 | 86 |
| es/833 | GovPublic | Declaración de modificaciones - Profesionales y OR | 4 | 97 |
| es/834 | GovPublic | Solicitud de certificado de explotador de VANT/SVANT | 3 | 120 |
| es/835 | Finance | Suscripción al servicio de avisos de la AEAT | 1 | 7 |
| es/836 | Finance | Formulario 3 COMBINADO - Control de Supervivencia y de Estado Civil | 1 | 17 |
| es/837 | Finance | PS.6.37 - Solicitud Cambio de Agente Pagador | 1 | 34 |
| es/838 | Finance | Representación en el procedimiento de inspección y sancionador derivado | 1 | 41 |
| es/839 | Finance | Declaración jurada de pensión - Anexo I | 1 | 16 |
| es/840 | Finance | Declaración de deudos con derecho a pensión | 1 | 6 |
| es/841 | Finance | Comunicación de cambio en la situación del beneficiario - 04 | 1 | 24 |
| es/842 | Finance | Ausencia del país - Reclamo de haberes - 02 | 1 | 42 |
| es/843 | Finance | Solicitud de tasación de inmueble | 3 | 53 |
| es/844 | Finance | Solicitud de préstamo personal - Fondo Nacional de las Artes | 7 | 242 |
| fr/800 | Healthcare | Demande non spécifique de remboursement d’une spécialité pharmaceutique | 1 | 11 |
| fr/801 | Healthcare | Adhésion en qualité de praticien de l’art infirmier à la Convention nationale | 1 | 8 |
| fr/802 | Healthcare | Demande d’inscription en qualité d’infirmier auprès de l’INAMI | 2 | 13 |
| fr/803 | Healthcare | Demande de prime pour les infirmiers ayant une qualification professionnelle particulière en diabétologie | 2 | 20 |
| fr/804 | Healthcare | Notification de soins infirmiers pour un patient palliatif (annexe 6) | 1 | 19 |
| fr/805 | Healthcare | Formulaire de demande ou de prescriptions (annexe 32) | 1 | 17 |
| fr/806 | Healthcare | Attestation du médecin traitant pour admission palliative en centre de soins de jour | 1 | 7 |
| fr/807 | Healthcare | Trajet de soins diabète : demande pour la délivrance d’un glucomètre (B31) | 1 | 15 |
| fr/808 | Healthcare | Notification d’un programme éducation et autogestion chez un patient diabétique de type 2 (B41) | 1 | 9 |
| fr/809 | Healthcare | Demande d’intervention pour six forfaits PMA1 ou PMA2 (annexe A1) | 1 | 9 |
| fr/810 | Healthcare | Notification d’intervention pour aliments diététiques en cas de galactosémie (C51) | 1 | 9 |
| fr/811 | Healthcare | Autorisation de remboursement de nutrition parentérale ambulatoire (C42) | 1 | 14 |
| fr/812 | Healthcare | Demande pour un examen en imagerie médicale (annexe 82) | 1 | 14 |
| fr/813 | Healthcare | Autorisation limitée d’aliments diététiques à des fins médicales spéciales (C11) | 1 | 13 |
| fr/814 | Healthcare | Plan de soins pour prestations techniques spécifiques de soins infirmiers | 1 | 27 |
| fr/815 | Healthcare | Paiement au comptant des prestations pharmaceutiques remboursables (annexe 30) | 1 | 13 |
| fr/816 | Healthcare | Certificat d’incapacité de travail d’un assuré étranger en Belgique | 2 | 22 |
| fr/817 | Healthcare | Statut social : attestation de votre activité professionnelle hebdomadaire | 2 | 13 |
| fr/818 | Healthcare | Demande d’un numéro INAMI de médecin avec code compétence -000 | 2 | 11 |
| fr/819 | Healthcare | Notification des données d’un Conebeam CT (annexe 84) | 1 | 14 |
| fr/820 | Education | Inscription comme nouvel organisateur de peer-review dentaire | 1 | 6 |
| fr/821 | Education | Inscription à la formation pédagogique relative à l’enseignement de la danse | 2 | 19 |
| fr/822 | Education | Évaluation d’une formation continue dentaire et attestation de présence | 1 | 38 |
| fr/823 | Education | Évaluation d’une activité de formation continue par l’organisateur | 1 | 90 |
| fr/824 | Healthcare | Statut social : attestation d’attribution de prestations à un tiers | 2 | 13 |
| fr/825 | Education | Support didactique d’e-learning pour l’accréditation professionnelle | 3 | 34 |
| fr/826 | Education | Reconnaissance comme organisateur d’e-learning professionnel | 3 | 34 |
| fr/827 | Education | Nouveaux responsables de la reconnaissance des activités de formation continue | 2 | 23 |
| fr/828 | Education | Changement de rapporteur de GLEM pour la formation continue | 2 | 8 |
| fr/829 | Education | Création d’un GLEM de formation continue | 5 | 102 |
| fr/830 | Business | Déclaration de renonciation du gérant du débit de tabac le plus proche | 1 | 13 |
| fr/831 | Business | Demande d’autorisation d’exercice d’une entreprise cinématographique | 4 | 140 |
| fr/832 | Business | Attestation d’identification pour l’exonération du carburant du transport fluvial de marchandises | 1 | 11 |
| fr/833 | Business | Déclaration trimestrielle d’activité des distributeurs de produits énergétiques en exemption de TICPE | 1 | 17 |
| fr/834 | Business | Autorisation de réception, stockage, reconditionnement et distribution de produits énergétiques exemptés | 1 | 23 |
| fr/835 | Business | Déclaration d’engagement du représentant légal de l’établissement de revente de tabac | 2 | 13 |
| fr/836 | Business | Avis d’importation en franchise | 2 | 31 |
| fr/837 | Business | Demande de remboursement ou remise de droits de douane | 3 | 44 |
| fr/838 | Business | Bordereau de vente à l’exportation, procédure de secours | 3 | 124 |
| fr/839 | Business | Déclaration d’ouverture de chantier | 3 | 38 |
| fr/840 | Business | Demande d’attestation de capacité de courtier de fret fluvial | 1 | 20 |
| fr/841 | Business | Fiche technique relative à la capacité financière d’une entreprise de transport | 1 | 34 |
| fr/842 | Business | Bordereau d’inscription de gage sans dépossession | 6 | 74 |
| fr/843 | Business | Demande d’arrêté de police de la circulation | 2 | 82 |
| fr/844 | Business | Remboursement partiel d’accise sur les énergies achetées pour les activités agricoles et forestières en 2024 | 3 | 98 |
| fr/845 | GovPublic | Demande d’intervention auprès de l’assureur avant aide juridictionnelle | 1 | 21 |
| fr/846 | GovPublic | Demande de copie d’un extrait conservé au répertoire civil | 2 | 23 |
| fr/847 | GovPublic | Demande de copie d’une décision de justice civile, sociale ou commerciale | 3 | 44 |
| fr/848 | GovPublic | Demande de copie d’une décision de justice pénale | 3 | 48 |
| fr/849 | GovPublic | Demande d’un certificat de non appel | 3 | 68 |
| fr/850 | WorkplaceHR | Enquête du CHSCT relative à un accident du travail grave | 3 | 84 |
| fr/851 | WorkplaceHR | Attestation du salarié ayant bénéficié de l’assistance du conseiller du salarié | 1 | 23 |
| fr/852 | WorkplaceHR | Demande de remboursement du salaire maintenu par l’employeur d’un conseiller du salarié | 1 | 22 |
| fr/853 | WorkplaceHR | État de frais d’un conseiller du salarié | 1 | 44 |
| fr/854 | WorkplaceHR | Demande d’adhésion à une convention de pré-retraite progressive | 7 | 349 |
