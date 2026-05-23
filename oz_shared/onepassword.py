import logging
import os
import subprocess

import onepassword

_logger = logging.getLogger(__name__)


def load_op_secrets_deprecated() -> None:
    if os.getenv("ENV", "") != "local":
        return

    secrets_raw = os.getenv("SECRETS", "").strip()
    if not secrets_raw:
        _logger.warning("ENV=local but SECRETS is not set; skipping 1Password loader")
        return

    names: list[str] = [s.strip() for s in secrets_raw.split(",") if s.strip()]

    for name in names:
        try:
            result = subprocess.run(
                ["op", "item", "get", name, "--fields", "label=credential", "--reveal"],
                check=True,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError as e:
            _logger.error(
                "1Password CLI (op) not found; cannot load secrets. "
                "Install from https://developer.1password.com/docs/cli", extra=e
            )
            return
        except subprocess.CalledProcessError as exc:
            _logger.error(
                "Failed to fetch secret from 1Password",
                extra={"secret_name": name, "stderr": exc.stderr.strip()},
            )
            continue

        value = result.stdout.strip()
        if not value:
            _logger.warning("1Password returned empty value", extra={"secret_name": name})
            continue

        os.environ[name] = value

    _logger.info("Loaded secrets successfully")


async def load_op_secrets(vault: str = "Dev") -> None:
    """Load secrets via the 1Password SDK using a service account token.

    Requires OP_SERVICE_ACCOUNT_TOKEN env var. The token should be scoped
    to only the target vault. Each name in SECRETS is resolved as
    op://<vault>/<name>/credential.
    """
    if os.getenv("ENV", "") != "local":
        return

    integration_name = os.getenv("OP_SERVICE_ACCOUNT_INTEGRATION_NAME", "")
    if not integration_name:
        _logger.warning("OP_SERVICE_ACCOUNT_INTEGRATION_NAME not set; skipping SDK loader")

    token = os.getenv("OP_SERVICE_ACCOUNT_TOKEN", "").strip()
    if not token:
        _logger.warning("OP_SERVICE_ACCOUNT_TOKEN not set; skipping SDK loader")
        return

    secrets_raw = os.getenv("SECRETS", "").strip()
    if not secrets_raw:
        _logger.warning("ENV=local but SECRETS is not set; skipping 1Password loader")
        return

    names: list[str] = [s.strip() for s in secrets_raw.split(",") if s.strip()]

    client = await onepassword.Client.authenticate(
        auth=token,
        integration_name="oz-shared",
        integration_version="1.0.0",
    )

    for name in names:
        try:
            value = await client.secrets.resolve(f"op://{vault}/{name}/credential")
        except Exception as exc:
            _logger.error(
                "Failed to fetch secret from 1Password SDK",
                extra={"secret_name": name, "error": str(exc)},
            )
            continue

        if not value:
            _logger.warning("1Password SDK returned empty value", extra={"secret_name": name})
            continue

        os.environ[name] = value

    _logger.info("Loaded secrets successfully")
