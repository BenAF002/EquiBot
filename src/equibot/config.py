import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

# find EquiBot dir
if os.getenv('OPENROUTER_API_KEY') is None:
    ROOT_DIR = Path().resolve()
    while ROOT_DIR.name != 'EquiBot':
        ROOT_DIR = ROOT_DIR.parent
        if ROOT_DIR.name == '':
            break
    ENV_PATH = ROOT_DIR / ".env"
else:
    ENV_PATH = ".env"

class Settings(BaseSettings):
    openrouter_api_key: str
    sec_api_username: str

    model_config = SettingsConfigDict(
        env_file=ENV_PATH, 
        env_file_encoding="utf-8",
        extra="ignore" # prevents crashing if extra vars are in .env
    )

settings = Settings()