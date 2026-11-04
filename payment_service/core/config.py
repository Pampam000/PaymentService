from typing import Literal, Self

from pydantic import AnyHttpUrl, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    environment: Literal["development", "production"] = Field("development", validation_alias="APP_ENV")
    database_url: SecretStr = SecretStr("")
    payment_provider: Literal["yookassa"] = "yookassa"
    yoo_mode: Literal["test", "live"] = "test"
    yoo_test_shop_id: str = ""
    yoo_test_secret_key: SecretStr = SecretStr("")
    yoo_live_shop_id: str = ""
    yoo_live_secret_key: SecretStr = SecretStr("")
    payment_return_url: AnyHttpUrl | None = None
    backend_token: SecretStr = SecretStr("")
    admin_token: SecretStr = SecretStr("")
    backend_base_url: AnyHttpUrl | None = None
    order_lookup_token: SecretStr = SecretStr("")
    payment_event_token: SecretStr = SecretStr("")

    @property
    def yoo_shop_id(self) -> str:
        return self.yoo_test_shop_id if self.yoo_mode == "test" else self.yoo_live_shop_id

    @property
    def yoo_secret_key(self) -> SecretStr:
        return self.yoo_test_secret_key if self.yoo_mode == "test" else self.yoo_live_secret_key

    @model_validator(mode="after")
    def require_production_database(self) -> Self:
        backend_token = self.backend_token.get_secret_value()
        admin_token = self.admin_token.get_secret_value()
        if self.environment == "production" and (not backend_token or not admin_token):
            raise ValueError("BACKEND_TOKEN and ADMIN_TOKEN are required in production")
        if backend_token and backend_token == admin_token:
            raise ValueError("Backend and admin tokens must differ")
        if self.environment == "production" and (self.backend_base_url is None or not self.order_lookup_token.get_secret_value()):
            raise ValueError("BACKEND_BASE_URL and ORDER_LOOKUP_TOKEN are required in production")
        if self.environment == "production" and self.backend_base_url is not None and self.backend_base_url.scheme != "https":
            raise ValueError("BACKEND_BASE_URL must use HTTPS in production")
        if self.order_lookup_token.get_secret_value() in {backend_token, admin_token} and self.order_lookup_token.get_secret_value():
            raise ValueError("Order lookup token must differ from inbound tokens")
        event_token = self.payment_event_token.get_secret_value()
        if self.environment == "production" and not event_token:
            raise ValueError("PAYMENT_EVENT_TOKEN is required in production")
        if event_token and event_token in {backend_token, admin_token, self.order_lookup_token.get_secret_value()}:
            raise ValueError("Payment event token must differ from other service tokens")
        if self.environment == "production" and not self.database_url.get_secret_value():
            raise ValueError("DATABASE_URL is required in production")
        if self.yoo_mode == "live" and self.environment != "production":
            raise ValueError("Live YooKassa mode requires APP_ENV=production")
        if self.yoo_test_shop_id and self.yoo_test_shop_id == self.yoo_live_shop_id:
            raise ValueError("Test and live YooKassa shops must differ")
        if self.yoo_test_secret_key.get_secret_value() and self.yoo_test_secret_key == self.yoo_live_secret_key:
            raise ValueError("Test and live YooKassa keys must differ")
        if self.environment == "production" or self.yoo_shop_id or self.yoo_secret_key.get_secret_value():
            if not self.yoo_shop_id or not self.yoo_secret_key.get_secret_value():
                raise ValueError("Selected YooKassa shop ID and secret key are required together")
            if self.payment_return_url is None:
                raise ValueError("PAYMENT_RETURN_URL is required with YooKassa credentials")
        if self.yoo_mode == "live" and self.payment_return_url is not None:
            if self.payment_return_url.scheme != "https":
                raise ValueError("PAYMENT_RETURN_URL must use HTTPS in live mode")
        return self


settings = Settings()
