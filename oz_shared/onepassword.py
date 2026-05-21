import logging
import os
import subprocess

_logger = logging.getLogger(__name__)


def load_op_secrets() -> None:
    if os.getenv("ENV", "") != "local":
        return

    secrets_raw = os.getenv("SECRETS", "").strip()
    if not secrets_raw:
        _logger.warning("ENV=local but SECRETS is not set; skipping 1Password loader")
        return

    names: list[str] = [s.strip() for s in secrets_raw.split(",") if s.strip()]
    loaded: int = 0

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
        loaded += 1

    _logger.info(
        "Loaded secrets from 1Password",
        extra={"count": loaded, "total": len(names)},
    )
