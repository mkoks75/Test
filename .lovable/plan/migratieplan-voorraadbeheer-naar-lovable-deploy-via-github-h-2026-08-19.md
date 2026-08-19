# Migratieplan: voorraadbeheer naar Lovable, deploy via GitHub → Hetzner

Doel: de complete FastAPI/Jinja-applicatie herbouwen als één TanStack Start-app in Lovable, met PostgreSQL op je eigen Hetzner-server, en de bestaande deploystraat (GitHub Actions → SSH → Docker Compose op Hetzner) hergebruiken.

## Uitgangspunten

- Alle functionaliteit blijft behouden; het design wordt nieuw (de stijl van het proefstuk).
- Database: PostgreSQL in een container op Hetzner, naast de app-container.
- Geen Lovable Cloud: de app praat rechtstreeks met jouw database via server functions.
- De huidige SQLite-data wordt eenmalig geconverteerd naar PostgreSQL.

## Fase 0 — Infrastructuur op Hetzner (eenmalig)

- `docker-compose.yml` uitbreiden met een `postgres:16` service met named volume en dagelijkse dump naar een backupmap.
- App-container wordt een Node-container die de gebouwde TanStack Start-server draait in plaats van uvicorn.
- Secrets als environment variables op de server: databaseverbinding, sessiegeheim, SMTP-gegevens.
- GitHub Actions workflow aanpassen: build → image/artifact naar de server → `docker compose up -d`. Dezelfde SSH-secrets als nu.

## Fase 1 — Datamodel

Alle 16 tabellen uit `models.py` worden SQL-migraties met dezelfde relaties:

| Groep | Tabellen |
| --- | --- |
| Toegang | `users`, `password_reset_tokens` |
| Stamdata | `producten`, `eenheden`, `locaties`, `conserveringsmethoden`, `product_houdbaarheid` |
| Oogst & uitgifte | `harvest_entries`, `ontvangers`, `uitgiftes` |
| Winkel & containers | `shop_items`, `shop_uitgiftes`, `containers`, `niveau_logs` |
| Overig | `shared_lists`, `product_cache` |

Daarna: importscript dat de bestaande SQLite-database uitleest en één op één in PostgreSQL zet, inclusief id's zodat historie en volgnummers kloppen.

## Fase 2 — Basis van de applicatie

- Databaselaag: één verbindingsmodule plus getypeerde queries, alleen aangeroepen vanuit server functions.
- Inloggen met sessiecookie, wachtwoord-hashing en wachtwoord-reset per mail — gelijk aan `auth.py`.
- Rollen: admin versus gebruiker, afgedwongen op de server bij elke actie, niet alleen in de UI.
- Navigatieschil, foutpagina's en de designtokens uit het proefstuk als vaste basis.

## Fase 3 — Kernschermen

1. **Dashboard** — voorraadcijfers, bijna verlopen, snelle acties (uitbouw van het proefstuk, nu op echte data).
2. **Oogst registreren** — inclusief nieuw product aanmaken en houdbaarheid instellen zonder het formulier te verlaten, en de aparte afhandeling van producten met etiket per stuk.
3. **Voorraadoverzicht** — filteren op product, locatie, conservering en houdbaarheid; detailweergave per partij.
4. **Uitgifte** — uitgifte aan ontvangers, met correctie van de resterende voorraad en volledige historie.

## Fase 4 — Winkel, containers en boodschappen

5. **Winkelvoorraad** — `shop_items` met eigen uitgiftes en niveauregistratie.
6. **Containers** — niveaulogboek en verloop per container.
7. **Boodschappen en gedeelde lijsten** — inclusief deelbare lijst via link.
8. **Geopende producten** — bijhouden wat is aangebroken en tot wanneer houdbaar.

## Fase 5 — Beheer en afronding

9. **Beheer** — producten, eenheden, locaties, ontvangers, conserveringsmethoden en houdbaarheidsschema's.
10. **Gebruikersbeheer en account** — eigen gegevens, wachtwoord wijzigen, gebruikers uitnodigen.
11. **Zoeken** over de hele voorraad, plus etiketten/QR waar dat nu ook zit.
12. Doorloop van alle oude routes als eindcontrole, zodat er niets ontbreekt.

## Fase 6 — Overzetten

- Testronde op de preview met een kopie van de echte data.
- Onderhoudsmoment: laatste import draaien, DNS/poort omzetten naar de nieuwe container, oude container uitzetten.
- Oude Python-code blijft in de repo-historie als terugvalpad tot alles stabiel draait.

## Technische keuzes

- Frontend en backend in één TanStack Start-app; serverlogica in server functions, externe endpoints (gedeelde lijsten, eventuele webhooks) als server routes.
- Database benaderd met een lichte SQL-laag met migraties in versiebeheer; geen ORM-magie, zodat het schema leesbaar blijft.
- De app draait in productie als Node-server in Docker op Hetzner — niet op Lovable-hosting, zodat de database lokaal blijft.
- Werkwijze: jij bouwt en beoordeelt in Lovable, Lovable pusht naar GitHub, GitHub Actions deployt naar Hetzner.

## Volgorde van opleveren

Fase 0 en 1 eerst, zodat er zo snel mogelijk op echte data gewerkt wordt. Daarna per fase een werkend geheel, telkens te bekijken op de preview voordat we verder gaan.
