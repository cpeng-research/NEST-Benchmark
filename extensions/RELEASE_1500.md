# NEST Additions: 19 October 2026, Second Increment

This batch adds 100 complete source forms to the [1,400-template inventory](RELEASE_1400.md).
The combined text-task inventory is 1,500 templates. Existing files and identifiers are unchanged.

## Coverage

| Language | Added | Combined |
| --- | ---: | ---: |
| English | 0 | 449 |
| Chinese | 0 | 431 |
| French | 50 | 305 |
| Spanish | 50 | 315 |
| **Total** | **100** | **1,500** |

| Language | GovPublic | Business | Finance | Healthcare | Education | WorkplaceHR | Total |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| en | 97 | 95 | 98 | 53 | 40 | 66 | 449 |
| zh | 23 | 107 | 41 | 23 | 32 | 205 | 431 |
| fr | 56 | 43 | 57 | 48 | 65 | 36 | 305 |
| es | 49 | 53 | 51 | 76 | 58 | 28 | 315 |

## Files and Use

New batch: [2026-10-19-multilingual-v0.2](2026-10-19-multilingual-v0.2/README.md).

- Empty templates: `workflow/0-html_template/data_<language>/<ID>.html`.
- Structural annotations and synthetic filled instances: workflow stages 1-3.
- Synthetic contexts, placeholder templates and metadata: workflow stages 4-6.
- Sources, versions and collection dates: `SOURCE.md`, `data/provenance/` and `data/annotations/`.
- Complete file inventory: `manifest.json` and `SHA256SUMS`.

Stages 7-9 and model outputs are not generated. The existing shared workflow entry point
and task metrics apply. A multipage form is one sample; original source documents are linked,
not redistributed. Per-source attribution and reuse terms are recorded in the batch.

## Sample Index

