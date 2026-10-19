"""Contenu par defaut de la page d'accueil (copie de la maquette validee).

Sert de FILET : tant qu'une section n'a pas ete enregistree depuis l'admin,
le site affiche ces valeurs, donc l'accueil fonctionne des le premier jour
sur une base vierge ou existante, sans aucune ligne en base. Des qu'un admin
enregistre une section, SA version en base prend le relais (les reglages
`payload` sont fusionnes par-dessus ceux-ci ; les items en base remplacent
ceux-ci).

Convention : `title`/`subtitle`/`body` en francais, suffixe `_en` pour
l'anglais ; `payload` = reglages (FR), `payload_en` = uniquement les cles de
payload traduites."""

SECTION_ORDER = [
    "topbar",
    "hero",
    "hero_slides",
    "popular_searches",
    "stats",
    "services",
    "guarantees",
    "how_it_works",
    "top_providers",
    "pro",
    "academy",
    "news",
    "testimonials",
    "partners",
    "apps",
]

SECTIONS: dict[str, dict] = {
    "topbar": {
        "type": "topbar",
        "payload": {
            "countries_source": "config",  # "config" (liste ci-dessous) | "db" (pays avec service actif)
            "countries": [
                {"code": "TG", "name": "Togo"},
                {"code": "CI", "name": "Côte d'Ivoire"},
                {"code": "BJ", "name": "Bénin"},
            ],
            "default_country": "TG",
            "countries_label": "Pays :",
            "payment_text": "Paiement : Mixx by Yas · Flooz · Carte",
            "help_label": "Aide WhatsApp",
            "help_url": "",
        },
        "payload_en": {"countries_label": "Country:", "payment_text": "Payment: Mixx by Yas · Flooz · Card", "help_label": "WhatsApp help"},
    },
    "hero": {
        "type": "hero",
        "title": "Le bon artisan, vérifié et formé, près de chez vous.",
        "title_en": "The right craftsperson, verified and trained, near you.",
        "subtitle": "Plombiers, électriciens, nounous, cuisiniers, agents d'entretien... Décrivez votre besoin, SITA trouve le bon prestataire. Vous payez seulement quand le travail est fait.",
        "subtitle_en": "Plumbers, electricians, nannies, cooks, cleaners... Describe your need and SITA finds the right provider. You only pay when the work is done.",
        "payload": {
            "search_placeholder": "Ex : « mon robinet de cuisine fuit depuis hier »",
            "search_button": "Trouver",
            "popular_label": "Populaire :",
            # Titre ecrit lettre par lettre ; recommence apres une pause si "loop".
            "typewriter": {"enabled": True, "speed_ms": 55, "erase_speed_ms": 22, "pause_ms": 2600, "loop": True, "caret": True},
            "pay_note": {"kicker": "Paiement protégé", "text": "15 000 FCFA bloqués via Mobile Money. Libérés quand vous confirmez la fin du travail."},
        },
        "payload_en": {
            "badge": "Available in Lomé · Togo",
            "search_placeholder": "E.g. “my kitchen tap has been leaking since yesterday”",
            "search_button": "Find",
            "popular_label": "Popular:",
            "pay_note": {"kicker": "Protected payment", "text": "15,000 FCFA held via Mobile Money. Released when you confirm the work is done."},
        },
    },
    "hero_slides": {
        "type": "slides",
        "payload": {
            # Rapport largeur/hauteur des affiches : 4/3 | 1/1 | 16/9 | 3/4 | 4/5
            "ratio": "16/9",
            # cover : l'image remplit le cadre (recadree) ; contain : l'image entiere est visible
            "fit": "cover",
            # Affiche, sous l'image, le titre et le sous-titre de l'affiche (le plus souvent inutile : le texte est dans l'image).
            "show_caption": False,
            # fade | slide | stack | zoom | flip | coverflow
            "transition": "stack",
            "autoplay": True,
            "interval_ms": 4500,
            "pause_on_hover": True,
            "loop": True,
            "show_dots": True,
            "show_arrows": True,
            "show_progress": True,
        },
        # Aucune affiche par defaut : elles se publient depuis l'admin (Affiches d'accueil).
        "items": [],
    },
    "popular_searches": {
        "type": "chips",
        "items": [
            {"kind": "chip", "title": "Fuite d'eau", "title_en": "Water leak"},
            {"kind": "chip", "title": "Nounou certifiée", "title_en": "Certified nanny"},
            {"kind": "chip", "title": "Ménage de fin de semaine", "title_en": "Weekend cleaning"},
            {"kind": "chip", "title": "Climatisation", "title_en": "Air conditioning"},
            {"kind": "chip", "title": "Traiteur événement", "title_en": "Event catering"},
        ],
    },
    "stats": {
        "type": "stats",
        "items": [
            {"kind": "stat", "title": "prestataires inscrits", "title_en": "registered providers", "data": {"source": "vendors_total", "round_to": 1000, "suffix": "+"}},
            {"kind": "stat", "title": "téléchargements", "title_en": "downloads", "data": {"source": "manual", "value": "30 000+"}},
            {"kind": "stat", "title": "Togo · Côte d'Ivoire · Bénin", "title_en": "Togo · Côte d'Ivoire · Benin", "data": {"source": "countries_served", "suffix": " pays", "min": 3}},
        ],
    },
    "services": {
        "type": "services",
        "title": "Tous les services, un seul endroit",
        "title_en": "All services, one place",
        "payload": {
            "mode": "auto",  # "auto" = sous-categories les plus fournies ; "manual" = uniquement les items ci-dessous
            "auto_limit": 12,
            "link_label": "Voir les 25+ catégories →",
            "link_url": "/categories",
            "item_url_template": "/recherche?q={name}",
        },
        "payload_en": {"link_label": "See all 25+ categories →"},
        "items": [],
    },
    "guarantees": {
        "type": "guarantees",
        "title": "Quatre garanties Trankyl, sur chaque mission",
        "title_en": "Four Trankyl guarantees on every job",
        "payload": {"kicker": "La sécurité et la fiabilité sont notre priorité"},
        "payload_en": {"kicker": "Safety and reliability are our priority"},
        "items": [
            {"kind": "guarantee", "title": "Prestataires vérifiés", "title_en": "Verified providers", "body": "Pièce d'identité, adresse, références et entretien. Badge visible sur chaque profil.", "body_en": "ID, address, references and interview. Badge visible on every profile."},
            {"kind": "guarantee", "title": "Formés à l'Académie", "title_en": "Trained at the Academy", "body": "Parcours métier, quiz et certificat Trankyl. Les certifiés passent en tête des résultats.", "body_en": "Career path, quizzes and Trankyl certificate. Certified providers rank first."},
            {"kind": "guarantee", "title": "Paiement protégé", "title_en": "Protected payment", "body": "Mobile Money ou carte. L'argent est bloqué et versé au prestataire à la fin du travail.", "body_en": "Mobile Money or card. Money is held and paid to the provider when the work is done."},
            {"kind": "guarantee", "title": "Assurance en option", "title_en": "Optional insurance", "body": "Couvrez la casse et les dommages pour quelques centaines de FCFA, au moment de payer.", "body_en": "Cover breakage and damage for a few hundred FCFA at checkout."},
        ],
    },
    "how_it_works": {
        "type": "steps",
        "title": "Comment ça marche",
        "title_en": "How it works",
        "items": [
            {"kind": "step", "title": "Décrivez", "title_en": "Describe", "body": "Texte, photo ou vocal, en français ou en langue locale. SITA comprend et précise.", "body_en": "Text, photo or voice, in French or a local language. SITA understands and clarifies."},
            {"kind": "step", "title": "Comparez", "title_en": "Compare", "body": "Profils, avis vérifiés, prix indicatifs et disponibilités. Discutez dans le chat.", "body_en": "Profiles, verified reviews, indicative prices and availability. Chat with providers."},
            {"kind": "step", "title": "Réservez et payez protégé", "title_en": "Book and pay safely", "body": "Devis accepté en un clic, paiement bloqué, assurance en option, suivi en temps réel.", "body_en": "Accept the quote in one click, payment held, optional insurance, live tracking."},
            {"kind": "step", "title": "Réservez et notez", "title_en": "Book and rate", "body": "Facture automatique, avis vérifié, prestataire en favori pour la prochaine fois.", "body_en": "Automatic invoice, verified review, provider saved as a favourite."},
        ],
    },
    "top_providers": {
        "type": "top_providers",
        "title": "Les mieux notés à Lomé",
        "title_en": "Top rated in Lomé",
        "payload": {
            "limit": 4,
            "min_rating": 0,
            "fill_with_unrated": True,  # complete avec des certifies non encore notes (par score de confiance)
            "link_label": "Tous les prestataires →",
            "link_url": "/prestataires",
        },
        "payload_en": {"link_label": "All providers →"},
    },
    "pro": {
        "type": "pro",
        "title": "Plus de clients, moins de paperasse.",
        "title_en": "More customers, less paperwork.",
        "payload": {
            "kicker": "Trankyl Pro · Pour les artisans et prestataires",
            "text": "Un profil pro à partager sur WhatsApp, des demandes près de chez vous, des devis et factures, une formation certifiante et une assurance pour travailler l'esprit tranquille.",
            "primary_label": "Créer mon profil gratuit",
            "primary_url": "/register",
            "secondary_label": "Me former d'abord",
            "secondary_url": "/metiers",
        },
        "payload_en": {
            "kicker": "Trankyl Pro · For craftspeople and providers",
            "text": "A pro profile to share on WhatsApp, requests near you, quotes and invoices in 30 seconds, certified training and insurance for peace of mind.",
            "primary_label": "Create my free profile",
            "secondary_label": "Train first",
        },
        "items": [
            {"kind": "feature", "title": "Profil + lien partageable", "title_en": "Profile + shareable link", "subtitle": "trankyl.com/kossi-plombier", "subtitle_en": "trankyl.com/kossi-plumber"},
            {"kind": "feature", "title": "Devis & factures", "title_en": "Quotes & invoices", "subtitle": "PDF + envoi WhatsApp", "subtitle_en": "PDF + WhatsApp sending"},
            {"kind": "feature", "title": "Badges de confiance", "title_en": "Trust badges", "subtitle": "Vérifié · Certifié · Assuré", "subtitle_en": "Verified · Certified · Insured"},
            {"kind": "feature", "title": "Coach SITA Pro", "title_en": "SITA Pro coach", "subtitle": "Conseils prix, réponses, profil", "subtitle_en": "Pricing tips, replies, profile", "tone": "highlight"},
        ],
    },
    "academy": {
        "type": "academy",
        "title": "Apprenez un métier qui compte",
        "title_en": "Learn a trade that matters",
        "payload": {
            "kicker": "Trankyl Académie",
            "text": "Vidéos courtes, fiches pratiques, quiz et certificat reconnu par Trankyl. Agent d'entretien, aide à domicile, cuisinier, nounou... et bientôt plomberie, électricité, froid.",
            "cta_label": "Découvrir les parcours",
            "cta_url": "/metiers",
        },
        "payload_en": {
            "kicker": "Trankyl Academy",
            "text": "Short videos, practical sheets, quizzes and a Trankyl-recognised certificate. Cleaner, home carer, cook, nanny... and soon plumbing, electricity, cooling.",
            "cta_label": "Discover the programmes",
        },
    },
    "news": {
        "type": "news",
        "title": "Actualités",
        "title_en": "News",
        "payload": {"limit": 3, "link_label": "Tout lire →", "link_url": "/blog"},
        "payload_en": {"link_label": "Read all →"},
    },
    "testimonials": {
        "type": "testimonials",
        "title": "Ils ont fait appel à Trankyl",
        "title_en": "They trusted Trankyl",
        "payload": {"limit": 3, "min_rating": 4, "verified_label": "Avis vérifié"},
        "payload_en": {"verified_label": "Verified review"},
        "items": [],  # temoignages manuels optionnels (affiches avant les avis reels)
    },
    "partners": {
        "type": "partners",
        "payload": {"supported_label": "Ils nous soutiennent et nous accompagnent.", "press_label": "Vu dans la presse"},
        "payload_en": {"supported_label": "They support and accompany us.", "press_label": "As seen in the press"},
        # Memes logos et memes liens que le site Trankyl (rubriques « Ils nous soutiennent » et « Partenaires »).
        "items": [
            {"kind": "supporter", "title": "GIZ · Cofinancement UE", "title_en": "GIZ · EU co-financing", "image_url": "/partners/giz-cofin-ue.png", "link_url": "https://www.youtube.com/watch?v=lVvcKrn3GmQ&t=16s"},
            {"kind": "supporter", "title": "ATD", "image_url": "/partners/atd.png", "link_url": "https://www.togofirst.com/fr/tic/1005-7808-a-la-decouverte-de-trankyl-l-appli-togolaise-de-mise-en-relation-entre-prestataires-a-domicile-et-particuliers"},
            {"kind": "supporter", "title": "Lomé Bouge Info", "image_url": "/partners/lome-bouge.jpg", "link_url": "https://lomebougeinfo.tg/togo-decouvrez-trankyl-la-seule-application-pour-tous-les-services-2/"},
            {"kind": "supporter", "title": "IFC", "image_url": "/partners/ifc.svg", "link_url": "https://www.ifc.org/fr/home"},
            {"kind": "supporter", "title": "PNUD", "title_en": "UNDP", "image_url": "/partners/pnud.svg", "link_url": "https://www.undp.org/"},
            {"kind": "supporter", "title": "Togo Tech", "image_url": "/partners/togo-tech.svg", "link_url": "https://www.togotech.tg/"},
            {"kind": "press", "title": "Reportage vidéo", "title_en": "Video report", "image_url": "/partners/presse-tele.svg", "link_url": "https://www.youtube.com/watch?v=lVvcKrn3GmQ&t=16s"},
            {"kind": "press", "title": "TogoFirst", "image_url": "/partners/presse-togo.svg", "link_url": "https://www.togofirst.com/fr/tic/1005-7808-a-la-decouverte-de-trankyl-l-appli-togolaise-de-mise-en-relation-entre-prestataires-a-domicile-et-particuliers"},
            {"kind": "press", "title": "Lomé Bouge Info", "image_url": "/partners/presse-lome.svg", "link_url": "https://lomebougeinfo.tg/togo-decouvrez-trankyl-la-seule-application-pour-tous-les-services-2/"},
            {"kind": "press", "title": "CIO Mag", "image_url": "/partners/presse-cio.svg", "link_url": "https://cio-mag.com/trankyl-lapplication-pour-tous-les-services-en-toute-tranquillite/"},
            {"kind": "press", "title": "Oceans News", "image_url": "/partners/presse-ocean.svg", "link_url": "https://oceans-news.com/plateforme-numerique-trankyl-solution-sure-de-mise-en-relation/"},
            {"kind": "press", "title": "Africa Presse", "title_en": "Africa Press", "image_url": "/partners/presse-africa-presse.svg", "link_url": "https://www.africapresse.paris/Sati-SAI-CEO-de-Trankyl-au-Togo-Nous-voulons-nous-positionner-sur-le-marche-des"},
        ],
    },
    "apps": {
        "type": "apps",
        # Memes applications, memes liens de stores et memes visuels que le site Trankyl.
        "items": [
            {"kind": "app", "title": "App Trankyl", "subtitle": "Pour les clients : demander, suivre, payer, noter.", "subtitle_en": "For customers: request, track, pay, rate.", "tone": "yellow", "image_url": "/apps/client-app.webp",
             "data": {"stores": [{"label": "Google Play", "url": "https://play.google.com/store/apps/details?id=com.trankyl.client"}, {"label": "App Store", "url": "https://apps.apple.com/fr/app/trankyl/id1547815509"}]}},
            {"kind": "app", "title": "Trankyl Heros", "subtitle": "Pour les prestataires : missions, devis, factures, formation.", "subtitle_en": "For providers: jobs, quotes, invoices, training.", "tone": "dark", "image_url": "/apps/vendor-app.webp",
             "data": {"badge": "PRO", "stores": [{"label": "Google Play", "url": "https://play.google.com/store/apps/details?id=com.trankyl.vhero&hl=en_IN&gl=US"}, {"label": "App Store", "url": "https://apps.apple.com/us/app/trankyl-heros/id1548459730"}]}},
        ],
    },
}

# Palette cyclique des icones de services (reprend les tons de la maquette).
SERVICE_TONES = ["green", "gold", "grey", "yellow"]
