import json
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _as_list(v):
    if v is None or isinstance(v, list):
        return v
    s = str(v).strip()
    if not s:
        return []
    if s.startswith("["):
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            pass
    return [x.strip() for x in s.split(",") if x.strip()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore", env_ignore_empty=True)

    APP_NAME: str = "SellerVision"
    ENV: str = "dev"
    PORT: int = 8000
    DATABASE_URL: str = "sqlite:///./sellervision.db"
    SECRET_KEY: str = "CHANGE_ME_super_secret_key_for_dev_only"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24
    CORS_ORIGINS: list[str] = ["*"]
    ALLOWED_HOSTS: list[str] = ["*"]
    DATA_RETENTION_DAYS: int = 180
    PPC_DIR: str = "data/ppc"
    PPC_SOURCES: list[dict] = []
    DATA_SOURCE: str = "file"
    VST_CACHE_TTL: int = 300
    VST_API_BASE: str = ""
    VST_API_KEY: str = ""
    VST_TIMEOUT: int = 30
    VST_VERIFY_SSL: bool = True

    AMAZON_ADS_CLIENT_ID: str = ""
    AMAZON_ADS_CLIENT_SECRET: str = ""
    AMAZON_ADS_REFRESH_TOKEN: str = ""
    AMAZON_ADS_PROFILE_ID: str = ""
    AMAZON_ADS_REGION: str = "NA"

    AMAZON_SPI_CLIENT_ID: str = ""
    AMAZON_SPI_CLIENT_SECRET: str = ""
    AMAZON_SPI_REFRESH_TOKEN: str = ""
    AMAZON_SPI_MARKETPLACE_ID: str = "ATVPDKIKX0DER"

    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_ROLE_ARN: str = ""
    AWS_REGION: str = "us-east-1"

    # Tu dong dong bo Amazon dinh ky (de mo dashboard luc nao cung co so lieu moi, khong can bam nut)
    AMAZON_AUTO_SYNC_ENABLED: bool = True
    # Gio chay co dinh trong ngay (theo gio marketplace, mac dinh: 01:00, 07:00, 13:00, 19:00)
    # .env: AMAZON_AUTO_SYNC_SCHEDULE_HOURS=1,7,13,19  hoac  [1,7,13,19]
    AMAZON_AUTO_SYNC_SCHEDULE_HOURS: list[int] = [1, 7, 13, 19]
    AMAZON_AUTO_SYNC_DAYS: int = 3

    SUPABASE_URL: str = ""
    SUPABASE_KEY: str = ""


    @field_validator("CORS_ORIGINS", "ALLOWED_HOSTS", mode="before")
    @classmethod
    def _split_lists(cls, v):
        return _as_list(v)

    @field_validator("AMAZON_AUTO_SYNC_SCHEDULE_HOURS", mode="before")
    @classmethod
    def _parse_hours(cls, v):
        if isinstance(v, list):
            return [int(x) for x in v]
        if isinstance(v, str):
            v = v.strip()
            if v.startswith("["):
                try:
                    return [int(x) for x in json.loads(v)]
                except (json.JSONDecodeError, ValueError):
                    pass
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        return v

    @field_validator("PPC_SOURCES", mode="before")
    @classmethod
    def _parse_sources(cls, v):
        if isinstance(v, str):
            v = v.strip()
            return json.loads(v) if v else []
        return v


settings = Settings()
