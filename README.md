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

## Deployment

The repo includes:

- [deploy/nginx-protracklite.conf](/home/shantanu/ptlite/deploy/nginx-protracklite.conf)
- [deploy/protracklite.service](/home/shantanu/ptlite/deploy/protracklite.service)
- [deploy.sh](/home/shantanu/ptlite/deploy.sh)

Use `/etc/protracklite.env` on the server for runtime settings. Do not keep production settings inside `/opt/protracklite`, because deploys refresh that directory. For MySQL, for example:

```env
DATABASE_URL=mysql+pymysql://USER:PASSWORD@127.0.0.1:3307/protracklite
BASE_DOMAIN=tasks.omnihire.in
```

If you use SQLite in production, do not keep the database inside `/opt/protracklite`, because release extracts can overwrite it. Use a persistent path outside the app directory, for example:

```env
DATABASE_URL=sqlite:////var/lib/protracklite/protracklite.db
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
- preserves runtime settings by reading environment variables from `/etc/protracklite.env`
- preserves production data because `git archive` does not include ignored files such as local `*.db`
- reinstalls Python dependencies in `/opt/protracklite/.venv`
- reloads systemd and restarts `protracklite`