| Language/ID | Domain | Source form | Pages | Fields |
| --- | --- | --- | ---: | ---: |
| es/750 | Finance | Solicitud de aplazamiento de deudas superiores a 50.000 euros | 6 | 90 |
| es/751 | Finance | Solicitud de compensación de deudas | 4 | 91 |
| es/752 | Finance | Solicitud de suspensión del procedimiento de pago y de expedición de certificado a efectos de la compensación prevista en el artículo 56 del Reglamento General de Recaudación | 1 | 17 |
| es/753 | Finance | Ficha identificativa del crédito | 1 | 19 |
| es/754 | Finance | Modelo de aval para la concesión de aplazamientos y fraccionamientos de pago (código de aval 3) | 2 | 34 |
| es/755 | Finance | Modelo H-100. Solicitud de pago de devolución a herederos | 1 | 25 |
| es/756 | Finance | Solicitud de adhesión al procedimiento electrónico para el intercambio de ficheros entre la Agencia Estatal de Administración Tributaria y las entidades de crédito, en el ámbito de las obligaciones de información a la Administración Tributaria relativas a extractos normalizados de cuentas corrientes | 1 | 18 |
| es/757 | Finance | Comunicación de adhesión al procedimiento de enajenación de bienes por vía telemática | 1 | 12 |
| es/758 | Finance | Comunicación de adhesión al procedimiento para efectuar por medios telemáticos el embargo de dinero en cuentas abiertas en entidades de crédito | 1 | 16 |
| es/759 | Finance | Interposición de recurso de reposición | 4 | 116 |
| es/760 | Finance | Denuncia pública tributaria | 2 | 11 |
| es/761 | Finance | Modelo 145 | 2 | 92 |
| es/762 | Finance | Modelo 146 | 2 | 88 |
| es/763 | Finance | Modelo 147 | 2 | 82 |
| es/764 | Finance | TC.13/1 Solicitud de devolución de ingresos indebidos | 2 | 96 |
| es/765 | Finance | TC1/15-3 Mandato de adeudo directo SEPA para cuotas | 2 | 32 |
| es/766 | Finance | TC17/10 Solicitud de aplazamiento de deudas | 9 | 376 |
| es/767 | Finance | TC17/12 Cambio de cuenta de domiciliación de aplazamiento | 2 | 23 |
| es/768 | Finance | Solicitud de moratoria, diferimiento o exención de cuotas | 1 | 47 |
| es/769 | Finance | Formulario de solicitud de aportes no reembolsables (ANR) para la reparación de comercios afectados | 2 | 16 |
| es/770 | Finance | Solicitud o comunicación a la Administración Tributaria | 3 | 98 |
| es/771 | Finance | Solicitud de mantenimiento de cuentas de acreedores | 2 | 48 |
| es/772 | Finance | Modelo 04 Solicitud de tipo reducido de IVA para vehiculo | 2 | 94 |
| es/773 | Finance | Modelo 01 Solicitud de certificados tributarios | 2 | 90 |
| es/774 | Finance | Modelo de representación fiscal del importador a los efectos del artículo 86.tres LIVA | 1 | 17 |
| es/775 | Business | Especificaciones de operación de mantenimiento | 1 | 13 |
| es/776 | Business | Solicitud de producto a pedido para establecimiento elaborador, APA 4B | 1 | 16 |
| es/777 | Business | Planilla de peso y balanceo | 1 | 14 |
| es/778 | Business | Solicitud de certificado tipo, de producción o tipo suplementario | 2 | 19 |
| es/779 | Business | Certificado de liberación autorizada, tarjeta de aprobación de aeronavegabilidad | 1 | 20 |
| es/780 | Business | Registro de inspección de aeronave militar de excedente | 1 | 39 |
| es/781 | Business | Declaración de cumplimiento de aeronave deportiva liviana | 1 | 40 |
| es/782 | Business | Solicitud de certificado de habilitación de taller aeronáutico de reparación | 1 | 34 |
| es/783 | Business | Presolicitud de declaración de intención | 2 | 29 |
| es/784 | Business | Informe de ingreso al centro de mantenimiento de aeronave, motor o hélice | 1 | 29 |
| es/785 | Business | Solicitud de traslado de taller | 1 | 29 |
| es/786 | Business | Autorización a consignatarios para emisión de DT-e y cierre de movimientos en SIGSA | 1 | 11 |
| es/787 | Business | Solicitud de alta como entidad autorizada en SIGSA | 1 | 8 |
| es/788 | Business | Certificado de fabricación de instalación blindada, Anexo IV | 1 | 24 |
| es/789 | Business | Solicitud de apertura de expediente electrónico para inscripción de productos veterinarios | 1 | 11 |
| es/790 | GovPublic | Solicitud de inscripción en la matrícula nacional de buques | 2 | 126 |
| es/791 | GovPublic | Solicitud de transferencia de buques menores, NAB 3 a 9 | 2 | 124 |
| es/792 | GovPublic | Solicitudes varias de buques: motor, medidas, tipo y eliminación | 1 | 62 |
| es/793 | GovPublic | Solicitud de certificación de dominio o inhibiciones de buques | 2 | 59 |
| es/794 | GovPublic | Solicitud de inscripciones varias de buques | 2 | 85 |
| es/795 | GovPublic | Ejercicio del derecho de acceso a datos personales | 1 | 20 |
| es/796 | GovPublic | Ejercicio del derecho de rectificación, actualización o supresión de datos personales | 1 | 23 |
| es/797 | GovPublic | Solicitud de credencial de investigador de la Biblioteca Nacional | 2 | 48 |
| es/798 | GovPublic | Reclamo sobre servicios postales, F.37d | 6 | 43 |
| es/799 | GovPublic | Declaración jurada de reempadronamiento nacional obligatorio de armas | 3 | 70 |
| fr/750 | Healthcare | Demande d'ouverture des droits à l'assurance maladie | 2 | 22 |
| fr/751 | Healthcare | Notification de suspicion de maladie de Creutzfeldt-Jakob, GSS ou insomnie fatale familiale | 1 | 78 |
| fr/752 | Healthcare | Certificat médical : information particulière en cas de coupure de courant | 2 | 11 |
| fr/753 | Healthcare | Certificat médical de contre-indication à la vaccination COVID-19 | 3 | 43 |
| fr/754 | Healthcare | Notification obligatoire de rubéole | 1 | 83 |
| fr/755 | Healthcare | Certificat médical d’accouchement pour un acte d’enfant sans vie | 1 | 25 |
| fr/756 | Healthcare | Notification obligatoire d’hépatite aiguë A | 1 | 59 |
| fr/757 | Healthcare | Certificat d’aptitude physique au permis de plaisance à moteur | 2 | 22 |
| fr/758 | Healthcare | Signalement obligatoire de rougeole | 1 | 97 |
| fr/759 | Healthcare | Déclaration initiale et issue du traitement de la tuberculose | 2 | 115 |
| fr/760 | GovPublic | Dérogation pour transport et relâcher de spécimens d’espèces animales protégées | 2 | 69 |
| fr/761 | GovPublic | Dérogation pour destruction, altération ou dégradation de sites de reproduction ou aires de repos | 2 | 52 |
| fr/762 | GovPublic | Demande de certificat d’immatriculation d’un véhicule | 1 | 88 |
| fr/763 | GovPublic | Mandat pour effectuer les formalités d’immatriculation | 1 | 21 |
| fr/764 | GovPublic | Certificat de cession d’un véhicule d’occasion | 2 | 104 |
| fr/765 | GovPublic | Demande d’inscription sur les listes électorales des citoyens français | 2 | 35 |
| fr/766 | GovPublic | Attestation de témoin | 3 | 19 |
| fr/767 | GovPublic | Vote par procuration et récépissé | 2 | 47 |
| fr/768 | GovPublic | Demande d’inscription au permis de conduire des bateaux de plaisance à moteur | 1 | 20 |
| fr/769 | GovPublic | Déclaration de perte ou vol du certificat d’immatriculation | 1 | 25 |
| fr/770 | GovPublic | Dérogation pour le transport de spécimens d’espèces animales protégées | 2 | 74 |
| fr/771 | GovPublic | Déclaration d’une manifestation sportive non motorisée sans classement | 2 | 21 |
| fr/772 | GovPublic | Consultation du dossier d’assistance éducative au tribunal pour enfants | 2 | 22 |
| fr/773 | GovPublic | Autorisation de sortie du territoire d’un mineur | 1 | 30 |
| fr/774 | GovPublic | Fiche d’intervention sur équipement à fluides frigorigènes | 1 | 49 |
| fr/775 | Business | Demande d’attestation d’habilitation d’un collaborateur immobilier | 2 | 40 |
| fr/776 | Business | Bulletin de déclaration d’activité d’un prestataire de formation | 2 | 49 |
| fr/777 | Business | Déclaration de manipulation ou de déclassement en entrepôt | 2 | 30 |
| fr/778 | Business | Demande de classement d’un meublé de tourisme | 1 | 30 |
| fr/779 | Business | Attestation du gérant du débit de tabac de rattachement | 2 | 15 |
| fr/780 | Business | Fiche de fabrication en entrepôt fiscal | 2 | 31 |
| fr/781 | Business | Demande d’indemnisation des pertes de fonds au titre des calamités agricoles | 2 | 29 |
| fr/782 | Business | Demande d’autorisation d’exportateur agréé pour l’origine préférentielle | 5 | 112 |
| fr/783 | Business | Déclaration d’intention de cessation d’activité agricole | 1 | 42 |
| fr/784 | Business | Fiche de renseignements pour l’installation d’un exploitant agricole étranger | 2 | 144 |
| fr/785 | Business | Demande d’autorisation de fabrication, commerce ou intermédiation de matériels réglementés, personne physique | 1 | 14 |
| fr/786 | Business | Déclaration préalable d’intervention d’un entrepreneur de spectacles hors UE ou EEE | 4 | 133 |
| fr/787 | Business | Bordereau de suivi des déchets | 2 | 153 |
| fr/788 | Business | Avis de travaux urgents aux exploitants de réseaux | 1 | 43 |
| fr/789 | Business | Déclaration du bénéfice des droits acquis d’une installation classée, régime déclaration | 5 | 116 |
| fr/790 | WorkplaceHR | Convention de période de mise en situation en milieu professionnel | 3 | 106 |
| fr/791 | WorkplaceHR | Éléments du contrat de travail, passeport talent salarié diplômé ou entreprise innovante | 2 | 45 |
| fr/792 | WorkplaceHR | Demande d’adhésion à une convention d’allocation spéciale du FNE | 4 | 172 |
| fr/793 | WorkplaceHR | Éléments du contrat de travail, salarié détaché ICT | 2 | 72 |
| fr/794 | WorkplaceHR | Liste des dépenses déductibles DOETH engagées par l’établissement en 2019 | 1 | 17 |
| fr/795 | WorkplaceHR | Attestation de salaire pour le paiement des indemnités journalières | 2 | 130 |
| fr/796 | WorkplaceHR | Demande de cessation anticipée d’activité des marins-pêcheurs | 3 | 50 |
| fr/797 | WorkplaceHR | Demande d’attribution de l’allocation complémentaire de ressources des marins | 3 | 58 |
| fr/798 | WorkplaceHR | Déclaration préalable d’une opération de bâtiment ou génie civil à l’inspection du travail | 1 | 82 |
| fr/799 | WorkplaceHR | Demande d’utilisation de points C2P pour une majoration de durée d’assurance pour la retraite | 2 | 19 |
