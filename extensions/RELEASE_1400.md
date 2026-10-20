# NEST Additions: 19 October 2026

This increment adds 100 complete source forms to the [1,300-template inventory](RELEASE_1300.md).
The combined text-task inventory is 1,400 templates. Existing data and identifiers are unchanged.

## Coverage

| Language | Added | Combined |
| --- | ---: | ---: |
| English | 0 | 449 |
| Chinese | 0 | 431 |
| French | 50 | 255 |
| Spanish | 50 | 265 |
| **Total** | **100** | **1,400** |

| Language | GovPublic | Business | Finance | Healthcare | Education | WorkplaceHR | Total |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| en | 97 | 95 | 98 | 53 | 40 | 66 | 449 |
| zh | 23 | 107 | 41 | 23 | 32 | 205 | 431 |
| fr | 41 | 28 | 57 | 38 | 65 | 26 | 255 |
| es | 39 | 38 | 26 | 76 | 58 | 28 | 265 |

## New Files

All 100 additions are in [2026-10-19-multilingual-v0.1](2026-10-19-multilingual-v0.1/README.md).

- `workflow/0-html_template/data_<language>/<ID>.html`: empty templates.
- `workflow/1-annotated_json/`: structural annotations.
- `workflow/2-filled_json-a/` and `3-filled_html-a/`: synthetic filled instances.
- `workflow/4-context-a/`, `5-ph_html-a/`, `6-meta-a/`: contexts, placeholder templates and metadata.
- `manifest.json`: stable language-specific IDs, field counts and file hashes.
- `data/annotations/`, `data/provenance/`, `SOURCE.md`: source links, editions, collection dates and attribution.
- `SHA256SUMS`: checksums for every file in the batch.

Stages 7-9 and model predictions are not generated. The existing shared workflow entry point and
task metrics apply to these additions; there is no form-specific evaluator.

Complete multipage forms count as one sample. Original third-party documents are linked, not redistributed.
Per-source reuse terms and attribution are recorded in the batch source records.

## Sample Index

