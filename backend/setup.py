"""Interactive model setup; secrets never enter command history or browser fields."""

import getpass
import json
from pathlib import Path

from backend.credentials import save
from backend.interpreter import OpenAIInterpreter


def main():
    model = input("OpenAI model ID supporting Responses structured outputs: ").strip()
    interpreter = OpenAIInterpreter(model)
    key = getpass.getpass("OpenAI API key (hidden): ").strip()
    if not key:
        raise ValueError("API key is required.")
    # Validate before persisting. The key is only kept in this process's environment.
    import os
    os.environ["OPENAI_API_KEY"] = key
    intent = interpreter.trade("Buy 20 USDT of BNB")
    if intent != {"symbol": "BNBUSDT", "amount": "20.00"}:
        raise ValueError("The model did not interpret the setup check correctly.")
    save("openai", {"api_key": key})
    config = Path(__file__).resolve().parents[1] / "data" / "model.json"
    config.write_text(json.dumps({"model": model}), encoding="utf-8")
    print("Model setup verified and saved with Windows user encryption.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError) as exc:
        print(str(exc))
        raise SystemExit(1)
