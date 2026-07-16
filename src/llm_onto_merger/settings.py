from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Ollama backend
    ollama_model: str = ""
    ollama_host: str = "http://localhost:11434"

    # vLLM backend (OpenAI-compatible)
    use_vllm: bool = False
    vllm_model: str = ""
    vllm_host: str = "http://localhost:8000/v1"

    # OpenRouter backend (OpenAI-compatible), selected via --model on the CLI
    openrouter_api_key: str = ""
    openrouter_host: str = "https://openrouter.ai/api/v1"

    parallel_llm_request_count: int = 4
    debug: bool = False


settings = Settings()