| Language/ID | Domain | Source form | Pages | Fields |
| --- | --- | --- | ---: | ---: |
| es/700 | WorkplaceHR | Solicitud de equipos de protección individual | 1 | 15 |
| es/701 | WorkplaceHR | Comunicación genérica a las unidades de prevención | 1 | 12 |
| es/702 | WorkplaceHR | Comunicación de deficiencias, incidentes, riesgos y propuestas de mejora | 1 | 14 |
| es/703 | WorkplaceHR | Comunicación personal de accidente de trabajo o incidente | 1 | 24 |
| es/704 | WorkplaceHR | Declaración responsable de accidente de trabajo in itinere o en desplazamiento | 2 | 30 |
| es/705 | WorkplaceHR | Comunicación de persona empleada especialmente sensible | 1 | 20 |
| es/706 | WorkplaceHR | Comunicación de embarazo y período de lactancia natural | 1 | 37 |
| es/707 | WorkplaceHR | Cuestionario de autoevaluación para el desarrollo del teletrabajo | 6 | 30 |
| es/708 | WorkplaceHR | Declaración responsable de contacto estrecho por COVID-19 | 1 | 20 |
| es/709 | WorkplaceHR | Comunicación de jornadas reales realizadas por trabajadores agrarios | 3 | 313 |
| es/710 | WorkplaceHR | Declaración de no estar afectado de incompatibilidad | 1 | 9 |
| es/711 | WorkplaceHR | Declaración jurada o promesa que formula | 1 | 11 |
| es/712 | WorkplaceHR | Juramento o promesa de toma de posesión | 1 | 8 |
| es/713 | WorkplaceHR | Declaración responsable de capacidad funcional | 1 | 11 |
| es/714 | WorkplaceHR | Datos personales y bancarios para nómina | 1 | 11 |
| es/715 | WorkplaceHR | Datos personales y profesionales | 1 | 15 |
| es/716 | WorkplaceHR | Comunicación de designación de delegados de prevención | 3 | 263 |
| es/717 | Finance | Designación de sujeto responsable del ingreso de cuotas de convenio especial | 3 | 69 |
| es/718 | WorkplaceHR | Comunicación de variación de datos del registro de prevención | 2 | 68 |
| es/719 | WorkplaceHR | Solicitud de tarjeta identificativa de delegados de prevención | 2 | 69 |
| es/720 | WorkplaceHR | Solicitud de afiliación, asignación de número y variación de datos | 4 | 81 |
| es/721 | GovPublic | Solicitud de documento o información en bases de datos de la TGSS | 3 | 93 |
| es/722 | WorkplaceHR | Solicitud de rectificación de datos de vida laboral | 2 | 174 |
| es/723 | GovPublic | Autorización de entrega de información a persona distinta a su titular | 2 | 100 |
| es/724 | Finance | Solicitud de cambio de base de cotización en convenios especiales | 4 | 37 |
| es/725 | Business | SOLICITUD DE CERTIFICADO DE PRIORIDAD | 1 | 17 |
| es/726 | WorkplaceHR | Solicitud de informe de antecedentes - personal civil PSA | 1 | 7 |
| es/727 | Business | SOLICITUD DE APROBACIÓN E INSCRIPCIÓN / LIBRE CIRCULACIÓN DE PRODUCTOS Y/O ELEMENTOS DE USO ENOLÓGICO | 1 | 32 |
| es/728 | Business | CERTIFICADO DE ANÁLISIS LIBRE CIRCULACIÓN POR DDJJ - PRODUCTOS ENOLÓGICOS (FORM. 1070) | 1 | 38 |
| es/729 | Business | FORMULARIO CERTIFICADO DE ANÁLISIS LIBRE CIRCULACIÓN POR DDJJ (elaboradores artesanales y caseros) | 1 | 20 |
| es/730 | Business | DECLARACIÓN JURADA DE ELABORACIÓN DE VINO CASERO Y ARTESANAL | 2 | 189 |
| es/731 | WorkplaceHR | INFORME DE FINALIZACION DE COSECHA (CONTRATISTAS) | 1 | 28 |
| es/732 | WorkplaceHR | PROTOCOLO PARA MEDICIÓN DE ILUMINACIÓN EN EL AMBIENTE LABORAL | 3 | 141 |
| es/733 | WorkplaceHR | PROTOCOLO DE MEDICIÓN DE RUIDO EN EL AMBIENTE LABORAL | 3 | 164 |
| es/734 | WorkplaceHR | PROTOCOLO DE MEDICIÓN DE LA PUESTA A TIERRA Y CONTINUIDAD DE LAS MASAS | 3 | 152 |
| es/735 | WorkplaceHR | PROTOCOLO PARA MEDICIÓN DE CONTAMINANTES QUÍMICOS EN EL AIRE DE UN AMBIENTE DE TRABAJO | 3 | 248 |
| es/736 | Business | SOLICITUD DE INSCRIPCION DE EMPAQUES | 1 | 17 |
| es/737 | Business | MUESTREO DE FRUTOS EN EMPAQUE | 1 | 50 |
| es/738 | Business | PLANILLA DE DESPACHO | 1 | 41 |
| es/739 | Business | SOLICITUD DE ABM DE USUARIO EXTERNO - SISTEMA DE GESTIÓN | 1 | 20 |
| es/740 | Business | SOLICITUD DE MODIFICACIÓN DE INFORMACIÓN EN EL RNCyFS | 2 | 160 |
| es/741 | Business | SOLICITUD DE INSCRIPCIÓN DE FIRMAS | 1 | 28 |
| es/742 | Business | PLANILLA DE COTIZACIÓN - CNAD-2026-CDI-05 | 2 | 5 |
| es/743 | Business | FORMULARIO DE MANTENIMIENTO DE LA OFERTA - CNAD-2026-CDI-05 | 2 | 6 |
| es/744 | Business | DECLARACIÓN JURADA DE INTERESES - DECRETO 202/2017 | 5 | 31 |
| es/745 | Business | SOLICITUD DE ENSAYO - LABORATORIO DE COMPATIBILIDAD ELECTROMAGNÉTICA (LECEM) | 3 | 46 |
| es/746 | Business | SOLICITUD DE EMISIÓN DE CERTIFICADO DE ANÁLISIS DE SEMILLAS | 1 | 35 |
| es/747 | WorkplaceHR | SOLICITUD DE HABILITACIÓN DE MUESTREADORES - PAQUETE COMPLETO | 6 | 178 |
| es/748 | Business | SOLICITUD DE ENSAYOS DE CLIENTES PARTICULARES - LABORATORIO ANIMAL | 2 | 74 |
| es/749 | Business | SOLICITUD DE ENSAYOS DE PRODUCTOS BIOLÓGICOS CON FINES DE REGISTRO | 2 | 36 |
| fr/700 | WorkplaceHR | Contrat de professionnalisation | 2 | 86 |
| fr/701 | WorkplaceHR | Contrat d’apprentissage | 2 | 152 |
| fr/702 | WorkplaceHR | Contrat emploi-consolidé : formation complémentaire et cotisation accident du travail | 11 | 467 |
| fr/703 | WorkplaceHR | Rupture conventionnelle du CDI d’un salarié protégé | 2 | 79 |
| fr/704 | WorkplaceHR | Déclaration mensuelle d’abattement de cotisations patronales des marins | 1 | 14 |
| fr/705 | WorkplaceHR | Contrat unique d’insertion : demande d’aide | 4 | 110 |
| fr/706 | WorkplaceHR | Exonération de cotisations patronales pour l’embauche en ZRR et ZRU | 5 | 116 |
| fr/707 | WorkplaceHR | Enquête du CHSCT sur des situations de risque grave | 3 | 45 |
| fr/708 | WorkplaceHR | Attestation relative à l’obligation annuelle de négocier sur les salaires | 1 | 9 |
| fr/709 | WorkplaceHR | Prise en charge des cotisations sociales des stagiaires professionnels non rémunérés | 3 | 68 |
| fr/710 | WorkplaceHR | Relevé individuel des temps d’activité prud’homale | 2 | 231 |
| fr/711 | WorkplaceHR | Déclaration de départ de salariés agricoles | 2 | 161 |
| fr/712 | WorkplaceHR | Autorisation de travail pour un salarié étranger résidant en France | 4 | 255 |
| fr/713 | WorkplaceHR | Dérogation à l’interdiction du travail de nuit des jeunes marins | 2 | 35 |
| fr/714 | WorkplaceHR | Autorisation d’emploi d’un jeune de quinze ans à bord d’un navire pendant les vacances | 2 | 47 |
| fr/715 | WorkplaceHR | Procès-verbal des élections du CSE : membres titulaires | 3 | 395 |
| fr/716 | WorkplaceHR | Indemnisation kilométrique d’un défenseur syndical | 2 | 88 |
| fr/717 | WorkplaceHR | Procès-verbal de carence pour tous les collèges du CSE | 1 | 38 |
| fr/718 | WorkplaceHR | Déclaration préalable à l’embauche d’un salarié agricole | 6 | 189 |
| fr/719 | WorkplaceHR | Remboursement des salaires maintenus pour les fonctions prud’homales | 1 | 42 |
| fr/720 | WorkplaceHR | Demande de médaille d’honneur du travail | 4 | 102 |
| fr/721 | WorkplaceHR | Requête aux fins de saisine du conseil de prud’hommes par un salarié | 9 | 260 |
| fr/722 | WorkplaceHR | Indemnisation d’un défenseur syndical rémunéré à la commission | 1 | 27 |
| fr/723 | WorkplaceHR | Remboursement à l’employeur du salaire maintenu d’un défenseur syndical | 1 | 34 |
| fr/724 | WorkplaceHR | Relevé mensuel des contrats de travail temporaire | 1 | 17 |
| fr/725 | Business | Déclaration préalable d’une activité commerciale ou artisanale ambulante | 2 | 23 |
| fr/726 | Business | Déclaration préalable à une vente en liquidation | 2 | 26 |
| fr/727 | Business | Déclaration préalable d’une vente au déballage | 1 | 21 |
| fr/728 | Business | Demande d’inscription sur le registre des revendeurs d’objets mobiliers | 1 | 16 |
| fr/729 | Business | Déclaration d’ouverture, de mutation ou de translation d’un débit de boissons | 3 | 59 |
| fr/730 | Business | Déclaration d’activité : commerce de matériels forestiers de reproduction | 2 | 40 |
| fr/731 | Business | Déclaration de vente directe d’œufs et exemption au classement | 2 | 28 |
| fr/732 | Business | Demande d’agrément sanitaire d’un établissement alimentaire | 2 | 20 |
| fr/733 | Business | Dérogation à l’obligation d’agrément sanitaire | 2 | 48 |
| fr/734 | Business | Déclaration en mairie de location de chambre d’hôte | 4 | 39 |
| fr/735 | Business | Déclaration en mairie des meublés de tourisme | 4 | 43 |
| fr/736 | Business | Renouvellement de licence pour le transport public routier | 1 | 25 |
| fr/737 | Business | Copies certifiées conformes de licences de transport routier | 2 | 26 |
| fr/738 | Business | Habilitation à la téléprocédure ECS Bureau de Sortie | 2 | 31 |
| fr/739 | Business | Demande de sortie du statut de déchet | 3 | 41 |
| fr/740 | Business | Déclaration de cession soumise au droit de préemption commercial | 3 | 89 |
| fr/741 | Business | Autorisation nationale de pêche professionnelle de l’anchois en zone CIEM VIII | 2 | 33 |
| fr/742 | GovPublic | Déclaration de détention et d’emplacement de ruches | 2 | 71 |
| fr/743 | GovPublic | Demande d’autorisation de défrichement | 3 | 138 |
| fr/744 | GovPublic | Demande de permission de voirie ou de permis de stationnement | 2 | 86 |
| fr/745 | Business | Agrément d’un véhicule routier pour le transport de longue durée d’animaux | 2 | 26 |
| fr/746 | Business | Déclaration d’activité des professionnels des animaux de compagnie domestiques | 3 | 43 |
| fr/747 | Business | Notification de mouvements ou transferts transfrontières de déchets | 2 | 105 |
| fr/748 | Business | Informations accompagnant les transferts de déchets de la liste verte | 2 | 90 |
| fr/749 | GovPublic | Demande d’autorisation d’un système de vidéoprotection | 3 | 133 |
