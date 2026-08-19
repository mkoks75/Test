# Uitrollen op Hetzner

De applicatie draait als twee containers op de eigen server: de Node-server met
de app, en PostgreSQL met de gegevens. GitHub Actions logt na elke push naar
`main` in via SSH en zet de nieuwe versie neer.

```
Lovable  →  GitHub (main)  →  GitHub Actions  →  SSH  →  Hetzner
                                                          ├── app  (Node, poort 8000)
                                                          ├── db   (PostgreSQL)
                                                          └── backup (dagelijkse dump)
```

## Eenmalig inrichten

1. Zorg dat op de server Docker met de compose-plugin staat en dat de map
   `~/project-maarten` een clone van deze repository is.
2. Maak daar een `.env` aan op basis van `.env.example` en vul de wachtwoorden
   in. Genereer `SESSION_SECRET` met `openssl rand -base64 48`.
3. Maak de mappen aan die de containers gebruiken:
   ```bash
   mkdir -p ~/project-maarten/backups
   ```
4. Start de boel:
   ```bash
   cd ~/project-maarten
   docker compose up -d --build
   ```
   De app-container draait bij het opstarten zelf de migraties uit
   `db/migrations`, dus het schema staat er meteen.
5. Zet in GitHub de secrets `VPS_HOST`, `VPS_USER` en `VPS_SSH_KEY`. Die kunnen
   dezelfde zijn als bij de oude Python-applicatie.

## De bestaande gegevens overzetten

De oude applicatie gebruikte SQLite. Eenmalig omzetten:

```bash
# op de server, met de app tijdelijk gestopt
python3 scripts/sqlite_to_postgres.py data/voorraad.db > /tmp/import.sql
docker compose exec -T db psql -U "$POSTGRES_USER" "$POSTGRES_DB" < /tmp/import.sql
```

Het script neemt de id's één op één over en zet daarna de sequences bij, zodat
nieuwe registraties netjes verdergaan waar de oude applicatie stopte. Het
begint met een `TRUNCATE`, dus je kunt de import zonder gedoe herhalen tijdens
het testen.

## Accounts

De wachtwoorden uit de oude applicatie worden bewust niet meegenomen. Iedereen
stelt eenmalig een nieuw wachtwoord in. Maak of herstel een account met:

```bash
docker compose exec app node scripts/maak-gebruiker.mjs maarten maarten@example.nl --admin
```

Het script drukt een herstel-link af die zeven dagen geldig is; die geef je aan
de gebruiker. Bestaat de gebruikersnaam al, dan wordt het account bijgewerkt en
komt er een nieuwe link. Daarnaast kan iedereen zelf een link aanvragen via
"Wachtwoord vergeten" op het inlogscherm.

Zolang er nog geen SMTP is ingericht, komt de herstel-link in de serverlog te
staan (`docker compose logs app`) in plaats van in de mailbox.

## De database vanuit de Lovable-preview bereiken

Om tijdens het bouwen met echte gegevens te werken, heeft de preview een
`DATABASE_URL` nodig die naar de server wijst. Richt daarvoor het liefst een
losse testdatabase in, zodat de productiegegevens buiten schot blijven:

```bash
docker compose exec db createdb -U "$POSTGRES_USER" voorraad_test
```

Stel PostgreSQL open voor de preview (poort 5432 in de firewall, alleen met
`ssl=require`) en zet de verbindingsstring als `DATABASE_URL` bij de secrets van
het project, samen met een `SESSION_SECRET`.

## Dagelijks onderhoud


- **Backups**: de `backup`-container schrijft elke 24 uur een gzip-dump naar
  `~/project-maarten/backups` en ruimt dumps ouder dan veertien dagen op.
- **Terugzetten**:
  ```bash
  gunzip -c backups/voorraad-20260819-0300.sql.gz \
    | docker compose exec -T db psql -U "$POSTGRES_USER" "$POSTGRES_DB"
  ```
- **Logs**: `docker compose logs -f app`

## Over de build

De productiebuild gebruikt `NITRO_PRESET=node-server`, zodat er een gewone
Node-server uitkomt in plaats van een edge-bundel. Dat gebeurt alleen in de
`Dockerfile`; de preview in Lovable blijft ongewijzigd draaien.
