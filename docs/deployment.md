# Putting LedgerMind online

One server in AWS London runs three Docker containers: **nginx** (https, free Let's Encrypt certificate), the
**web app** (Next.js) and the **API server** (FastAPI). The database (AWS RDS PostgreSQL), the files (S3) and the AI (Bedrock)
are all in London too.

```
https://ledgermind.duckdns.org ──► nginx ──┬── /      ──► web app
                                         └── /api   ──► API server ──► RDS · S3 · Bedrock (London)
```

## 1. AWS: a role for the server (no keys on the server)

IAM → Roles → Create role → *AWS service: EC2* → name it `ledgermind-server`, and add this as an inline policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    { "Sid": "Files", "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
      "Resource": "arn:aws:s3:::ledgermind-files-london/*" },
    { "Sid": "ListFiles", "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::ledgermind-files-london" },
    { "Sid": "AI", "Effect": "Allow",
      "Action": "bedrock:InvokeModel",
      "Resource": [
        "arn:aws:bedrock:eu-west-2::foundation-model/deepseek.v3.2",
        "arn:aws:bedrock:eu-west-2::foundation-model/openai.gpt-oss-120b-1:0"
      ] }
  ]
}
```

The server can then use only its own bucket and the two AI models, and there are no AWS keys to leak.

## 2. AWS: the server

EC2 → Launch instance, region **Europe (London) eu-west-2**:

- Image: **Ubuntu 24.04 LTS**; type: **t3.medium** (building a workbook needs the memory); disk: 30 GB
- Key pair: create one and keep the `.pem` file safe (it is how you log in)
- Security group: allow **SSH 22** (from your IP only), **HTTP 80** and **HTTPS 443** (from anywhere)
- Advanced details → IAM instance profile: **ledgermind-server**
- After launch: Elastic IPs → allocate one and associate it with the server (the address then never changes)

## 3. The domain (DuckDNS)

On duckdns.org, set the **ledgermind** domain's IP to the server's **Elastic IP** and press *update ip*.
Check it before step 6: `nslookup ledgermind.duckdns.org` must show the Elastic IP (not your home address).

## 4. Install Docker on the server

```bash
ssh -i ledgermind.pem ubuntu@<elastic-ip>
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker ubuntu && exit        # log in again after this
```

## 5. The code and the settings

```bash
git clone https://github.com/dhruv608/finance-flow.git ledgermind && cd ledgermind
cp .env.example .env                                      # DOMAIN=ledgermind.duckdns.org, NGINX_MODE=http
cp backend/.env.production.example backend/.env.production
nano backend/.env.production                              # DATABASE_URL, ALLOWED_ORIGINS, COMPANIES_HOUSE_API_KEY
```

Leave `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` empty: the server uses its role (step 1).

## 6. Start, get the certificate, switch to https

```bash
docker compose up -d --build                              # NGINX_MODE=http for now
docker compose run --rm --entrypoint certbot certbot certonly --webroot -w /var/www/certbot \
  -d ledgermind.duckdns.org --email <your email> --agree-tos --no-eff-email
sed -i 's/NGINX_MODE=http/NGINX_MODE=https/' .env
docker compose up -d                                      # nginx restarts with https
```

Open https://ledgermind.duckdns.org and sign in. The certificate renews by itself (the certbot container checks twice a
day and nginx reloads every 6 hours).

## 7. Once only: the files from the laptop

The uploads and workbooks made on the laptop are on its disk. On the laptop (with the AWS keys in backend/.env):

```bash
PYTHONPATH=. python backend/scripts/move_files_to_s3.py           # shows what it will copy
PYTHONPATH=. python backend/scripts/move_files_to_s3.py --apply   # copies them and points the records at S3
```

## Deploying (the Deploy button)

GitHub builds the images and the server only pulls them, so a deploy never slows the server down or runs it out of
memory. Push the code, then on GitHub: **Actions > Deploy > Run workflow**. A green tick: the new version is live. A
red cross: nothing changed on the server, the old version is still running.

One-time setup: run `deploy/aws_setup_github_deploy.sh` once in AWS CloudShell (it makes the two ECR image stores and
the permissions; no keys are stored in GitHub).

Backup way (if GitHub is ever not available): on the server, remove the `BACKEND_IMAGE` / `FRONTEND_IMAGE` lines from
`.env` and run `git pull && docker compose build backend && docker compose build frontend && docker compose up -d`
(one image at a time, so the build does not run the server out of memory), then `docker builder prune -af`.

## Everyday

| To do | Command (in the `ledgermind` folder on the server) |
|---|---|
| Update to the latest code | GitHub: Actions > Deploy > Run workflow (see above) |
| See what the API server says | `docker compose logs -f backend` |
| Restart everything | `docker compose restart` |
| Add a sign-in | `docker compose exec backend python backend/scripts/create_user.py` |

## Before real client data goes in

- A Companies House key registered to the firm (not the developer's)
- Remove the old Singapore database and bucket once London has run well for a few days
- The AWS keys in the laptop's backend/.env belong to another project's user: replace them with keys of a user
  limited like the role in step 1
