import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file from project root
project_root = Path(__file__).parent.parent
env_file = project_root / ".env"
load_dotenv(env_file)


class Settings:
    """Central config loader."""

    # Kalshi
    KALSHI_KEY_ID = os.getenv("KALSHI_KEY_ID")
    KALSHI_KEY_FILE = os.getenv("KALSHI_KEY_FILE", ".secrets/kalshi.pem")
    KALSHI_BASE_URL = "https://external-api.kalshi.com/trade-api/v2"

    # The Odds API
    ODDS_API_KEY = os.getenv("ODDS_API_KEY")
    ODDS_API_BASE_URL = "https://api.the-odds-api.com/v4"

    # Arb thresholds (percent)
    MIN_ARB_MARGIN = 1.0  # Only show arbs with >1% edge after fees

    # Mappings for event/outcome name normalization
    MAPPINGS_FILE = project_root / "config" / "mappings.yaml"

    @classmethod
    def validate(cls):
        """Check that required secrets are set."""
        missing = []
        if not cls.KALSHI_KEY_ID:
            missing.append("KALSHI_KEY_ID")
        if not cls.ODDS_API_KEY:
            missing.append("ODDS_API_KEY")

        if missing:
            raise ValueError(
                f"Missing required environment variables: {', '.join(missing)}\n"
                f"Please copy .env.example to .env and fill in your API credentials."
            )

        # Check that Kalshi key file exists
        key_path = project_root / cls.KALSHI_KEY_FILE
        if not key_path.exists():
            raise FileNotFoundError(
                f"Kalshi private key not found at {key_path}.\n"
                f"Download your .pem file from Kalshi and save it to {cls.KALSHI_KEY_FILE}"
            )

        return True


if __name__ == "__main__":
    try:
        Settings.validate()
        print("[OK] All settings valid")
    except (ValueError, FileNotFoundError) as e:
        print(f"[ERROR] Settings error: {e}")
