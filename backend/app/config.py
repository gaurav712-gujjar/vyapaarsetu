from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DB_HOST: str = "localhost"
    DB_PORT: int = 3306
    DB_USER: str = "vyapaarsetu"
    DB_PASSWORD: str = "changeme"
    DB_NAME: str = "vyapaarsetu"

    JWT_SECRET: str = "change_this_to_a_long_random_string"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480

    ADMIN_EMAIL: str = "admin@vyapaarsetu.in"
    ADMIN_PASSWORD: str = "change_this_admin_password"

    RAZORPAY_KEY_ID: str = ""
    RAZORPAY_KEY_SECRET: str = ""

    QUEUE_POLL_INTERVAL_SECONDS: int = 2
    MAX_RETRIES: int = 5

    # Kept small by default since free-tier MySQL hosts (Aiven, PlanetScale, etc.)
    # cap total concurrent connections low. Raise these only for load testing
    # against a DB that can actually handle it (see locustfile.py).
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 5

    META_VERIFY_TOKEN: str = ""
    META_APP_SECRET: str = ""

    # Chat-commerce (WhatsApp/Instagram order flow via conversation.py)
    GROQ_API_KEY: str = ""                   # for llm.py intent parsing (console.groq.com)
    META_WHATSAPP_TOKEN: str = ""            # WhatsApp Cloud API send-message token
    META_WHATSAPP_PHONE_NUMBER_ID: str = ""  # WhatsApp Cloud API phone number id
    META_PAGE_ACCESS_TOKEN: str = ""         # Instagram/Page send-message token
    RAZORPAY_WEBHOOK_SECRET: str = ""        # set in Razorpay Dashboard > Webhooks

    # Used to SEND messages back to customers (different from the inbound
    # webhook tokens above). Get these from Meta App Dashboard > WhatsApp >
    # API Setup (temporary token, or a permanent System User token for prod),
    # and the phone_number_id shown on the same page.
    META_WHATSAPP_TOKEN: str = ""
    META_WHATSAPP_PHONE_NUMBER_ID: str = ""
    # Facebook Page access token, used for sending Instagram DM replies.
    META_PAGE_ACCESS_TOKEN: str = ""

    # Anthropic API key for the chat-commerce intent parser (llm.py).
    ANTHROPIC_API_KEY: str = ""

    # Razorpay Dashboard > Settings > Webhooks > (create one) > Secret.
    # Used to verify /api/webhooks/razorpay requests are genuinely from Razorpay.
    RAZORPAY_WEBHOOK_SECRET: str = ""
    WHATSAPP_BUSINESS_NUMBER: str = ""

    @property
    def database_url(self) -> str:
        return (
            f"mysql+pymysql://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}?charset=utf8mb4"
        )

    class Config:
        env_file = ".env"


settings = Settings()