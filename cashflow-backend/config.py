from functools import lru_cache
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    SUPABASE_URL: str
    SUPABASE_KEY: str
    GROQ_API_KEY: str
    OCR_SPACE_API_KEY: str

    APP_ENV: str = "development"
    ALLOWED_ORIGINS: str = "http://localhost:8080,http://127.0.0.1:8080,http://localhost:3000"
    AUTH_REQUIRED: bool = False
    API_KEY: str | None = Field(default=None, repr=False)
    MAX_UPLOAD_MB: int = 10

    @property
    def origins_list(self) -> list[str]:
        items = [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]
        return items or ["http://localhost:8080"]

    @property
    def max_upload_bytes(self) -> int:
        return max(self.MAX_UPLOAD_MB, 1) * 1024 * 1024

    @model_validator(mode="after")
    def validate_security(self) -> "Settings":
        if self.APP_ENV.lower() == "production" and "*" in self.origins_list:
            raise ValueError("Wildcard CORS is not allowed in production.")
        if self.APP_ENV.lower() == "production" and not self.AUTH_REQUIRED:
            raise ValueError("AUTH_REQUIRED must be true in production.")
        if self.APP_ENV.lower() == "production" and self.AUTH_REQUIRED and not self.API_KEY:
            raise ValueError("API_KEY must be set when AUTH_REQUIRED=true in production.")
        return self

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
