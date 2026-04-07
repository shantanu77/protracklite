# ProtrackLite

FastAPI implementation of the `protrackLite.md` specification with:

- org-scoped login via `/{org-slug}/`
- task creation, editing, and time logging
- work-rate and Monday report pages
- admin dashboard with team metrics
- MySQL-ready SQLAlchemy models with SQLite fallback for local development

## Local run

1. Create a virtual environment and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Copy env values:

```bash
cp .env.example .env
```

3. Start the app:

```bash
uvicorn app.main:app --reload
```

4. Open `http://127.0.0.1:8000/solulever/login`

Seed admin credentials:

- email: `admin@solulever.com`
- password: `ChangeMe123`

## Deployment

The repo includes:

- [deploy/nginx-protracklite.conf](/home/shantanu/ptlite/deploy/nginx-protracklite.conf)
- [deploy/protracklite.service](/home/shantanu/ptlite/deploy/protracklite.service)
- [deploy.sh](/home/shantanu/ptlite/deploy.sh)

Use `.env` on the server to point `DATABASE_URL` at your MySQL instance, for example:

```env
DATABASE_URL=mysql+pymysql://USER:PASSWORD@127.0.0.1:3307/protracklite
BASE_DOMAIN=tasks.omnihire.in
```

That matches your SSH tunnel pattern:

```bash
ssh -i /home/shantanu/mykey.key -L 3307:10.0.0.3:3306 -N root@37.27.6.17
```

To push `main` and deploy the current committed code to `/opt/protracklite`:

```bash
chmod +x deploy.sh
./deploy.sh
```

The script:

- pushes `main` to `origin`
- uploads the current `HEAD` as a tarball to the VPS
- refreshes `/opt/protracklite`
- reinstalls Python dependencies in `/opt/protracklite/.venv`
- reloads systemd and restarts `protracklite`
