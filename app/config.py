from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    bot_token: str
    webhook_url: str = ""
    bot_mode: str = "webhook"  # "webhook" | "polling"

    database_url: str

    # Image settings
    flag_width: int = 800
    flag_height: int = 534
    white_threshold: int = 240  # pixels with all channels >= this are "white"
    color_match_tolerance: int = 80  # max RGB Euclidean distance to count as a color match

    # Game settings
    max_guesses_dm: int = 6
    max_guesses_group: int = 10
    timer_initial_seconds: int = 45
    timer_per_guess_seconds: int = 10


settings = Settings()
