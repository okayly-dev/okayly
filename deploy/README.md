<!-- Explains how to deploy and operate the sample demo on one AWS server. -->
# Put the demo on one AWS server (runbook)

This runbook is for the owner. The server runs sample data and sandbox providers only. It holds no real posting credential. Check AWS's current pricing page before creating resources, and keep the existing billing alert enabled.

## 1. Launch the server

1. Sign in to AWS with the normal administrator user or role, not the root account.
2. Choose one AWS region and keep every resource below in that region.
3. Open **EC2**, choose **Instances**, then **Launch instances**.
4. Name it `okayly-demo` and add the tag `project=okayly`. Tags make every demo resource easier to find and remove.
5. Choose the current Ubuntu LTS image and a small instance type that can comfortably run two containers. Check the selected type against AWS's current pricing page. For burstable instances, explicitly select Standard CPU credits to avoid surplus CPU charges.
6. Select or create a key pair and save its private key only on the owner's computer. Never put it in this repository.
7. Create a security group tagged `project=okayly` with exactly these inbound rules:
   - SSH, TCP port 22, source **My IP** (the owner's current public IP), never `0.0.0.0/0`.
   - HTTP, TCP port 80, source `0.0.0.0/0` and `::/0`.
   - HTTPS, TCP port 443, source `0.0.0.0/0` and `::/0`.
8. Launch the instance and wait until its status checks pass.

## 2. Point a separate demo domain at it

HTTPS needs a domain name. Use a new demo domain that does not link to the owner's other business or reveal a private brand.

In the domain's DNS manager, create an **A** record for the chosen host name whose value is the instance's public IPv4 address. DNS changes can take time to appear. A normal EC2 public address can change after a stop and start; consider attaching an Elastic IP if the address must survive that. An Elastic IP incurs the public IPv4 hourly charge while in use or idle until released. Replacing a normal public IPv4 with one Elastic IP keeps one charged address. Check AWS's current pricing page before allocating it.

## 3. Connect and install Docker

In EC2, select the instance and choose **Connect** for AWS's current connection instructions. From the owner's terminal, connect as Ubuntu using the saved key. Then type:

```sh
sudo apt-get update
sudo apt-get install -y docker.io docker-compose-v2
sudo usermod -aG docker "$USER"
exit
```

This installs Docker and Compose, and grants the login user permission to run Docker. Connect again so the new group membership takes effect. If Ubuntu's current package does not provide `docker-compose-v2`, follow Docker's official Ubuntu installation instructions instead.

## 4. Copy a reviewed snapshot without history

Until repository history has been reviewed and rewritten, deploy a snapshot of reviewed `master`; do not push or clone the repository. From the local repository:

```sh
git archive --format=tar --output=/tmp/okayly-demo.tar master
tar -tf /tmp/okayly-demo.tar
shasum -a 256 /tmp/okayly-demo.tar
scp -i KEY_FILE /tmp/okayly-demo.tar ubuntu@SERVER_IP:okayly-demo.tar
```

Replace `KEY_FILE` and `SERVER_IP` with the saved SSH key path and the server's fixed IP. Verify the SSH host fingerprint against the instance console before connecting. Check the archive contains no `.git`, `.env`, private information or secret. Only tracked files at the reviewed commit are included; local edits are not. Record the commit and archive checksum in the private deployment handoff.

On the server, compare the checksum with the local result, then unpack into a new empty folder:

```sh
sha256sum okayly-demo.tar
mkdir okayly
tar -xf okayly-demo.tar -C okayly
cd okayly
cp deploy/env.example .env
chmod 600 .env
nano .env
```

Set `SITE_ADDRESS` to the demo domain and **change `DRAFTER` to `fixture`** before the first start. Leave `MODEL_API_KEY` empty. Set `DEMO_CONTROLS=0` for this public check: setting it to 1 lets anyone with the link use reset and tamper controls. Fixture mode uses sample drafts and makes no model calls.

Only after the owner approves live mode, the owner enters the Muse key directly into this server-only `.env`, sets the agreed daily cap, changes `DRAFTER` to `muse`, and restarts. Never print the file or put a key into chat, a shell command or this repository.

Later, after the repository exists and its history has been rewritten and checked, cloning with owner-managed read-only access may replace this snapshot route. Until then, no Git history or repository credential goes onto the server.

## 5. Start and check the demo

```sh
docker compose up -d --build
docker compose ps
```

This builds the app and starts it behind Caddy. Caddy obtains and renews the HTTPS certificate. Open `https://<domain>/api/health`, replacing `<domain>` with the demo domain. A healthy response says `{"ok":true}`.

To inspect recent logs without displaying the `.env` file:

```sh
docker compose logs --tail=100 app caddy
```

## 6. Update, stop, or reset

When the owner has installed `deploy/update-code` on their user PATH, either coding agent or a terminal can run:

```sh
update-code --check
update-code
```

`--check` tests a snapshot of saved `master` without contacting the server. The normal command runs those same checks, shows the exact revision and asks for `deploy` plus that revision before uploading. It does not commit, merge or push; uncommitted edits are not deployed. Server details are read from the private `~/.config/okayly/update-code.json`, outside the repository. The fields are `repo`, `ssh_target`, `key_file`, `known_hosts`, `remote_dir` and the HTTPS `health_url`; `python` optionally selects the local test interpreter, defaulting to the repository's `.venv/bin/python`.

The command builds before stopping the current app, keeps the previous source and image, preserves the server-only `.env` and Docker volumes, and recreates only the app. Caddy is left running. Hosting configuration changes need a separate review. Failed startup restores the previous source and image; it does not undo database changes made by new application code. Old images and source backups are retained for owner-managed cleanup. A successful update records its revision and checksum in the private `update-code.log` beside the configuration. Public verification reads only `/api/health`, never a paid drafting endpoint.

To update before cloning is approved, create and check a new snapshot of reviewed `master`, then copy it as above. Stop the stack and replace its source files with that snapshot while preserving the server-only `.env` and Docker volumes. Start with `docker compose up -d --build`. Do not unpack an archive over `.env` without first checking its contents.

Once a reviewed clone is in use, `git pull --ff-only` followed by `docker compose up -d --build` is the update route.

To stop the demo while keeping its database and HTTPS certificates:

```sh
docker compose down
```

Resetting deletes the sample demo database and cannot be undone. Stop the stack, list the project volumes with `docker volume ls`, and identify the volume whose name ends in `_app_data`. After the owner confirms that exact name, remove it, then start again:

```sh
docker compose down
docker volume rm EXACT_APP_DATA_VOLUME_NAME
docker compose up -d
```

When the demo is finished, stop or terminate the instance and remove any Elastic IP and DNS record that are no longer needed. In AWS, filter resources by the tag `project=okayly` so none are overlooked. Check the billing alert and the AWS billing page afterward.
