-- 0002_seed.sql — Stamgegevens en admin-gebruiker voor een verse database.
-- Idempotent: veilig om opnieuw te draaien. Data overgenomen uit de test-DB.

BEGIN;

-- ── Referentie-tabellen ─────────────────────────────────────────────────────

INSERT INTO public.conserveringsmethoden (id, naam, actief) VALUES
  (1, 'Vers', true),
  (2, 'Diepvries', true),
  (3, 'Koel', true),
  (4, 'Vacuum', true),
  (5, 'Weckpot', true),
  (6, 'Gedroogd', true)
ON CONFLICT (id) DO NOTHING;

INSERT INTO public.eenheden (id, naam, etiket_per_stuk, actief) VALUES
  (1, 'kg', false, true),
  (2, 'stuks', true, true),
  (3, 'gram', false, true),
  (4, 'liter', false, true)
ON CONFLICT (id) DO NOTHING;

INSERT INTO public.locations (id, name, active) VALUES
  (1, 'Koelkast', true),
  (2, 'Vriezer', true),
  (3, 'Voorraadkast', true),
  (4, 'Kelderkast', true),
  (5, 'Bijkeuken', true),
  (6, 'Pantry', true)
ON CONFLICT (id) DO NOTHING;

INSERT INTO public.ontvangers (id, naam, actief) VALUES
  (1, 'Familie Jansen', true),
  (2, 'Buren De Vries', true),
  (3, 'Voedselbank', true),
  (4, 'Familie Bakker', true)
ON CONFLICT (id) DO NOTHING;

INSERT INTO public.products (id, name, unit, eenheid_id, active) VALUES
  (1,  'Aardappelen',    'kg',    1, true),
  (2,  'Uien',           'kg',    1, true),
  (3,  'Wortelen',       'kg',    1, true),
  (4,  'Appels',         'kg',    1, true),
  (5,  'Peren',          'kg',    1, true),
  (6,  'Tomaten',        'kg',    1, true),
  (7,  'Pompoen',        'stuks', 2, true),
  (8,  'Courgette',      'stuks', 2, true),
  (9,  'Spinazie',       'kg',    1, true),
  (10, 'Prei',           'bos',   2, true),
  (11, 'Spruiten',       'kg',    1, true),
  (12, 'Bloemkool',      'stuks', 2, true),
  (13, 'Broccoli',       'stuks', 2, true),
  (14, 'Witte kool',     'stuks', 2, true),
  (15, 'Rode kool',      'stuks', 2, true),
  (16, 'Bonengedroogd',  'kg',    1, true)
ON CONFLICT (id) DO NOTHING;

-- ── Admin-gebruiker (maarten / demo2026) ────────────────────────────────────
-- Hash in pbkdf2-formaat, overgenomen uit de bestaande test-DB.

INSERT INTO public.users (id, username, hashed_password, email, is_admin) VALUES
  (1, 'maarten',
   'pbkdf2$210000$ba65afa526ab865d0a492801a44980a0$13815c98df8ddfbf46c9d8995833cc5a9f4a55cbdb7c93e801d9cd846e4931c8',
   'maartenkoks@gmail.com', true)
ON CONFLICT (id) DO NOTHING;

-- ── Sequences gelijkzetten met de hoogste id ────────────────────────────────

SELECT setval('public.conserveringsmethoden_id_seq', 6,  true);
SELECT setval('public.eenheden_id_seq',              4,  true);
SELECT setval('public.locations_id_seq',            6,  true);
SELECT setval('public.ontvangers_id_seq',            4,  true);
SELECT setval('public.products_id_seq',             16, true);
SELECT setval('public.users_id_seq',                 1,  true);

COMMIT;
