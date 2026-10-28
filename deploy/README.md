# Put the demo on one AWS server (runbook)

This runbook is for the owner. The server runs sample data and sandbox providers only. It holds no real posting credential. Check AWS's current pricing page before creating resources, and keep the existing billing alert enabled.

## 1. Launch the server

1. Sign in to AWS with the normal administrator user or role, not the root account.
2. Choose one AWS region and keep every resource below in that region.
3. Open **EC2**, choose **Instances**, then **Launch instances**.
4. Name it `okayly-demo` and add the tag `project=okayly`. Tags make every demo resource easier to find and remove.
5. Choose the current Ubuntu LTS image and a small instance type that can comfortably run two containers. Check the selected type against AWS's current pricing page.
6. Select or create a key pair and save its private key only on the owner's computer. Never put it in this repository.
7. Create a security group tagged `project=okayly` with exactly these inbound rules:
   - SSH, TCP port 22, source **My IP** (the owner's current public IP), never `0.0.0.0/0`.
   - HTTP, TCP port 80, source `0.0.0.0/0` and `::/0`.
   - HTTPS, TCP port 443, source `0.0.0.0/0` and `::/0`.
8. Launch the instance and wait until its status checks pass.

## 2. Point a separate demo domain at it

HTTPS needs a domain name. Use a new demo domain that does not link to the owner's other business or reveal a private brand.

In the domain's DNS manager, create an **A** record for the chosen host name whose value is the instance's public IPv4 address. DNS changes can take time to appear. A normal EC2 public address can change after a stop and start; consider attaching an Elastic IP if the address must survive that. Check AWS's current pricing page before allocating one because it can add cost.

## 3. Connect and install Docker

In EC2, select the instance and choose **Connect** for AWS's current connection instructions. From the owner's terminal, connect as Ubuntu using the saved key. Then type:

```sh
sudo apt-get update
sudo apt-get install -y docker.io docker-compose-v2 git
sudo usermod -aG docker "$USER"
exit
```

This installs Docker, Compose, and Git, and grants the login user permission to run Docker. Connect again so the new group membership takes effect. If Ubuntu's current package does not provide `docker-compose-v2`, follow Docker's official Ubuntu installation instructions instead.

## 4. Put the private repository on the server

Clone the repository using a read-only deploy key or an access token entered by the owner. Do not paste a private key or token into chat, save it in this repository, or put it directly in a command that shell history will retain.

```sh
git clone REPOSITORY_URL okayly
cd okayly
cp deploy/env.example .env
chmod 600 .env
nano .env
```

Replace `SITE_ADDRESS` with the new demo domain. The owner must paste the Muse key into the empty `MODEL_API_KEY` field directly in this server-only file, save, and exit. Do not show or print the file. Keep `DAILY_SPEND_CAP_USD` at the intended cap. `DEMO_CONTROLS=1` exposes demo-only buttons to anyone who has the link, so leave it at 1 only while judges need those controls.

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

To update to a reviewed repository version:

```sh
cd okayly
git pull --ff-only
docker compose up -d --build
```

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
