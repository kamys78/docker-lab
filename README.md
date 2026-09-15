# DevOps Hands-On Lab Handbook

A from-scratch, practical walkthrough of Git internals, Docker, Docker Compose, and GitHub Actions CI — built step by step, including real bugs hit and fixed along the way.

---

## Table of Contents

1. [Git Internals](#1-git-internals)
2. [Branching & Merge Conflicts](#2-branching--merge-conflicts)
3. [Remotes, GitHub & PR Workflow](#3-remotes-github--pr-workflow)
4. [Docker — Single Container](#4-docker--single-container)
5. [Docker Compose — Multi-Container App](#5-docker-compose--multi-container-app)
6. [The `depends_on` Race Condition](#6-the-depends_on-race-condition)
7. [GitHub Actions — CI Pipeline](#7-github-actions--ci-pipeline)
8. [Debugging Log — Real Issues Hit](#8-debugging-log--real-issues-hit)
9. [Interview Question Bank](#9-interview-question-bank)

---

## 1. Git Internals

### Mental model
Git is a content-addressable filesystem. Every piece of content is hashed (SHA-1) and stored as an object. Four object types:
- **blob** — file contents (no filename)
- **tree** — directory listing (maps names → blobs/trees)
- **commit** — snapshot pointer (tree + parent + metadata)
- **ref** — human-readable pointer to a commit (branch, tag)

**A branch is just a movable pointer to a commit** — a 41-byte file under `.git/refs/heads/`. Creating a branch is instant because it copies a string, not files.

### Commands used
```bash
mkdir git-lab && cd git-lab
git init
echo "hello devops" > file1.txt
git add file1.txt
git commit -m "first commit"

git log --oneline
git cat-file -p HEAD
git cat-file -p HEAD^{tree}

git branch feature-1
cat .git/refs/heads/feature-1   # same SHA as master — proves branch = pointer

git checkout feature-1
cat .git/HEAD                    # ref: refs/heads/feature-1
```

### Common mistakes
- Forgetting `.gitignore` before first commit → accidentally committing `node_modules`, `.env`, secrets
- Not running `git status` before add/commit — habit, not optional

---

## 2. Branching & Merge Conflicts

### Fast-forward vs true merge
```bash
git checkout -b feature/login-page
# ...commit work...
git checkout master
git merge feature/login-page    # fast-forward: pointer just slides forward
```

When both branches have diverged (each has commits the other doesn't), Git creates a **merge commit** with two parents instead of fast-forwarding.

### Rebase vs Merge
| | Merge | Rebase |
|---|---|---|
| History | Preserves true history, adds merge commit | Rewrites commits on top of target, linear history |
| SHAs | Unchanged | New SHAs for replayed commits |
| Safe on shared branches? | Yes | **No** — never rebase a branch others have pulled |

### Resolving a merge conflict
```bash
git merge branch-a
# CONFLICT (content): Merge conflict in file1.txt
git status                       # shows "both modified"
cat file1.txt                    # shows conflict markers:
# <<<<<<< HEAD
# ...current branch content...
# =======
# ...incoming branch content...
# >>>>>>> branch-a

# manually edit to resolve, remove markers, then:
git add file1.txt
git commit
```

### Common mistakes
1. Panicking and running `git merge --abort` when resolution was actually straightforward
2. Forgetting `git add` after resolving — commit will refuse
3. Leaving conflict markers in the file by accident (always re-check the file before committing)
4. Picking one side without understanding *why* both sides changed

---

## 3. Remotes, GitHub & PR Workflow

```bash
git remote add origin https://github.com/<user>/<repo>.git
git remote -v                    # confirms fetch/push URLs
git branch -M main
git push -u origin main          # -u sets upstream tracking
```

### PR-based workflow
```bash
git checkout -b feature/readme
# ...commit...
git push -u origin feature/readme
# open PR on GitHub targeting main
```

A PR is a **review gate + CI trigger point** — this is the seam where automated pipelines (Section 7) attach to the Git workflow.

### Merge strategies on GitHub (and why they matter)
| Strategy | Effect |
|---|---|
| Merge commit | Preserves every commit, adds a merge commit |
| Squash and merge | Collapses PR into one new commit — **rewrites SHA** |
| Rebase and merge | Replays commits individually — **rewrites SHAs**, linear history |

**Gotcha:** after a squash/rebase merge on GitHub, your local branch diverges from `origin` (shows "ahead 1, behind 1") because the remote commit has a different SHA than your local one, even with identical content. Fix:
```bash
git fetch origin
git reset --hard origin/main
```

### Common mistakes
1. Force-pushing (`--force`) to a shared branch — can wipe teammates' work. Use `--force-with-lease` if you must.
2. Committing directly to `main` instead of using PRs
3. Not pulling before pushing → "rejected, non-fast-forward" error
4. Deleting multiple remote refs in one `push --delete` command — if one ref doesn't exist, **the whole command fails**, including refs that would have succeeded. Delete one at a time when unsure.
5. Running `git branch -M master` from the wrong branch — force-renames whatever branch you're currently on, silently overwriting an existing branch of that name.

### Branch cleanup
```bash
git branch -d <branch>           # safe delete — refuses if unmerged
git branch -D <branch>           # force delete — use with care
git push origin --delete <branch>
git fetch --prune                # sync local view of remote branches
```

---

## 4. Docker — Single Container

### App structure
```
docker-lab/
└── app/
    ├── app.py
    ├── requirements.txt
    ├── Dockerfile
    └── .dockerignore
```

### Dockerfile (annotated)
```dockerfile
FROM python:3.12-slim          # slim = smaller image; avoid alpine here (glibc needed for psycopg2)

WORKDIR /app                   # base dir for all subsequent COPY/RUN

COPY requirements.txt .        # copy deps FIRST — enables layer caching
RUN pip install --no-cache-dir -r requirements.txt

COPY . .                       # copy app code AFTER deps are cached

EXPOSE 5000                    # documentation only — does not publish the port

CMD ["python", "app.py"]       # exec form — runs as PID 1, handles signals properly
```

**Why deps before code:** Docker caches layers. If code is copied first, any code change invalidates the cache for the (slow) pip install layer too. Copying `requirements.txt` alone first means that layer only rebuilds when dependencies actually change.

**Why exec form (`["python", "app.py"]`) not shell form (`python app.py`):** shell form wraps the process in `/bin/sh -c`, adding an extra layer that can swallow signals like `SIGTERM` — matters for graceful shutdown, especially in Kubernetes later.

### `.dockerignore`
```
__pycache__
*.pyc
.git
.env
```
Prevents `COPY . .` from dragging in git history, caches, or secrets.

### Build & run
```bash
docker build -t flask-app:v1 .
docker images
docker history flask-app:v1      # inspect layer sizes

docker run -p 5001:5000 flask-app:v1
```

**Port note:** app must bind `0.0.0.0`, not `127.0.0.1` — `127.0.0.1` inside a container only accepts connections from within that same container.

---

## 5. Docker Compose — Multi-Container App

### `docker-compose.yml`
```yaml
services:
  app:
    build: ./app
    ports:
      - "5001:5000"
    environment:
      DB_HOST: db
      DB_NAME: appdb
      DB_USER: appuser
      DB_PASSWORD: apppass
    depends_on:
      - db

  db:
    image: postgres:16
    environment:
      POSTGRES_DB: appdb
      POSTGRES_USER: appuser
      POSTGRES_PASSWORD: apppass
    volumes:
      - pgdata:/var/lib/postgresql/data
    ports:
      - "5433:5432"

volumes:
  pgdata:
```

### Key concepts
- **`build: ./app`** — path is relative to the **compose file's location**, not your terminal's current directory. Common mistake: placing `docker-compose.yml` in the wrong folder breaks this silently.
- **`DB_HOST: db`** — `db` is the Compose **service name**, resolved via Docker's internal DNS. Containers reach each other by service name, not `localhost`.
- **`volumes: pgdata:/var/lib/postgresql/data`** — without this, DB data lives only in the container's writable layer and is destroyed on `docker-compose down`. Containers are ephemeral; persistent data needs a volume.
- **Official `postgres:16` image** — don't rebuild database engines from scratch; "build from scratch" applies to your own app logic, not well-maintained upstream infra images.

### Commands
```bash
docker-compose up --build
docker ps
docker-compose logs -f app
docker exec -it <db-container> psql -U appuser -d appdb

docker-compose down              # stops containers, keeps volume (data persists)
docker-compose down -v           # stops containers AND deletes volume (data lost)
```

---

## 6. The `depends_on` Race Condition

### The problem
`depends_on` (list form) only guarantees **start order**, not **readiness**. A container can be "started" while the process inside (e.g., Postgres) is still initializing and not yet accepting connections.

### Reproducing it deliberately
Added an artificial delay to force the race window:
```yaml
db:
  command: ["sh", "-c", "sleep 15 && docker-entrypoint.sh postgres"]
```
With plain `depends_on: [db]`, the `app` container starts immediately and `/db-check` reliably fails for ~15 seconds until Postgres finishes its delayed start.

### The fix — healthcheck + conditional depends_on
```yaml
db:
  healthcheck:
    test: ["CMD-SHELL", "pg_isready -U appuser -d appdb"]
    interval: 5s
    timeout: 5s
    retries: 5

app:
  depends_on:
    db:
      condition: service_healthy
```
With this in place, `app` does not start at all until Postgres reports healthy — even with the artificial sleep still present.

**Interview answer:** *"`depends_on` alone only controls start order, not readiness. To guarantee the database is actually accepting connections before the app starts, I use a healthcheck combined with `condition: service_healthy`."*

---

## 7. GitHub Actions — CI Pipeline

### File location (must be exact)
```
docker-lab/
└── .github/
    └── workflows/
        └── docker-ci.yml
```
Must sit at the **repo root** — GitHub only scans `.github/workflows/*.yml` relative to root, not relative to any subfolder.

### `docker-ci.yml`
```yaml
name: Docker CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  build-and-test:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Build Docker image
        run: docker build -t flask-app:ci ./app

      - name: Start app + db with Compose
        run: docker compose up -d --build

      - name: Wait for app to be healthy
        run: |
          for i in {1..10}; do
            if curl -sf http://localhost:5001/db-check; then
              echo "App is healthy"
              exit 0
            fi
            echo "Waiting for app... attempt $i"
            sleep 3
          done
          echo "App never became healthy"
          exit 1

      - name: Show logs on failure
        if: failure()
        run: docker compose logs

      - name: Tear down
        if: always()
        run: docker compose down -v
```

### Key concepts
- **Every job runs on a fresh, empty VM** — no code, no cache, unless a step explicitly restores it. `actions/checkout@v4` is what pulls your repo in; forgetting it is the #1 first-run failure.
- **`on: push` + `pull_request`** — PR runs catch failures before merge; push-to-main runs confirm the merged result still works.
- **`docker compose up -d --build`** — `-d` (detached) is required, otherwise the step blocks forever waiting on a foreground process.
- **Retry loop for `/db-check`** — same readiness problem as Section 6, now in CI. CI runners can be slower/more variable than a local machine, so a single blind `curl` right after `up -d` is a classic source of flaky tests.
- **`if: failure()`** — only dumps logs when something broke; keeps successful runs clean.
- **`if: always()`** on teardown — ensures cleanup happens even after a failure, so containers don't linger on the runner.
- **Secrets** — never hardcode real credentials in the YAML. Use GitHub Secrets (Settings → Secrets and variables → Actions), referenced as `${{ secrets.MY_SECRET }}`.

---

## 8. Debugging Log — Real Issues Hit

| Issue | Root Cause | Fix |
|---|---|---|
| `README.md` not visible on GitHub | Viewing default branch (had a stray `main` vs `master`); PR not yet merged | Standardized default branch, merged PR |
| `ahead 1, behind 1` after merge | GitHub squash-merged the PR, creating a new commit SHA for the same content | `git fetch && git reset --hard origin/main` |
| `git branch -M master` renamed the wrong branch | Command run while sitting on a different branch than intended | Always check `git branch`/prompt before rename commands |
| `push --delete branch-a branch-b feature/login-page` failed entirely | One ref (`feature/login-page`) didn't exist remotely — multi-ref delete failed atomically | Delete refs one at a time |
| `bind: address already in use` on port 5000 | macOS AirPlay Receiver occupies port 5000 by default | Mapped to a different host port (`-p 5001:5000`) |
| `unable to prepare context: path ".../app/app" not found` | `docker-compose.yml` was in the wrong directory (`app/` instead of repo root) — `build:` context resolves relative to the compose file's location | Moved `docker-compose.yml` to correct location |
| `/db-check` fails right after `docker-compose up` | Race condition — `depends_on` doesn't wait for Postgres readiness | Added `healthcheck` + `condition: service_healthy` |
| `.github/workflows/docker-ci.yml` pushed blank | File content never actually got written (editor/heredoc issue) before commit | Rewrote using `cat > file << 'EOF' ... EOF`, verified with `cat` before committing |
| CI failed on `pip install` | Deliberately introduced non-existent package version (`psycopg2-binary==99.99.99`) | Corrected version in `requirements.txt` |

---

## 9. Interview Question Bank

**Git**
- What is a branch, internally? → A pointer file under `.git/refs/heads/` containing a commit SHA; cheap to create.
- Difference between `git fetch` and `git pull`? → `fetch` downloads but doesn't merge; `pull` = fetch + merge (or `--rebase`).
- Rebase vs merge, and when to use each? → Rebase for clean local history before pushing; merge for shared/pushed branches.
- Merge commit vs squash vs rebase merge on a PR? → Full history vs single collapsed commit vs replayed linear history; squash/rebase both rewrite SHAs.
- How do you handle a rejected push? → Pull/rebase, resolve conflicts, push again — never blind force-push shared branches.

**Docker**
- Why order `COPY requirements.txt .` before `COPY . .`? → Layer caching — avoids reinstalling dependencies on every code change.
- What does `EXPOSE` actually do? → Documentation only; doesn't publish a port. `-p` at `docker run` does that.
- Exec form vs shell form of `CMD`? → Exec form runs as PID 1 and handles signals (e.g. `SIGTERM`) correctly; shell form wraps in `/bin/sh -c`, which can swallow signals.
- Does `depends_on` guarantee the database is ready? → No — only start order. Use a healthcheck with `condition: service_healthy` for actual readiness.
- Why use a named volume for the database? → Containers are ephemeral; without a volume, data is lost on `down`/removal.

**GitHub Actions**
- Difference between an Action and a workflow? → A workflow is the full YAML pipeline; an Action is a single reusable step (e.g. `actions/checkout`).
- How do you handle secrets? → GitHub Secrets, injected as environment variables at runtime — never committed.
- How would you speed up a slow pipeline? → Dependency caching (`actions/cache`), parallel jobs, smaller base images, `paths:` filters to skip irrelevant runs.
- Why test DB connectivity in CI, not just that the container starts? → A container "running" doesn't mean the app is functionally correct — end-to-end checks catch real integration failures.


BUILD & TEST JOB
<img width="2218" height="1424" alt="image" src="https://github.com/user-attachments/assets/e4550ab5-3cfe-4083-8b8a-f2f10176af7d" />


---

*Built hands-on, from scratch, no forked repos — every file, config, and bug in this handbook was created and debugged directly.*
